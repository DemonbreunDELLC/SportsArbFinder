"""Betting math: odds conversion, devigging, arbitrage and +EV calculations.

Everything here is pure functions with no I/O so it can be unit-tested,
used from the CLI and (via a small API bridge) from the web dashboard.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple


# --------------------------------------------------------------------------
# Odds formatting / conversion
# --------------------------------------------------------------------------

def decimal_to_american(decimal: float) -> str:
    if decimal is None or decimal <= 0:
        return "—"
    if decimal >= 2.0:
        return f"+{round((decimal - 1) * 100)}"
    return f"{round(-100 / (decimal - 1))}"


def american_to_decimal(american: float) -> float:
    if american > 0:
        return 1 + american / 100
    return 1 + 100 / abs(american)


def decimal_to_fractional(decimal: float) -> str:
    if decimal is None or decimal <= 0:
        return "—"
    # Find a clean fraction within a small tolerance (e.g. 1.909 -> 10/11)
    best = None
    for den in range(1, 101):
        num = round((decimal - 1) * den)
        if num <= 0:
            continue
        if abs((num / den) + 1 - decimal) < 0.002:
            best = (num, den)
            break
    if best is None:
        return f"{decimal - 1:.2f}/1"
    g = _gcd(best[0], best[1])
    return f"{best[0] // g}/{best[1] // g}"


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def implied_probability(decimal: float) -> float:
    """Implied probability from decimal odds (0..1)."""
    if decimal is None or decimal <= 1.0:
        return 0.0
    return 1.0 / decimal


# --------------------------------------------------------------------------
# Devigging (fair probabilities)
# --------------------------------------------------------------------------

def devig_proportional(implied: Sequence[float]) -> List[float]:
    """Remove the bookmaker margin by scaling implied probs to sum to 1."""
    total = sum(implied)
    if total <= 0:
        return [0.0] * len(implied)
    return [p / total for p in implied]


def fair_probabilities(decimal_odds: Sequence[float]) -> List[float]:
    """Fair (no-vig) probabilities from a set of decimal odds on one market."""
    return devig_proportional([implied_probability(d) for d in decimal_odds])


def consensus_fair_probabilities(
    outcome_prices: Dict[str, List[float]]
) -> Dict[str, float]:
    """Fair probabilities using the multi-book consensus.

    For each outcome we average the implied probability across every
    bookmaker that prices it, then devig the averaged line so the market
    sums to 1. This is the standard "no-vig consensus" method used by
    +EV tools (OddsJam uses a sharp-anchored model; consensus is the
    closest approximation available from a single odds feed).
    """
    avg_implied: Dict[str, float] = {}
    for outcome, prices in outcome_prices.items():
        valid = [p for p in prices if p and p > 1.0]
        if not valid:
            avg_implied[outcome] = 0.0
        else:
            avg_implied[outcome] = sum(1.0 / p for p in valid) / len(valid)
    keys = list(avg_implied.keys())
    if not keys:
        return {}
    fair = devig_proportional([avg_implied[k] for k in keys])
    return dict(zip(keys, fair))


# --------------------------------------------------------------------------
# Arbitrage
# --------------------------------------------------------------------------

def arbitrage_margin(best_decimal_odds: Sequence[float]) -> Optional[float]:
    """Profit margin (as a fraction, e.g. 0.02 = 2%) if implied sum < 1.

    Returns None when no arbitrage exists.
    """
    valid = [d for d in best_decimal_odds if d and d > 1.0]
    if len(valid) < 2:
        return None
    total_implied = sum(1.0 / d for d in valid)
    if total_implied >= 1.0:
        return None
    return 1.0 / total_implied - 1.0


def arbitrage_stakes(
    decimal_odds: Sequence[float], total_stake: float
) -> Tuple[List[float], float]:
    """Optimal stake per outcome so every outcome pays the same.

    Returns (stakes, guaranteed_return). Stake for outcome i is
    total_stake * (1/odds_i) / sum(1/odds). If the market isn't an
    arbitrage the "guaranteed return" will be <= total_stake.
    """
    inv = [1.0 / d for d in decimal_odds]
    s = sum(inv)
    if s <= 0:
        return [0.0] * len(decimal_odds), 0.0
    stakes = [total_stake * (p / s) for p in inv]
    return stakes, total_stake / s


def distinct_bookmakers(entries: Sequence[Dict]) -> bool:
    """True when the entries reference at least two different bookmakers."""
    books = {e.get("bookmaker_key") or e.get("bookmaker") for e in entries if e}
    return len(books) >= 2


# --------------------------------------------------------------------------
# Back / lay (exchange) arbitrage
# --------------------------------------------------------------------------

def lay_arbitrage_margin(back_odds: float, lay_odds: float, commission: float) -> Optional[float]:
    """Guaranteed profit margin for backing at `back_odds` and laying the
    same outcome at `lay_odds` on an exchange charging `commission`.

    Balanced stakes: lay_stake = back_stake * back_odds / (lay_odds - commission).
    Profit per $1 of back stake:
        P = back_odds * (1 - commission) / (lay_odds - commission) - 1
    An arbitrage exists when P > 0, i.e. back_odds > lay_odds - commission.
    """
    if lay_odds <= commission or back_odds <= 1.0:
        return None
    profit = back_odds * (1 - commission) / (lay_odds - commission) - 1.0
    return profit if profit > 0 else None


def lay_arbitrage_stakes(back_odds: float, lay_odds: float, commission: float, back_stake: float):
    """Return (lay_stake, guaranteed_profit) for a back/lay arbitrage."""
    lay_stake = back_stake * back_odds / (lay_odds - commission)
    profit = back_stake * (back_odds * (1 - commission) / (lay_odds - commission) - 1.0)
    return lay_stake, profit


# --------------------------------------------------------------------------
# Expected value
# --------------------------------------------------------------------------

def expected_value(fair_probability: float, decimal_odds: float) -> float:
    """EV as a fraction (0.05 = 5%). Positive means the price beats fair value."""
    if decimal_odds <= 1.0:
        return 0.0
    return fair_probability * decimal_odds - 1.0


def hold_percentage(best_decimal_odds: Sequence[float]) -> Optional[float]:
    """Bookmaker hold implied by the best prices on a market (fraction)."""
    valid = [d for d in best_decimal_odds if d and d > 1.0]
    if len(valid) < 2:
        return None
    return sum(1.0 / d for d in valid) - 1.0


# --------------------------------------------------------------------------
# Odds normalization helpers used by the engine
# --------------------------------------------------------------------------

def format_american(decimal: float) -> str:
    return decimal_to_american(decimal)


def format_fractional(decimal: float) -> str:
    return decimal_to_fractional(decimal)
