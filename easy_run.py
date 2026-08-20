"""Easy launcher: `python easy_run.py` starts the modern web dashboard.

No Streamlit, no subprocess plumbing — it is just a thin wrapper around
``app.py`` with sensible defaults (US region, h2h+spreads+totals, 0%
cutoff, 5-minute refresh). Pass any app.py flag through:

    python easy_run.py --region uk --markets h2h --refresh 120
"""
from app import build_parser, config_from_args, run_dashboard


def main():
    parser = build_parser()
    parser.set_defaults(
        host="0.0.0.0", port=8000, region="us",
        markets="h2h,spreads,totals", cutoff=0.0, max_profit=20.0,
        min_ev=1.0, stake=100.0, refresh=300, lay_commission=0.02,
        max_sports=10,
    )
    args = parser.parse_args()
    config = config_from_args(args)
    run_dashboard(config)


if __name__ == "__main__":
    main()
