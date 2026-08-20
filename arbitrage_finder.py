"""Arbitrage / +EV detection engine.

Scans sports events from The Odds API (or offline data) and produces:

* **arbitrage_opportunities** — cross-bookmaker arbs for h2h, totals,
  spreads, outrights and back/lay (exchange) markets, with optimal
  stake splits and guaranteed profit per outcome;
* **value_bets** — positive-EV opportunities computed against a
  consensus no-vig (devigged) market probability, the approach used by
  modern +EV tools like OddsJam;
* **odds_screen** — every book's lines per event (the "Odds Screen"
  comparison view), including the low-hold badge data.

Bugs fixed relative to the original engine:
* arbs now require at least two *different* bookmakers (the old h2h code
  happily "found" arbs where one book's own market summed under 100%);
* outrights events (which have no home/away teams) no longer crash;
* h2h_lay / outrights_lay are actually implemented (back-vs-lay math with
  exchange commission) instead of logging "unsupported market";
* totals/spreads are evaluated per line (point) with a cross-book check;
* spreads no longer mix a 'spread' key into the odds dict.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone

from calculators import (
    arbitrage_margin,
    arbitrage_stakes,
    consensus_fair_probabilities,
    expected_value,
    format_american,
    hold_percentage,
    implied_probability,
    lay_arbitrage_margin,
    lay_arbitrage_stakes,
)
from odds_api import OddsAPI

log = logging.getLogger("arbfinder")

SUMMARY_MARKETS = ("h2h", "spreads", "totals")  # markets shown in the odds screen


class ArbitrageFinder:
    def __init__(self, config):
        self.config = config
        self.odds_api = OddsAPI(config)
        self.setup_logging()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def setup_logging(self):
        log.setLevel(logging.INFO if self.config.verbose else logging.WARNING)
        if not log.handlers:
            fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            try:
                fh = logging.FileHandler("arbitrage_finder.log")
                fh.setFormatter(fmt)
                log.addHandler(fh)
            except OSError:
                pass
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(fmt)
            log.addHandler(sh)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def find_arbitrage(self) -> dict:
        started = datetime.now(timezone.utc)
        sports = self.odds_api.get_sports()

        if not sports:
            log.error("No sports available (check API key / network).")
            return self._empty_results(started)

        log.info("Analyzing %d in-season sports: %s", len(sports),
                 ", ".join(s["key"] for s in sports))

        all_arbs: list = []
        all_value_bets: list = []
        odds_screen: list = []
        total_events = 0
        markets_seen: set = set()

        for sport in sports:
            sport_key = sport["key"]
            events = self.odds_api.get_odds(sport_key)
            if self.odds_api.api_limit_reached:
                log.warning("API quota exhausted — stopping the scan.")
                break
            if not events:
                continue
            total_events += len(events)
            log.info("  %s: %d events", sport.get("title", sport_key), len(events))
            for event in events:
                try:
                    arbs, value_bets = self.analyze_event(event, sport)
                    all_arbs.extend(arbs)
                    all_value_bets.extend(value_bets)
                    for arb in arbs:
                        markets_seen.add(arb["market"])
                    screen = self.build_odds_screen(event, sport)
                    if screen:
                        odds_screen.append(screen)
                except Exception as exc:  # never let one event kill the scan
                    log.error("Error analyzing event %s: %s", event.get("id"), exc)
                    continue

        all_arbs.sort(key=lambda a: a["profit_margin"], reverse=True)
        all_value_bets.sort(key=lambda v: v["ev_percent"], reverse=True)

        results = {
            "generated_at": started.isoformat(),
            "source": self._source_name(),
            "fallback_reason": self.odds_api.fallback_reason,
            "config": self.config.to_dict(),
            "api_usage": {
                "remaining_requests": self.odds_api.remaining_requests,
                "used_requests": self.odds_api.used_requests,
            } if self._source_name() == "live" and self.odds_api.remaining_requests else None,
            "summary": {
                "sports_analyzed": len(sports),
                "events_analyzed": total_events,
                "arbitrage_opportunities": len(all_arbs),
                "value_bets": len(all_value_bets),
                "markets_analyzed": sorted(markets_seen) or list(self.config.markets),
            },
            "arbitrage_opportunities": all_arbs,
            "value_bets": all_value_bets[:400],
            "odds_screen": odds_screen,
        }
        log.info("Done: %d arbs, %d +EV bets across %d events.",
                 len(all_arbs), len(all_value_bets), total_events)
        if self.config.verbose:
            print(f"\n✓ Scan complete: {len(all_arbs)} arbitrage opportunity(ies), "
                  f"{len(all_value_bets)} +EV bet(s), {total_events} events.")
        return results

    def _source_name(self) -> str:
        if self.config.offline_file:
            return "offline-file"
        if self.odds_api.using_sample_data:
            return "sample-data"
        return "live"

    def _empty_results(self, started) -> dict:
        return {
            "generated_at": started.isoformat(),
            "source": self._source_name(),
            "fallback_reason": self.odds_api.fallback_reason,
            "config": self.config.to_dict(),
            "api_usage": None,
            "summary": {"sports_analyzed": 0, "events_analyzed": 0,
                        "arbitrage_opportunities": 0, "value_bets": 0,
                        "markets_analyzed": list(self.config.markets)},
            "arbitrage_opportunities": [],
            "value_bets": [],
            "odds_screen": [],
        }

    # ------------------------------------------------------------------
    # Event analysis
    # ------------------------------------------------------------------

    def analyze_event(self, event, sport) -> tuple[list, list]:
        arbs: list = []
        value_bets: list = []
        for market in self.config.markets:
            if market in ("h2h", "outrights"):
                self._analyze_nway(event, sport, market, arbs, value_bets)
            elif market in ("h2h_lay", "outrights_lay"):
                self._analyze_lay(event, sport, market, arbs)
            elif market == "totals":
                self._analyze_two_side_by_point(event, sport, "totals", arbs, value_bets)
            elif market == "spreads":
                self._analyze_two_side_by_point(event, sport, "spreads", arbs, value_bets)
        return arbs, value_bets

    # ------------------------------------------------------------------
    # Odds screen (per-event, per-book line comparison)
    # ------------------------------------------------------------------

    def build_odds_screen(self, event, sport) -> dict | None:
        if not (event.get("home_team") and event.get("away_team")):
            return None  # outrights have no head-to-head screen
        books = {}
        best = {"h2h": {}, "spreads": {}, "totals": {}}
        for book in event.get("bookmakers") or []:
            bkey = book.get("key")
            btitle = book.get("title") or bkey
            entry = {"title": btitle}
            for market in book.get("markets") or []:
                mkey = market.get("key")
                if mkey not in ("h2h", "spreads", "totals"):
                    continue
                outcomes = market.get("outcomes") or []
                if not outcomes:
                    continue
                point = outcomes[0].get("point")
                side = {}
                for o in outcomes:
                    price = o.get("price")
                    name = o.get("name")
                    if not price:
                        continue
                    key = self._side_key(mkey, name, event)
                    if key is None:
                        continue
                    side[key] = {"price": price, "american": format_american(price)}
                    col = best[mkey].setdefault(point if mkey != "h2h" else "h2h", {})
                    if key not in col or price > col[key]["price"]:
                        col[key] = {"price": price, "american": format_american(price)}
                if side:
                    entry[mkey] = {"point": point, "sides": side}
            if any(k in entry for k in ("h2h", "spreads", "totals")):
                books[bkey] = entry

        hold = {}
        for mkey in ("h2h", "spreads", "totals"):
            columns = best[mkey]
            if not columns:
                continue
            # pick the line with the most books for the hold computation
            line = max(columns, key=lambda k: len(columns[k]))
            prices = [v["price"] for v in columns[line].values()]
            h = hold_percentage(prices)
            if h is not None:
                hold[mkey] = round(h * 100, 2)
        return {
            "sport_key": sport["key"],
            "sport_title": sport.get("title", sport["key"]),
            "event": self._event_label(event),
            "event_id": event.get("id"),
            "commence_time": event.get("commence_time"),
            "starts_in_minutes": self._minutes_until(event.get("commence_time")),
            "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
            "books": books,
            "best": {k: v for k, v in best.items() if v},
            "hold": hold,
        }

    @classmethod
    def _side_key(cls, market, name, event) -> str | None:
        if market == "h2h":
            lowered = name.lower()
            home = event.get("home_team")
            away = event.get("away_team")
            if home and lowered == home.lower():
                return "home"
            if away and lowered == away.lower():
                return "away"
            if lowered in ("home", "h", "favorite", "favourite"):
                return "home"
            if lowered in ("away", "a", "underdog"):
                return "away"
            return "draw" if lowered in ("draw", "tie", "x") else None
        if market == "totals":
            return "over" if name.lower() == "over" else "under" if name.lower() == "under" else None
        if market == "spreads":
            return "home" if cls._is_home(name, event) else "away"
        return None

    # ------------------------------------------------------------------
    # Market data extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _outcome_groups(event, market_key) -> dict:
        """Group decimal prices per outcome name: name -> [(price, book_key, book_title)]"""
        groups = defaultdict(list)
        for book in event.get("bookmakers") or []:
            for market in book.get("markets") or []:
                if market.get("key") != market_key:
                    continue
                for outcome in market.get("outcomes") or []:
                    price = outcome.get("price")
                    if not price or price <= 1.0:
                        continue
                    groups[outcome["name"]].append(
                        (price, book.get("key"), book.get("title") or book.get("key"))
                    )
        # keep only the best price per book per outcome
        cleaned = {}
        for name, entries in groups.items():
            best_per_book = {}
            for price, bkey, btitle in entries:
                if bkey not in best_per_book or price > best_per_book[bkey][0]:
                    best_per_book[bkey] = (price, btitle)
            cleaned[name] = [(p, k, t) for k, (p, t) in best_per_book.items()]
        return cleaned

    @staticmethod
    def _event_label(event) -> str:
        if event.get("title"):
            return event["title"]
        home = event.get("home_team") or "?"
        away = event.get("away_team") or "?"
        return f"{home} vs {away}"

    def _make_arb(self, event, sport, market, outcomes, points, margin_pct,
                  total_implied, hold):
        """Build the standard arbitrage record + stake split."""
        odds_list = [o["odds"] for o in outcomes]
        stakes, guaranteed = arbitrage_stakes(odds_list, self.config.stake)
        for o, s in zip(outcomes, stakes):
            o["stake"] = round(s, 2)
            o["stake_pct"] = round(100 * s / self.config.stake, 2)
            o["return"] = round(o["odds"] * s, 2)
        return {
            "id": self._arb_id(event, market, points, outcomes),
            "sport_key": sport["key"],
            "sport_title": sport.get("title", sport["key"]),
            "event": self._event_label(event),
            "event_id": event.get("id"),
            "commence_time": event.get("commence_time"),
            "starts_in_minutes": self._minutes_until(event.get("commence_time")),
            "market": market,
            "points": points,
            "n_way": len(outcomes),
            "profit_margin": round(margin_pct, 3),
            "profit_per_100": round(margin_pct, 3),
            "guaranteed_return": round(guaranteed, 2),
            "total_implied_prob": round(total_implied, 5),
            "hold": round(hold, 5) if hold is not None else None,
            "stake": self.config.stake,
            "outcomes": outcomes,
            # legacy fields kept for compatibility with older consumers
            "best_odds": {o["name"]: o["odds"] for o in outcomes},
            "bookmakers": {o["name"]: o["bookmaker"] for o in outcomes},
        }

    @staticmethod
    def _arb_id(event, market, points, outcomes) -> str:
        raw = "|".join([
            str(event.get("sport_key", "")), str(event.get("id", "")), market,
            str(points or ""), "|".join(sorted(o["name"] for o in outcomes)),
        ])
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _minutes_until(commence_time) -> int | None:
        if not commence_time:
            return None
        try:
            t = datetime.fromisoformat(str(commence_time).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            return max(0, int((t - datetime.now(timezone.utc)).total_seconds() // 60))
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # n-way markets (h2h, outrights)
    # ------------------------------------------------------------------

    def _analyze_nway(self, event, sport, market, arbs, value_bets):
        groups = self._outcome_groups(event, market)
        if len(groups) < 2:
            return
        best = {}
        for name, entries in groups.items():
            price, bkey, btitle = max(entries, key=lambda e: e[0])
            best[name] = {"name": name, "odds": price, "bookmaker": btitle,
                          "bookmaker_key": bkey,
                          "american": format_american(price),
                          "implied_prob": round(implied_probability(price), 5)}

        books_used = {b["bookmaker_key"] for b in best.values()}
        if len(books_used) < 2:
            return  # same book on every side is not an arbitrage

        odds_list = [b["odds"] for b in best.values()]
        margin = arbitrage_margin(odds_list)
        total_implied = sum(1 / d for d in odds_list)
        if margin is not None:
            margin_pct = margin * 100
            if self.config.cutoff <= margin_pct <= self.config.max_profit:
                arbs.append(self._make_arb(
                    event, sport, market,
                    [dict(b) for b in best.values()], None, margin_pct,
                    total_implied, hold_percentage(odds_list)))

        # +EV: fair probability from the consensus, EV of the best price.
        # Require at least two distinct books pricing the market, otherwise
        # the "consensus" is just one book's own margin.
        all_books = {bkey for entries in groups.values() for _, bkey, _ in entries}
        if len(all_books) >= 2:
            fair = consensus_fair_probabilities({n: [e[0] for e in es] for n, es in groups.items()})
            for name, b in best.items():
                ev = expected_value(fair.get(name, 0.0), b["odds"])
                if ev >= self.config.min_ev / 100:
                    value_bets.append(self._value_bet(
                        event, sport, market, None, b, fair.get(name, 0.0)))

    # ------------------------------------------------------------------
    # Two-side markets grouped by line (totals, spreads)
    # ------------------------------------------------------------------

    def _analyze_two_side_by_point(self, event, sport, market, arbs, value_bets):
        if market == "totals":
            sides = ("Over", "Under")
        else:
            sides = self._spread_sides(event)
            if not sides:
                return
        by_point = defaultdict(lambda: {s: [] for s in sides})
        for book in event.get("bookmakers") or []:
            for m in book.get("markets") or []:
                if m.get("key") != market:
                    continue
                for outcome in m.get("outcomes") or []:
                    point = outcome.get("point")
                    name = outcome.get("name")
                    price = outcome.get("price")
                    if point is None or price is None or price <= 1.0:
                        continue
                    if market == "spreads":
                        name = sides[0] if self._is_home(outcome.get("name"), event) else sides[1]
                    if name in by_point[point]:
                        by_point[point][name].append(
                            (price, book.get("key"), book.get("title") or book.get("key")))

        for point, side_entries in by_point.items():
            best = {}
            groups = {}
            for side in sides:
                entries = side_entries[side]
                if not entries:
                    break
                # best price per book first
                best_per_book = {}
                for price, bkey, btitle in entries:
                    if bkey not in best_per_book or price > best_per_book[bkey][0]:
                        best_per_book[bkey] = (price, btitle)
                deduped = [(p, k, t) for k, (p, t) in best_per_book.items()]
                groups[side] = [e[0] for e in deduped]
                price, bkey, btitle = max(deduped, key=lambda e: e[0])
                best[side] = {"name": side, "odds": price, "bookmaker": btitle,
                              "bookmaker_key": bkey, "american": format_american(price),
                              "implied_prob": round(implied_probability(price), 5),
                              "point": point}
            if len(best) != len(sides):
                continue
            if len({b["bookmaker_key"] for b in best.values()}) < 2:
                continue  # both sides from the same book = no arb

            odds_list = [best[s]["odds"] for s in sides]
            margin = arbitrage_margin(odds_list)
            total_implied = sum(1 / d for d in odds_list)
            if margin is not None:
                margin_pct = margin * 100
                if self.config.cutoff <= margin_pct <= self.config.max_profit:
                    arbs.append(self._make_arb(
                        event, sport, market, [dict(best[s]) for s in sides],
                        point, margin_pct, total_implied, hold_percentage(odds_list)))

            # +EV needs a genuine consensus: >=2 distinct books at this line.
            books_at_point = {bkey for side in sides for _, bkey, _ in side_entries[side]}
            if len(books_at_point) >= 2:
                fair = consensus_fair_probabilities(groups)
                for side in sides:
                    b = best[side]
                    ev = expected_value(fair.get(side, 0.0), b["odds"])
                    if ev >= self.config.min_ev / 100:
                        value_bets.append(self._value_bet(
                            event, sport, market, point, b, fair.get(side, 0.0)))

    def _spread_sides(self, event):
        home = event.get("home_team")
        away = event.get("away_team")
        if home and away:
            return (home, away)
        # fall back to whatever names appear in spread outcomes
        names = set()
        for book in event.get("bookmakers") or []:
            for m in book.get("markets") or []:
                if m.get("key") == "spreads":
                    for o in m.get("outcomes") or []:
                        names.add(o.get("name"))
        if len(names) >= 2:
            return sorted(names)[:2]
        return None

    @staticmethod
    def _is_home(outcome_name, event) -> bool:
        """Spread outcomes are team names; map to the home side by name."""
        if not outcome_name:
            return False
        lowered = outcome_name.lower()
        home = event.get("home_team")
        if home and lowered == home.lower():
            return True
        away = event.get("away_team")
        if away and lowered == away.lower():
            return False
        # Some feeds use generic labels instead of team names.
        if lowered in ("home", "h", "favorite", "favourite"):
            return True
        return False

    # ------------------------------------------------------------------
    # Back / lay (exchange) markets: h2h_lay, outrights_lay
    # ------------------------------------------------------------------

    def _analyze_lay(self, event, sport, lay_market, arbs):
        """Back the best price (h2h/outrights) and lay the same outcome at
        an exchange. Profit when back_odds > lay_odds - commission."""
        back_market = "h2h" if lay_market == "h2h_lay" else "outrights"
        back_groups = self._outcome_groups(event, back_market)
        lay_groups = self._outcome_groups(event, lay_market)
        if not back_groups or not lay_groups:
            return
        for name in back_groups.keys() & lay_groups.keys():
            back_price, back_key, back_title = max(back_groups[name], key=lambda e: e[0])
            lay_price, lay_key, lay_title = min(lay_groups[name], key=lambda e: e[0])
            if back_key == lay_key:
                continue
            margin = lay_arbitrage_margin(back_price, lay_price, self.config.lay_commission)
            if margin is None:
                continue
            margin_pct = margin * 100
            if not (self.config.cutoff <= margin_pct <= self.config.max_profit):
                continue
            lay_stake, profit = lay_arbitrage_stakes(
                back_price, lay_price, self.config.lay_commission, self.config.stake)
            outcomes = [
                {"name": f"Back {name}", "odds": back_price, "bookmaker": back_title,
                 "bookmaker_key": back_key, "american": format_american(back_price),
                 "implied_prob": round(implied_probability(back_price), 5),
                 "stake": round(self.config.stake, 2), "stake_pct": 100.0,
                 "return": round(back_price * self.config.stake, 2)},
                {"name": f"Lay {name} (exch.)", "odds": lay_price, "bookmaker": lay_title,
                 "bookmaker_key": lay_key, "american": format_american(lay_price),
                 "implied_prob": round(implied_probability(lay_price), 5),
                 "stake": round(lay_stake, 2), "stake_pct": round(100 * lay_stake / (self.config.stake + lay_stake), 2),
                 "return": round(back_price * self.config.stake, 2)},
            ]
            arbs.append({
                "id": self._arb_id(event, lay_market, None, outcomes),
                "sport_key": sport["key"],
                "sport_title": sport.get("title", sport["key"]),
                "event": self._event_label(event),
                "event_id": event.get("id"),
                "commence_time": event.get("commence_time"),
                "starts_in_minutes": self._minutes_until(event.get("commence_time")),
                "market": lay_market,
                "points": None,
                "n_way": 2,
                "profit_margin": round(margin_pct, 3),
                "profit_per_100": round(margin_pct, 3),
                "guaranteed_return": round(profit + self.config.stake, 2),
                "total_implied_prob": None,
                "hold": None,
                "stake": self.config.stake,
                "lay_commission": self.config.lay_commission,
                "outcomes": outcomes,
                "best_odds": {o["name"]: o["odds"] for o in outcomes},
                "bookmakers": {o["name"]: o["bookmaker"] for o in outcomes},
            })

    # ------------------------------------------------------------------
    # +EV record + odds screen
    # ------------------------------------------------------------------

    def _value_bet(self, event, sport, market, point, best, fair_prob):
        return {
            "id": hashlib.sha1("|".join([
                str(event.get("id")), market, str(point or ""), best["name"],
            ]).encode()).hexdigest()[:16],
            "sport_key": sport["key"],
            "sport_title": sport.get("title", sport["key"]),
            "event": self._event_label(event),
            "commence_time": event.get("commence_time"),
            "starts_in_minutes": self._minutes_until(event.get("commence_time")),
            "market": market,
            "points": point,
            "outcome": best["name"],
            "odds": best["odds"],
            "american": best["american"],
            "bookmaker": best["bookmaker"],
            "bookmaker_key": best["bookmaker_key"],
            "fair_prob": round(fair_prob, 5),
            "implied_prob": best["implied_prob"],
            "ev_percent": round(expected_value(fair_prob, best["odds"]) * 100, 2),
            "sharp": best["bookmaker_key"] == "pinnacle",
        }
