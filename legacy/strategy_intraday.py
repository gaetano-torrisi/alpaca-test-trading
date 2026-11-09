"""Regole della strategia. Usate IDENTICHE dal bot reale e dal backtest."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import pandas as pd


@dataclass
class Candidate:
    symbol: str
    cls: str
    price: float
    stop: float
    target: float
    atr: float
    score: float
    reason: str


def regime_on(daily_row: pd.Series | None) -> bool:
    """Mercato 'risk-on' se il benchmark ha chiuso sopra la sua EMA lunga."""
    if daily_row is None or pd.isna(daily_row.get("ema_regime")):
        return False
    return bool(daily_row["close"] > daily_row["ema_regime"])


def class_allowed(cls: str, stock_on: bool, crypto_on: bool) -> bool:
    if cls == "crypto":
        return crypto_on
    if cls == "inverse":
        return not stock_on
    return stock_on


def evaluate_entry(symbol: str, cls: str, bar: pd.Series, daily_row: pd.Series | None,
                   news: tuple[float, int], stock_on: bool, crypto_on: bool,
                   cfg: dict) -> Candidate | None:
    e, x = cfg["entry"], cfg["exit"]
    if not class_allowed(cls, stock_on, crypto_on) or daily_row is None:
        return None
    needed = [bar.get("prior_high"), bar.get("rsi"), bar.get("atr"), bar.get("vol_ratio"),
              daily_row.get("ema_fast"), daily_row.get("ema_slow")]
    if any(v is None or pd.isna(v) for v in needed):
        return None
    price = float(bar["close"])
    # 1) tendenza giornaliera al rialzo
    if not (daily_row["close"] > daily_row["ema_fast"] > daily_row["ema_slow"]):
        return None
    # 2) rottura del massimo recente sulle barre da 15 minuti
    if price <= bar["prior_high"]:
        return None
    # 3) momentum non ancora esaurito
    if not (e["rsi_min"] <= bar["rsi"] <= e["rsi_max"]):
        return None
    # 4) volume sopra la media
    if bar["vol_ratio"] < e["volume_ratio_min"]:
        return None
    # 5) notizie non negative
    news_score, n_news = news
    if n_news > 0 and news_score < e["news_min_score"]:
        return None

    dist = x["stop_atr"] * float(bar["atr"])
    dist = min(max(dist, x["min_stop_pct"] * price), x["max_stop_pct"] * price)
    stop = price - dist
    target = price + dist * x["target_atr"] / x["stop_atr"]
    ret20 = 0.0 if pd.isna(daily_row.get("ret20")) else float(daily_row["ret20"])
    score = ret20 + 0.05 * min(float(bar["vol_ratio"]), 4.0) + 0.10 * news_score
    reason = (f"breakout {bar['prior_high']:.2f}, RSI {bar['rsi']:.0f}, vol x{bar['vol_ratio']:.1f}, "
              f"trend20g {ret20:+.1%}, news {news_score:+.2f} ({n_news})")
    return Candidate(symbol, cls, price, stop, target, float(bar["atr"]), score, reason)


def position_size(c: Candidate, equity: float, exposure: float, cfg: dict) -> float:
    r = cfg["risk"]
    factor = {"crypto": r["crypto_risk_factor"], "leveraged_long": r["leveraged_risk_factor"],
              "inverse": r["leveraged_risk_factor"]}.get(c.cls, 1.0)
    risk_usd = equity * r["risk_per_trade"] * factor
    qty = risk_usd / max(c.price - c.stop, 1e-9)
    max_value = min(r["max_position_pct"] * equity, r["max_gross_exposure"] * equity - exposure)
    qty = min(qty, max(max_value, 0) / c.price)
    if c.cls == "crypto":
        qty = math.floor(qty * 1e6) / 1e6
    else:
        qty = math.floor(qty)
    return qty if qty * c.price >= 100 else 0


def manage_position(pos: dict, bar: pd.Series | None, daily_row: pd.Series | None,
                    now: datetime, cfg: dict) -> tuple[str | None, float | None]:
    """Decide se chiudere una posizione o alzare lo stop.

    pos: {'entry', 'stop', 'atr', 'entry_time' (datetime)}
    Restituisce (motivo_chiusura | None, nuovo_stop | None).
    """
    x = cfg["exit"]
    if (now - pos["entry_time"]).total_seconds() >= x["max_hold_days"] * 86400:
        return "tempo massimo", None
    if (x.get("exit_on_daily_trend_break") and daily_row is not None
            and not pd.isna(daily_row.get("ema_fast"))
            and daily_row["end_time"] > pos["entry_time"]
            and daily_row["close"] < daily_row["ema_fast"]):
        return "tendenza giornaliera rotta", None
    if bar is not None and pos["stop"] < pos["entry"]:
        if bar["close"] >= pos["entry"] + x["breakeven_atr"] * pos["atr"]:
            return None, pos["entry"]
    return None, None
