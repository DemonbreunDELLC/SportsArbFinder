"""Real-time web dashboard for the SportsArbFinder engine.

A FastAPI + WebSocket server in the spirit of modern odds platforms
(OddsJam / ProfitDuel):

* a background scanner refreshes odds every ``refresh_seconds`` and
  pushes results to every connected browser over WebSocket;
* tabs for Arbitrage, +EV Bets, Odds Screen and Calculators;
* live source badges (LIVE / SAMPLE / OFFLINE) with fallback reasons;
* settings are editable from the UI and hot-reload the scanner.

Run:
    python app.py [--port 8000] [--region us] [--markets h2h,spreads,totals]
                  [--demo] [--offline response_data.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from arbitrage_finder import ArbitrageFinder
from config import Config, SUPPORTED_MARKETS

WEB_DIR = Path(__file__).parent / "web"
RESULTS_FILE = Path(__file__).parent / "arbitrage_results.json"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SportsArbFinder web dashboard")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("-r", "--region", choices=["us", "uk", "eu", "au"], default="us")
    p.add_argument("--markets", default="h2h,spreads,totals")
    p.add_argument("-c", "--cutoff", type=float, default=0.0)
    p.add_argument("-m", "--max-profit", type=float, default=20.0)
    p.add_argument("--min-ev", type=float, default=1.0)
    p.add_argument("--sports", type=str, default=None)
    p.add_argument("--bookmakers", type=str, default=None)
    p.add_argument("--api-key", type=str, default=None)
    p.add_argument("--offline", type=str, default=None)
    p.add_argument("--demo", action="store_true")
    p.add_argument("--stake", type=float, default=100.0)
    p.add_argument("--refresh", type=int, default=300)
    p.add_argument("--lay-commission", type=float, default=0.02)
    p.add_argument("--max-sports", type=int, default=10)
    return p


def config_from_args(args) -> Config:
    return Config(
        region=args.region,
        markets=[m.strip() for m in args.markets.split(",") if m.strip()],
        cutoff=args.cutoff,
        max_profit=args.max_profit,
        min_ev=args.min_ev,
        sports=[s.strip() for s in args.sports.split(",")] if args.sports else None,
        bookmakers=[b.strip() for b in args.bookmakers.split(",")] if args.bookmakers else None,
        api_key=args.api_key,
        offline_file=args.offline,
        stake=args.stake,
        refresh_seconds=args.refresh,
        lay_commission=args.lay_commission,
        max_sports=args.max_sports,
        verbose=False,
        demo=args.demo,
    )


class DashboardState:
    """Thread-safe shared state between the scanner loop and the web layer."""

    def __init__(self, config: Config, initial_results=None, static=False):
        self.config = config
        self.results = initial_results
        self.static = static          # True = serve saved results, never rescan
        self.last_scan = None
        self.scanning = False
        self.error = None
        self._stop = False
        self._force = False
        self._lock = threading.Lock()
        self.clients: set[WebSocket] = set()

    # -- scanner ---------------------------------------------------------

    def scan_now(self):
        with self._lock:
            self.scanning = True
        try:
            finder = ArbitrageFinder(self.config)
            self.results = finder.find_arbitrage()
            try:
                with open(RESULTS_FILE, "w") as f:
                    json.dump(self.results, f, indent=2)
            except OSError:
                pass
            self.error = None
            self.last_scan = time.time()
        except Exception as exc:  # noqa: BLE001 - keep the server alive
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                self.scanning = False

    def run_loop(self):
        while not self._stop:
            if self.static:
                time.sleep(1.0)
                continue
            self.scan_now()
            interval = self.config.refresh_seconds
            deadline = time.time() + interval
            while time.time() < deadline:
                if self._stop:
                    return
                if self._force:
                    self._force = False
                    break
                time.sleep(0.25)

    def stop(self):
        self._stop = True

    def request_rescan(self):
        self._force = True

    # -- settings --------------------------------------------------------

    def apply_settings(self, s: dict) -> dict:
        cfg = self.config
        markets = [m for m in s.get("markets", cfg.markets) if m in SUPPORTED_MARKETS]
        sports = s["sports"] if "sports" in s else cfg.sports
        bookmakers = s["bookmakers"] if "bookmakers" in s else cfg.bookmakers
        new_config = Config(
            region=s.get("region", cfg.region) if s.get("region") in ("us", "uk", "eu", "au") else cfg.region,
            markets=markets or ["h2h"],
            cutoff=float(s.get("cutoff", cfg.cutoff)),
            max_profit=float(s.get("max_profit", cfg.max_profit)),
            min_ev=float(s.get("min_ev", cfg.min_ev)),
            sports=sports or None,
            bookmakers=bookmakers or None,
            api_key=cfg.api_key,
            offline_file=cfg.offline_file,
            stake=float(s.get("stake", cfg.stake)),
            refresh_seconds=int(s.get("refresh_seconds", cfg.refresh_seconds)),
            lay_commission=float(s.get("lay_commission", cfg.lay_commission)),
            verbose=False,
            demo=cfg.demo,
        )
        self.config = new_config
        self.request_rescan()
        return self.config.to_dict()

    # -- websocket -------------------------------------------------------

    def meta(self) -> dict:
        return {
            "last_scan": self.last_scan,
            "scanning": self.scanning,
            "static": self.static,
            "error": self.error,
            "next_scan_in": max(0, int(self.config.refresh_seconds - (time.time() - (self.last_scan or 0)))),
        }

    def broadcast(self, message: dict):
        dead = []
        for ws in self.clients:
            try:
                asyncio.run_coroutine_threadsafe(ws.send_json(message), _loop).result(timeout=2)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


_loop: asyncio.AbstractEventLoop | None = None


def load_results_file(path: str):
    """If the offline file is a previous *results* file, load it directly."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if "arbitrage_opportunities" in data else None
    except (OSError, ValueError):
        return None


def create_app(config: Config, initial_results=None) -> FastAPI:
    static = False
    if config.offline_file and initial_results is None:
        saved = load_results_file(config.offline_file)
        if saved is not None:
            initial_results = saved
            static = True
    state = DashboardState(config, initial_results, static=static)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global _loop
        _loop = asyncio.get_running_loop()
        t = threading.Thread(target=state.run_loop, daemon=True, name="scanner")
        t.start()
        yield
        state.stop()

    app = FastAPI(title="SportsArbFinder", lifespan=lifespan)

    @app.get("/api/state")
    def api_state():
        return {"meta": state.meta(), "results": state.results}

    @app.get("/api/settings")
    def api_get_settings():
        return {
            "settings": state.config.to_dict(),
            "has_api_key": bool(state.config.api_key),
        }

    @app.post("/api/settings")
    async def api_set_settings(request: Request):
        body = await request.json()
        try:
            settings = state.apply_settings(body)
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        state.broadcast({"type": "settings", "settings": settings})
        return {"settings": settings}

    @app.post("/api/scan")
    async def api_scan():
        state.request_rescan()
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        state.clients.add(ws)
        try:
            await ws.send_json({"type": "state", "meta": state.meta(), "results": state.results})
            while True:
                msg = await ws.receive_text()
                if msg == '{"type":"scan"}' or '"scan"' in msg:
                    state.request_rescan()
        except WebSocketDisconnect:
            pass
        finally:
            state.clients.discard(ws)

    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app


def run_dashboard(config: Config, results=None, host="0.0.0.0", port=8000):
    import uvicorn

    app = create_app(config, results)
    print(f"\n⚡ SportsArbFinder dashboard: http://{host}:{port}")
    print(f"   Data source: {config.to_dict()['source']} "
          f"| region: {config.region} | markets: {','.join(config.markets)}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = config_from_args(args)
    run_dashboard(config, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
