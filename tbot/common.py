"""Funzioni comuni: configurazione, simboli, orari di mercato."""
from __future__ import annotations

import os
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def load_config(path: str | Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def api_keys() -> tuple[str, str]:
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        raise SystemExit("Mancano ALPACA_API_KEY / ALPACA_SECRET_KEY (vanno nei Secrets di GitHub).")
    return key, secret


# ---------------------------------------------------------------- simboli
def is_crypto(symbol: str) -> bool:
    """Nel bot le cripto sono sempre nel formato 'BTC/USD' (le posizioni vengono normalizzate)."""
    return "/" in symbol


def to_pair(symbol: str) -> str:
    """'BTCUSD' (formato posizioni) -> 'BTC/USD' (formato dati)."""
    if "/" in symbol:
        return symbol
    if symbol.endswith("USD"):
        return symbol[:-3] + "/USD"
    return symbol


def universe(cfg: dict) -> dict[str, list[str]]:
    u = cfg["universe"]
    return {
        "stocks": list(dict.fromkeys(u["stocks"] + u["index_etfs"])),
        "leveraged_long": list(u["leveraged_long"]),
        "inverse": list(u["inverse"]),
        "crypto": list(u["crypto"]) if cfg.get("crypto_enabled", True) else [],
    }


def all_stock_symbols(cfg: dict) -> list[str]:
    u = universe(cfg)
    return list(dict.fromkeys(u["stocks"] + u["leveraged_long"] + u["inverse"]))


def symbol_class(symbol: str, cfg: dict) -> str:
    u = universe(cfg)
    if is_crypto(symbol):
        return "crypto"
    if symbol in u["inverse"]:
        return "inverse"
    if symbol in u["leveraged_long"]:
        return "leveraged_long"
    return "stock"


# ------------------------------------------------------------------ orari
REGULAR_OPEN, REGULAR_CLOSE = time(9, 30), time(16, 0)


def stock_session(now_utc: datetime, trading_day: bool) -> str:
    """'regular' | 'pre' | 'post' | 'overnight' | 'closed' (ora di New York)."""
    t = now_utc.astimezone(ET)
    wd, hm = t.weekday(), t.time()
    if wd == 5 or (wd == 4 and hm >= time(20, 0)) or (wd == 6 and hm < time(20, 0)):
        return "closed"
    if not trading_day and time(4, 0) <= hm < time(20, 0):
        return "closed"
    if REGULAR_OPEN <= hm < REGULAR_CLOSE:
        return "regular"
    if time(4, 0) <= hm < REGULAR_OPEN:
        return "pre"
    if REGULAR_CLOSE <= hm < time(20, 0):
        return "post"
    return "overnight"


def is_rth(ts: datetime) -> bool:
    """La barra (timestamp di inizio) cade nella seduta regolare?"""
    t = ts.astimezone(ET).time()
    return REGULAR_OPEN <= t < REGULAR_CLOSE
