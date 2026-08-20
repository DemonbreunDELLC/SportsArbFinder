"""Deterministic, realistic sample data so the app runs (and demos well)
without an API key or network access.

The generated payload mirrors The Odds API v4 response shape exactly
(``sports`` + ``odds``), so it can be consumed by the same code path as a
saved live response. A fixed seed keeps the demo stable across runs.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

SEED = 20260819  # "current gen" reference date

BOOKS_US = [
    ("fanduel", "FanDuel"), ("draftkings", "DraftKings"), ("betmgm", "BetMGM"),
    ("caesars", "Caesars"), ("betrivers", "BetRivers"), ("pointsbetus", "PointsBet"),
    ("pinnacle", "Pinnacle"), ("williamhill_us", "William Hill"), ("fliff", "Fliff"),
]
BOOKS_UK = [
    ("bet365", "bet365"), ("williamhill", "William Hill"), ("betfred", "Betfred"),
    ("unibet", "Unibet"), ("pinnacle", "Pinnacle"), ("888sport", "888sport"),
    ("betfair", "Betfair"), ("marathonbet", "Marathonbet"),
]

SPORTS = [
    {
        "key": "basketball_nba", "title": "NBA", "group": "Basketball",
        "teams": ["Lakers", "Celtics", "Warriors", "Nuggets", "Bucks", "Suns", "Heat", "Knicks",
                  "Thunder", "Mavericks", "Clippers", "76ers", "Timberwolves", "Pelicans", "Cavaliers", "Pacers"],
        "events": 6, "total_mean": 225.0, "total_sigma": 1.5, "spread_scale": 9.5,
    },
    {
        "key": "baseball_mlb", "title": "MLB", "group": "Baseball",
        "teams": ["Yankees", "Dodgers", "Phillies", "Braves", "Orioles", "Astros", "Guardians", "Padres",
                  "Mets", "Mariners", "Twins", "Brewers", "Red Sox", "Rangers", "Diamondbacks", "Cubs"],
        "events": 8, "total_mean": 8.5, "total_sigma": 0.5, "spread_scale": 3.0,
    },
    {
        "key": "americanfootball_nfl", "title": "NFL", "group": "American Football",
        "teams": ["Chiefs", "Eagles", "49ers", "Ravens", "Cowboys", "Bengals", "Bills", "Lions",
                  "Packers", "Dolphins", "Jets", "Texans", "Steelers", "Chargers", "Falcons", "Bears"],
        "events": 4, "total_mean": 45.0, "total_sigma": 2.0, "spread_scale": 6.0,
    },
    {
        "key": "icehockey_nhl", "title": "NHL", "group": "Ice Hockey",
        "teams": ["Rangers", "Oilers", "Panthers", "Avalanche", "Maple Leafs", "Bruins", "Stars", "Golden Knights",
                  "Canucks", "Hurricanes", "Devils", "Kings", "Lightning", "Wild", "Jets", "Red Wings"],
        "events": 4, "total_mean": 6.0, "total_sigma": 0.5, "spread_scale": 2.5,
    },
    {
        "key": "soccer_epl", "title": "English Premier League", "group": "Soccer",
        "teams": ["Arsenal", "Manchester City", "Liverpool", "Chelsea", "Manchester United", "Tottenham",
                  "Newcastle", "Aston Villa", "Brighton", "West Ham", "Everton", "Fulham"],
        "events": 6, "total_mean": 2.75, "total_sigma": 0.25, "three_way": True,
    },
    {
        "key": "soccer_uefa_champs_league", "title": "UEFA Champions League", "group": "Soccer",
        "teams": ["Real Madrid", "Bayern Munich", "Barcelona", "Paris Saint-Germain", "Inter Milan", "Arsenal",
                  "Manchester City", "Borussia Dortmund"],
        "events": 4, "total_mean": 2.75, "total_sigma": 0.25, "three_way": True,
    },
    {
        "key": "tennis_atp", "title": "ATP Tennis", "group": "Tennis",
        "teams": ["Alcaraz", "Sinner", "Djokovic", "Medvedev", "Zverev", "Rune", "Fritz", "Shelton",
                  "Rublev", "de Minaur", "Tiafoe", "Hurkacz"],
        "events": 6, "two_way": True,
    },
    {
        "key": "americanfootball_ncaaf", "title": "NCAA Football", "group": "American Football",
        "teams": ["Georgia", "Ohio State", "Alabama", "Texas", "Michigan", "Oregon", "Notre Dame", "Penn State",
                  "Clemson", "LSU", "Oklahoma", "Tennessee"],
        "events": 4, "total_mean": 52.0, "total_sigma": 3.0, "spread_scale": 9.0,
    },
    {
        "key": "baseball_mlb_world_series_winner", "title": "MLB World Series Winner", "group": "Baseball",
        "outright": True, "outcomes": 10, "events": 1,
        "teams": ["Yankees", "Dodgers", "Phillies", "Braves", "Orioles", "Astros", "Guardians", "Padres",
                  "Mets", "Mariners", "Twins", "Brewers"],
    },
    {
        "key": "soccer_uefa_champs_league_winner", "title": "UEFA Champions League Winner", "group": "Soccer",
        "outright": True, "outcomes": 12, "events": 1,
        "teams": ["Real Madrid", "Bayern Munich", "Barcelona", "Paris Saint-Germain", "Inter Milan",
                  "Arsenal", "Manchester City", "Borussia Dortmund", "Liverpool", "Juventus"],
    },
]


def _event_id(parts) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:24]


def _clamp(p, lo=0.04, hi=0.96):
    return max(lo, min(hi, p))


def _price(implied, margin):
    return round(1.0 / (_clamp(implied) * margin), 3)


def _gen_h2h(rng, p_home, p_away, books, three_way=False, home="Home", away="Away"):
    """Return a list of bookmaker dicts each carrying an h2h market.

    Outcome names use the real team names (like The Odds API does).
    """
    out = []
    draw_p = 0.0
    if three_way:
        draw_p = rng.uniform(0.20, 0.30) * (1 - 0.08)
    for bk_key, bk_title in books:
        if rng.random() < 0.04:
            continue  # some books don't post this market
        margin = 1 + rng.uniform(0.02, 0.05)
        if three_way:
            ph = _clamp(p_home * (1 - draw_p) + rng.gauss(0, 0.012))
            pd = _clamp(draw_p + rng.gauss(0, 0.010))
            pa = _clamp(1 - ph - pd)
            outcomes = [
                {"name": home, "price": _price(ph, margin)},
                {"name": "Draw", "price": _price(pd, margin)},
                {"name": away, "price": _price(pa, margin)},
            ]
        else:
            ph = _clamp(p_home + rng.gauss(0, 0.012))
            pa = _clamp(p_away + rng.gauss(0, 0.012))
            outcomes = [
                {"name": home, "price": _price(ph, margin)},
                {"name": away, "price": _price(pa, margin)},
            ]
        out.append({"key": bk_key, "title": bk_title, "markets": [
            {"key": "h2h", "outcomes": outcomes},
        ]})
    return out


def _gen_totals(rng, total_point, books, over_implied):
    """Attach a totals market to every book."""
    for i, book in enumerate(books):
        margin = 1 + rng.uniform(0.02, 0.05)
        pt = total_point + rng.choice([0.0, 0.0, 0.0, -0.5, 0.5, -1.0, 1.0])
        oi = _clamp(over_implied + rng.gauss(0, 0.012))
        ui = _clamp(1 - oi + rng.gauss(0, 0.008))
        book["markets"].append({
            "key": "totals",
            "outcomes": [
                {"name": "Over", "price": _price(oi, margin), "point": pt},
                {"name": "Under", "price": _price(ui, margin), "point": pt},
            ],
        })
    return books


def _gen_spreads(rng, point, books, home_cover_implied, home_name, away_name):
    for book in books:
        margin = 1 + rng.uniform(0.02, 0.05)
        hc = _clamp(home_cover_implied + rng.gauss(0, 0.012))
        ac = _clamp(1 - hc + rng.gauss(0, 0.008))
        book["markets"].append({
            "key": "spreads",
            "outcomes": [
                {"name": home_name, "price": _price(hc, margin), "point": point},
                {"name": away_name, "price": _price(ac, margin), "point": point},
            ],
        })
    return books


def _inject_outlier(rng, books, market_key, outcome_name, boost):
    """Boost one book's price on one outcome to manufacture a real arb/+EV."""
    book = rng.choice(books)
    for market in book["markets"]:
        if market["key"] == market_key:
            for outcome in market["outcomes"]:
                if outcome["name"] == outcome_name:
                    outcome["price"] = round(outcome["price"] * (1 + boost), 3)
                    return True
    return False


def _gen_event(rng, sport, idx, now, region):
    teams = sport["teams"]
    home, away = rng.sample(teams, 2)
    offset_h = rng.uniform(3, 72)
    commence = now + timedelta(hours=offset_h)
    commence_iso = commence.strftime("%Y-%m-%dT%H:%M:%SZ")

    books = BOOKS_US if region == "us" else BOOKS_UK
    books = [(k, t) for k, t in books if k != "betfair"]  # exchange book handled separately

    p_home = rng.uniform(0.34, 0.66)
    p_away = 1 - p_home
    ev = _gen_h2h(rng, p_home, p_away, books,
                  three_way=sport.get("three_way", False), home=home, away=away)

    has_spreads = sport.get("spread_scale") and not sport.get("three_way") and sport.get("two_way") is not True
    has_totals = sport.get("total_mean") is not None and sport.get("two_way") is not True

    if has_spreads:
        margin_pts = (p_home - 0.5) * 2 * sport["spread_scale"]
        point = round(margin_pts * 2) / 2
        point = -point if point != 0 else -1.5
        cover = _clamp(0.5 + (p_home - 0.5) * 1.15)
        ev = _gen_spreads(rng, point, ev, cover, home, away)
    if has_totals:
        total_point = round(sport["total_mean"] + rng.gauss(0, sport["total_sigma"]) * 0.6) * 2 / 2
        over_i = _clamp(0.5 + (sport["total_mean"] - total_point) * 0.04 + rng.gauss(0, 0.01))
        ev = _gen_totals(rng, total_point, ev, over_i)

    # Manufacture realistic opportunities: a few real arbs, a few +EV-only edges
    roll = rng.random()
    if roll < 0.18:
        _inject_outlier(rng, ev, "h2h", "Away" if rng.random() < 0.5 else "Home", rng.uniform(0.07, 0.16))
    elif roll < 0.34:
        _inject_outlier(rng, ev, "h2h", "Away" if rng.random() < 0.5 else "Home", rng.uniform(0.03, 0.06))
    if has_totals and rng.random() < 0.10:
        _inject_outlier(rng, ev, "totals", rng.choice(["Over", "Under"]), rng.uniform(0.06, 0.13))
    if has_spreads and rng.random() < 0.08:
        _inject_outlier(rng, ev, "spreads", rng.choice(["Home", "Away"]), rng.uniform(0.06, 0.12))

    return {
        "id": _event_id([sport["key"], home, away, commence_iso]),
        "sport_key": sport["key"],
        "sport_title": sport["title"],
        "commence_time": commence_iso,
        "home_team": home,
        "away_team": away,
        "bookmakers": ev,
    }


def _gen_exchange_event(rng, now):
    """One soccer event with a Betfair-style h2h_lay market so the
    back/lay (matched-betting) tab has something to show."""
    sport = SPORTS[4]  # EPL
    home, away = rng.sample(sport["teams"], 2)
    commence = now + timedelta(hours=30)
    p_home = 0.52
    ev = _gen_h2h(rng, p_home, 1 - p_home, BOOKS_UK, three_way=True, home=home, away=away)
    # Betfair exchange market: lay prices ~2-3% below back prices
    back_prices = {}
    for book in ev:
        for market in book["markets"]:
            if market["key"] == "h2h":
                for outcome in market["outcomes"]:
                    back_prices.setdefault(outcome["name"], []).append(outcome["price"])
    lay_outcomes = []
    for name, prices in back_prices.items():
        back = sum(prices) / len(prices)
        lay_outcomes.append({"name": name, "price": round(back * rng.uniform(0.965, 0.985), 3)})
    ev.append({
        "key": "betfair", "title": "Betfair Exchange",
        "markets": [{"key": "h2h_lay", "outcomes": lay_outcomes}],
    })
    return {
        "id": _event_id(["epl_exchange", home, away, commence.isoformat()]),
        "sport_key": "soccer_epl",
        "sport_title": sport["title"],
        "commence_time": commence.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": home,
        "away_team": away,
        "bookmakers": ev,
    }


def _gen_outright(rng, sport, idx, now, region):
    outcomes = rng.sample(sport["teams"] + ["Dark Horse " + str(i) for i in range(1, 6)], sport["outcomes"])
    weights = [rng.uniform(0.4, 1.0) for _ in outcomes]
    total_w = sum(weights)
    base = [w / total_w for w in weights]
    books = BOOKS_US if region == "us" else BOOKS_UK
    bookmakers = []
    for bk_key, bk_title in books:
        margin = 1 + rng.uniform(0.03, 0.06)
        probs = [_clamp(p * rng.uniform(0.96, 1.05)) for p in base]
        probs = [p / sum(probs) for p in probs]
        bookmakers.append({
            "key": bk_key, "title": bk_title,
            "markets": [{"key": "outrights", "outcomes": [
                {"name": outcomes[i], "price": _price(probs[i], margin)} for i in range(len(outcomes))
            ]}],
        })
    # Manufacture one outright arbitrage: two books badly off on two
    # different outcomes so the combined best-price market sums < 100%.
    _inject_outlier(rng, bookmakers, "outrights", outcomes[3], rng.uniform(1.30, 1.45))
    _inject_outlier(rng, bookmakers, "outrights", outcomes[5], rng.uniform(1.18, 1.28))
    commence = now + timedelta(days=1)
    return {
        "id": _event_id([sport["key"], "outright", str(idx)]),
        "sport_key": sport["key"],
        "sport_title": sport["title"],
        "title": f"{sport['title']} — Outright Winner",
        "commence_time": commence.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": None,
        "away_team": None,
        "bookmakers": bookmakers,
    }


def generate_sample_data(region="us", now=None) -> dict:
    """Return {'sports': [...], 'odds': {sport_key: [events]}} in the same
    shape as a saved The Odds API response."""
    rng = random.Random(SEED)
    now = now or datetime.now(timezone.utc)

    sports_out = []
    odds = {}
    for sport in SPORTS:
        sports_out.append({
            "key": sport["key"], "group": sport["group"], "title": sport["title"],
            "description": f"{sport['title']} odds", "active": True,
            "has_outrights": bool(sport.get("outright")),
        })
        events = []
        for i in range(sport["events"]):
            if sport.get("outright"):
                events.append(_gen_outright(rng, sport, i, now, region))
            else:
                events.append(_gen_event(rng, sport, i, now, region))
        odds[sport["key"]] = events

    # Exchange demo event under soccer_epl
    odds["soccer_epl"].append(_gen_exchange_event(rng, now))

    return {"sports": sports_out, "odds": odds}


if __name__ == "__main__":
    import json
    data = generate_sample_data()
    print(f"{len(data['sports'])} sports, {sum(len(v) for v in data['odds'].values())} events")
    with open("/tmp/sample_preview.json", "w") as f:
        json.dump(data, f, indent=1)
    print("preview written to /tmp/sample_preview.json")
