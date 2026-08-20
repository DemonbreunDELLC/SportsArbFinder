"""Application configuration for the SportsArbFinder.

A single plain Config object is threaded through the API client, the
arbitrage engine, the CLI and the web server so every component sees the
same settings.
"""
import os

from dotenv import load_dotenv

# Markets that The Odds API v4 supports and this engine can analyze.
SUPPORTED_MARKETS = ("h2h", "spreads", "totals", "outrights", "h2h_lay", "outrights_lay")
# Markets shown by default in the dashboard (cheap, reliable, high volume).
DEFAULT_MARKETS = ("h2h", "spreads", "totals")
DEFAULT_REGIONS = ("us", "uk", "eu", "au")


def load_env_api_key() -> str | None:
    """API key from ODDS_API_KEY, .env or .env.txt (in that order)."""
    load_dotenv()                      # standard .env
    load_dotenv(".env.txt")            # key shipped in this repo
    key = os.getenv("ODDS_API_KEY")
    return key.strip() if key and key.strip() else None


class Config:
    def __init__(
        self,
        region="us",
        markets=DEFAULT_MARKETS,
        cutoff=0.0,                # min profit margin (%) for an arbitrage to count
        max_profit=20.0,           # filter out "too good" margins (data errors)
        min_ev=1.0,                # min EV (%) for the +EV / value bet finder
        sports=None,               # None = every in-season sport (expensive); list = subset
        bookmakers=None,           # None = all books; list = restrict to these book keys
        api_key=None,
        interactive=False,
        save_file=None,
        offline_file=None,         # raw odds dump (sports+odds) or a previous results file
        stake=100.0,               # default stake used by calculators / profit display
        refresh_seconds=300,       # odds refresh interval (respects API credits!)
        lay_commission=0.02,       # exchange commission (2%) for back/lay markets
        max_sports=10,             # safety cap on how many sports get scanned
        verbose=True,
        serve=False,               # CLI flag: launch the web dashboard
        demo=False,                # force sample data even when an API key exists
    ):
        self.region = region
        self.markets = tuple(m for m in markets if m in SUPPORTED_MARKETS) or ("h2h",)
        self.cutoff = float(cutoff)
        self.max_profit = float(max_profit)
        self.min_ev = float(min_ev)
        self.sports = list(sports) if sports else None
        self.bookmakers = list(bookmakers) if bookmakers else None
        self.api_key = api_key or load_env_api_key()
        self.interactive = interactive
        self.save_file = save_file
        self.offline_file = offline_file
        self.stake = float(stake)
        self.refresh_seconds = max(15, int(refresh_seconds))
        self.lay_commission = float(lay_commission)
        self.max_sports = int(max_sports)
        self.verbose = verbose
        self.serve = serve
        self.demo = demo

    @property
    def is_offline(self):
        return bool(self.offline_file)

    def to_dict(self):
        return {
            "region": self.region,
            "markets": list(self.markets),
            "cutoff": self.cutoff,
            "max_profit": self.max_profit,
            "min_ev": self.min_ev,
            "sports": self.sports,
            "bookmakers": self.bookmakers,
            "stake": self.stake,
            "refresh_seconds": self.refresh_seconds,
            "lay_commission": self.lay_commission,
            "max_sports": self.max_sports,
            "source": "offline" if self.is_offline else "live",
        }

    def __repr__(self):
        return f"Config(region={self.region!r}, markets={self.markets!r}, cutoff={self.cutoff}, max_profit={self.max_profit}, min_ev={self.min_ev}, refresh={self.refresh_seconds}s)"
