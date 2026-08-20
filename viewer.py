"""Results viewer: `python viewer.py [results.json]`.

Serves the web dashboard pinned to a previously generated results file
(``arbitrage_results.json`` by default) instead of rescanning live odds.

    python viewer.py                      # view arbitrage_results.json
    python viewer.py my_scan.json         # view a specific results file
"""
import sys
from pathlib import Path

from app import build_parser, config_from_args, run_dashboard


def main():
    # known flags parse normally; the positional results-file path lands in
    # `unknown` and is handled below
    args, unknown = build_parser().parse_known_args()
    positional = [a for a in unknown if not a.startswith("-")]
    target = positional[0] if positional else "arbitrage_results.json"
    if not Path(target).exists():
        print(f"✗ Results file not found: {target}")
        print("  Run `python main.py` first to generate it.")
        sys.exit(1)
    args.offline = target
    args.demo = False
    config = config_from_args(args)
    run_dashboard(config, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
