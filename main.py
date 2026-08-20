"""Command-line interface for the SportsArbFinder engine.

Examples:
    python main.py                          # US region, h2h+spreads+totals, live API
    python main.py -r uk --markets h2h      # UK region, moneyline only
    python main.py -c 1 -m 15 --min-ev 2    # arbs >=1% (cap 15%), +EV bets >=2%
    python main.py --sports basketball_nba,baseball_mlb
    python main.py --serve                  # scan once, then open the web dashboard
    python main.py -o response_data.json    # analyze a saved API response offline
"""
import argparse
import json
import os
import sys

from arbitrage_finder import ArbitrageFinder
from config import Config, SUPPORTED_MARKETS

DEFAULT_MARKETS = "h2h,spreads,totals"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="Sports betting arbitrage & +EV finder (The Odds API).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-r", "--region", choices=["us", "uk", "eu", "au"], default="us",
                   help="Bookmaker region")
    p.add_argument("--markets", default=DEFAULT_MARKETS,
                   help=f"Comma-separated markets: {', '.join(SUPPORTED_MARKETS)}")
    p.add_argument("-c", "--cutoff", type=float, default=0.0,
                   help="Minimum arbitrage profit margin (%)")
    p.add_argument("-m", "--max-profit", type=float, default=20.0,
                   help="Ignore arbs above this margin (%) — filters data errors")
    p.add_argument("--min-ev", type=float, default=1.0,
                   help="Minimum EV (%) for the +EV / value bet list")
    p.add_argument("--sports", type=str, default=None,
                   help="Comma-separated sport keys to scan (default: all active)")
    p.add_argument("--bookmakers", type=str, default=None,
                   help="Comma-separated bookmaker keys to restrict to")
    p.add_argument("--api-key", type=str, default=None,
                   help="The Odds API key (overrides .env / ODDS_API_KEY)")
    p.add_argument("-s", "--save", type=str, default=None,
                   help="Save raw API responses to a JSON file")
    p.add_argument("-o", "--offline", type=str, default=None,
                   help="Analyze a saved response file instead of the live API")
    p.add_argument("--stake", type=float, default=100.0,
                   help="Default stake ($) used for stake-split calculations")
    p.add_argument("--refresh", type=int, default=300,
                   help="Odds cache lifetime (seconds) — free tier is 500 credits/month")
    p.add_argument("--lay-commission", type=float, default=0.02,
                   help="Exchange commission for back/lay markets (2%% = 0.02)")
    p.add_argument("-i", "--interactive", action="store_true",
                   help="Show per-opportunity stake details in the terminal")
    p.add_argument("--demo", action="store_true",
                   help="Use built-in sample data instead of the live API")
    p.add_argument("-q", "--quiet", action="store_true", help="Suppress console output")
    p.add_argument("--serve", action="store_true",
                   help="Launch the web dashboard after scanning")
    p.add_argument("--out", type=str, default="arbitrage_results.json",
                   help="Where to write the results JSON")
    p.add_argument("--check-key", action="store_true",
                   help="Just test whether your ODDS_API_KEY works, then exit")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.check_key:
        from odds_api import OddsAPI
        from config import Config as _C
        probe = OddsAPI(_C(api_key=args.api_key))
        ok, msg = probe.check_api_key()
        print("✓" if ok else "✗", msg)
        return 0 if ok else 1

    config = Config(
        region=args.region,
        markets=[m.strip() for m in args.markets.split(",") if m.strip()],
        cutoff=args.cutoff,
        max_profit=args.max_profit,
        min_ev=args.min_ev,
        sports=[s.strip() for s in args.sports.split(",")] if args.sports else None,
        bookmakers=[b.strip() for b in args.bookmakers.split(",")] if args.bookmakers else None,
        api_key=args.api_key,
        interactive=args.interactive,
        save_file=args.save,
        offline_file=args.offline,
        stake=args.stake,
        refresh_seconds=args.refresh,
        lay_commission=args.lay_commission,
        verbose=not args.quiet,
        serve=args.serve,
        demo=args.demo,
    )

    finder = ArbitrageFinder(config)
    results = finder.find_arbitrage()

    out_path = args.out
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Results written to {out_path}")

    _print_terminal_summary(results, args.interactive)

    if args.serve:
        from app import run_dashboard
        run_dashboard(config=config, results=results)
    return results


def _print_terminal_summary(results, interactive=False):
    summary = results.get("summary", {})
    print("\n" + "=" * 62)
    print(f"  {summary.get('arbitrage_opportunities', 0)} arbitrage opportunities "
          f"| {summary.get('value_bets', 0)} +EV bets "
          f"| {summary.get('events_analyzed', 0)} events")
    print("=" * 62)

    arbs = results.get("arbitrage_opportunities", [])
    if not arbs:
        print("  No arbitrage opportunities met the cutoff.")
    for i, arb in enumerate(arbs[:25], 1):
        books = ", ".join(dict.fromkeys(o["bookmaker"] for o in arb["outcomes"]))
        starts = f"in {arb['starts_in_minutes']}m" if arb.get("starts_in_minutes") is not None else "—"
        print(f"  {i:>2}. {arb['event'][:44]:<44} {arb['profit_margin']:>5.2f}%  "
              f"[{arb['market']}] {books} ({starts})")
        if interactive:
            for o in arb["outcomes"]:
                print(f"        {o['name'][:28]:<28} ${o.get('stake', 0):>8.2f} @ "
                      f"{o['odds']:<6} {o['bookmaker']}")

    evs = results.get("value_bets", [])
    if evs:
        print(f"\n  Top +EV bets (showing {min(len(evs), 10)} of {len(evs)}):")
        for v in evs[:10]:
            print(f"    {v['ev_percent']:>5.2f}%  {v['outcome'][:24]:<24} @ {v['odds']:<6} "
                  f"{v['bookmaker']} — {v['event'][:40]}")

    usage = results.get("api_usage")
    if usage:
        print(f"\n  API credits remaining: {usage.get('remaining_requests')} "
              f"(used this session: {usage.get('used_requests')})")


if __name__ == "__main__":
    sys.exit(main())
