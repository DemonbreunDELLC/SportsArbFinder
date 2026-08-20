"""Client for The Odds API v4 (https://the-odds-api.com).

Fixes over the original implementation:
- loads the API key from ``ODDS_API_KEY``, ``.env`` AND the committed
  ``.env.txt`` (the old code only loaded ``.env``, so the key in the repo
  was silently ignored and every request 401'd);
- transparently falls back to deterministic sample data when no key is
  configured or the network is unavailable, so the app always runs;
- caches per-sport responses and respects the configured refresh interval
  (crucial on the 500-credit/month free tier);
- tracks ``x-requests-remaining`` credits and stops scanning before the
  quota is exhausted;
- supports filtering by bookmaker keys and sports keys.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

import requests

from config import load_env_api_key
from sample_data import generate_sample_data

log = logging.getLogger("odds_api")

BASE_URL = "https://api.the-odds-api.com/v4"
MIN_CREDITS_SAFETY = 25  # stop scanning when fewer than this many credits remain


class OddsAPI:
    def __init__(self, config):
        self.config = config
        self.api_key = config.api_key or load_env_api_key()
        self.base_url = BASE_URL
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SportsArbFinder/2.0 (+educational)"})
        self.remaining_requests = None
        self.used_requests = None
        self.api_limit_reached = False
        self._cache = {}          # sport_key -> (fetched_at, payload)
        self._lock = threading.Lock()
        self.using_sample_data = False
        self.fallback_reason = None   # set when serving sample data instead of live
        self._offline_data = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_sports(self):
        if self.config.offline_file:
            return self._load_offline()["sports"]

        if self.config.demo or not self.api_key:
            self._enable_sample_fallback("no API key configured" if not self.api_key
                                         else "demo mode enabled")
            return generate_sample_data(self.config.region)["sports"]

        url = f"{self.base_url}/sports"
        try:
            response = self.session.get(url, params={"apiKey": self.api_key, "all": "false"}, timeout=20)
            response.raise_for_status()
            sports = response.json()
        except requests.RequestException as e:
            self._handle_error(e, "fetching sports list")
            self._enable_sample_fallback(f"live API unreachable ({type(e).__name__})")
            return generate_sample_data(self.config.region)["sports"]

        wanted = self.config.sports
        if wanted:
            wanted_set = set(wanted)
            sports = [s for s in sports if s["key"] in wanted_set]
        # Keep the scan cheap: cap the number of sports analyzed.
        sports = sports[: self.config.max_sports]
        return sports

    def get_odds(self, sport_key):
        """Return the latest odds events for a sport, cached for
        ``refresh_seconds``. Returns [] on quota/network failure."""
        if self.config.offline_file:
            return self._load_offline()["odds"].get(sport_key, [])

        if self.config.demo or not self.api_key or self.using_sample_data:
            self._enable_sample_fallback(self.fallback_reason or "no API key configured")
            return generate_sample_data(self.config.region)["odds"].get(sport_key, [])

        with self._lock:
            cached = self._cache.get(sport_key)
            if cached and time.time() - cached[0] < self.config.refresh_seconds:
                return cached[1]
            if self.api_limit_reached:
                return []
            if self._credits_remaining() is not None and self._credits_remaining() < MIN_CREDITS_SAFETY:
                log.warning("API credits nearly exhausted — using cached data only.")
                return cached[1] if cached else []

            url = f"{self.base_url}/sports/{sport_key}/odds"
            params = {
                "apiKey": self.api_key,
                "regions": self.config.region,
                "markets": ",".join(self.config.markets),
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            }
            if self.config.bookmakers:
                params["bookmakers"] = ",".join(self.config.bookmakers)
            try:
                response = self.session.get(url, params=params, timeout=25)
            except requests.RequestException as e:
                self._handle_error(e, f"fetching {sport_key} odds")
                return cached[1] if cached else []

            if response.status_code == 422:
                return []  # market/region combination not offered for this sport
            if response.status_code == 401:
                self._handle_error(response, f"fetching {sport_key} odds")
                return cached[1] if cached else []
            if response.status_code == 429:
                self.api_limit_reached = True
                self._handle_error(response, f"fetching {sport_key} odds")
                return cached[1] if cached else []
            try:
                response.raise_for_status()
            except requests.RequestException as e:
                self._handle_error(e, f"fetching {sport_key} odds")
                return cached[1] if cached else []

            self.remaining_requests = response.headers.get("x-requests-remaining")
            self.used_requests = response.headers.get("x-requests-used")
            data = response.json()
            self._cache[sport_key] = (time.time(), data)

            if self.config.save_file:
                self._save_sport(sport_key, data)
            return data

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _enable_sample_fallback(self, reason: str):
        self.using_sample_data = True
        if not self.fallback_reason:
            self.fallback_reason = reason
            log.warning("Falling back to sample data: %s", reason)

    def _load_offline(self):
        if self._offline_data is None:
            with open(self.config.offline_file, "r") as f:
                self._offline_data = json.load(f)
        return self._offline_data

    def _credits_remaining(self):
        try:
            return int(self.remaining_requests)
        except (TypeError, ValueError):
            return None

    def _handle_error(self, error, context):
        if isinstance(error, requests.exceptions.HTTPError) and error.response is not None:
            status = error.response.status_code
            if status == 401:
                log.error("Unauthorized (401) — check your ODDS_API_KEY.")
                print("✗ Unauthorized. Check your ODDS_API_KEY.")
                self.api_limit_reached = True
            elif status == 429:
                log.error("Rate limited (429) — API quota exhausted.")
                print("✗ API request limit reached (429). Waiting for the next cycle.")
                self.api_limit_reached = True
            else:
                log.error(f"HTTP {status} while {context}: {error}")
        else:
            log.warning(f"Network error while {context}: {error}")

    def _save_sport(self, sport_key, odds_data):
        path = self.config.save_file
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
            else:
                data = {"sports": [], "odds": {}}
            data.setdefault("odds", {})[sport_key] = odds_data
            with open(path, "w") as f:
                json.dump(data, f, indent=1)
        except (OSError, ValueError) as e:
            log.warning(f"Could not save response to {path}: {e}")
