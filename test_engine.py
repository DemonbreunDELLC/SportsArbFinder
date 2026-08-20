"""Lightweight, dependency-free tests for the engine and calculators.

Run with:  .venv/bin/python test_engine.py
"""
import json
import sys
import tempfile
import os

from config import Config
from arbitrage_finder import ArbitrageFinder
from calculators import (
    arbitrage_margin,
    arbitrage_stakes,
    decimal_to_american,
    fair_probabilities,
    lay_arbitrage_margin,
    lay_arbitrage_stakes,
    consensus_fair_probabilities,
    expected_value,
)

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def test_calculators():
    print("calculators")
    check("american +110 -> 2.10", decimal_to_american(2.10) == "+110")
    check("american -110 -> 1.909", decimal_to_american(1.909) == "-110")
    check("american +300", decimal_to_american(4.0) == "+300")
    check("no arb when implied >= 1", arbitrage_margin([2.0, 2.0]) is None)
    check("arb detected", abs(arbitrage_margin([2.1, 2.1]) - 0.05) < 1e-9)
    stakes, ret = arbitrage_stakes([2.1, 2.1], 100)
    check("balanced stakes", abs(stakes[0] - 50) < 1e-9 and abs(ret - 105) < 1e-9)
    fair = fair_probabilities([2.0, 2.0])
    check("devig 50/50", abs(fair[0] - 0.5) < 1e-9)
    fair = fair_probabilities([1.5, 3.0])
    check("devig 2:1", abs(fair[0] - 2 / 3) < 1e-9)
    cf = consensus_fair_probabilities({"A": [2.0, 2.2], "B": [2.2, 2.4]})
    check("consensus devig sums to 1", abs(sum(cf.values()) - 1.0) < 1e-9)
    check("EV positive", expected_value(0.6, 1.8) > 0)
    m = lay_arbitrage_margin(2.0, 1.95, 0.02)
    check("lay arb margin", m is not None and m > 0)
    ls, profit = lay_arbitrage_stakes(2.0, 1.95, 0.02, 100)
    check("lay arb profit > 0", profit > 0 and ls > 0)
    check("no lay arb when lay too high", lay_arbitrage_margin(1.9, 2.1, 0.02) is None)


def test_engine_sample():
    print("engine on sample data")
    cfg = Config(
        region="us",
        markets=["h2h", "spreads", "totals", "outrights", "h2h_lay"],
        cutoff=0.0, max_profit=20.0, min_ev=1.0,
        demo=True, verbose=False,
    )
    r = ArbitrageFinder(cfg).find_arbitrage()
    arbs = r["arbitrage_opportunities"]
    evs = r["value_bets"]
    check("arbs found", len(arbs) > 0, f"got {len(arbs)}")
    check("value bets found", len(evs) > 0, f"got {len(evs)}")
    check("summary counts match", r["summary"]["arbitrage_opportunities"] == len(arbs))
    check("source is sample-data", r["source"] == "sample-data")

    bad = [a for a in arbs if not (cfg.cutoff <= a["profit_margin"] <= cfg.max_profit)]
    check("no arbs outside cutoff", not bad)

    same_book = [a for a in arbs if len({o["bookmaker_key"] for o in a["outcomes"]}) < 2]
    check("every arb uses >=2 bookmakers", not same_book)

    # back/lay arbs use a different stake convention (lay stake != back stake)
    bad_stakes = [a for a in arbs if not a["market"].endswith("_lay")
                  and abs(sum(o["stake"] for o in a["outcomes"]) - cfg.stake) > 0.5]
    check("stakes sum to configured stake", not bad_stakes, f"{len(bad_stakes)} off")

    for a in arbs:
        rets = [o["return"] for o in a["outcomes"] if o.get("return") is not None]
        if rets:
            spread = max(rets) - min(rets)
            assert spread < 0.01, f"unbalanced returns {a['id']}: {rets}"
    check("returns balanced across outcomes", True)

    check("events carry commence time", all(a.get("commence_time") for a in arbs))
    check("starts_in_minutes present", all(a.get("starts_in_minutes") is not None for a in arbs))

    markets = {a["market"] for a in arbs}
    check("lay markets analyzed", "h2h_lay" in markets, str(markets))
    check("outrights analyzed", "outrights" in markets, str(markets))

    bad_ev = [v for v in evs if v["fair_prob"] <= 0 or v["fair_prob"] >= 1]
    check("value bets have sane fair prob", not bad_ev)
    check("value bets sorted by EV", all(
        evs[i]["ev_percent"] >= evs[i + 1]["ev_percent"] for i in range(len(evs) - 1)))


def test_offline_file():
    print("offline file mode")
    from sample_data import generate_sample_data
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w") as f:
            json.dump(generate_sample_data("us"), f)
        cfg = Config(offline_file=path, verbose=False)
        r = ArbitrageFinder(cfg).find_arbitrage()
        check("offline source", r["source"] == "offline-file")
        check("offline arbs found", len(r["arbitrage_opportunities"]) > 0)
    finally:
        os.unlink(path)


def main():
    test_calculators()
    test_engine_sample()
    test_offline_file()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
