"""Indicatori tecnici (pandas puro, nessuna dipendenza esterna)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def add_intraday(df: pd.DataFrame, breakout_bars: int, atr_n: int) -> pd.DataFrame:
    """Aggiunge a un DataFrame di barre 15 min le colonne usate dalla strategia."""
    df = df.copy()
    df["prior_high"] = df["high"].shift(1).rolling(breakout_bars, min_periods=breakout_bars).max()
    df["rsi"] = rsi(df["close"], 14)
    df["atr"] = atr(df, atr_n)
    vol_avg = df["volume"].shift(1).rolling(20, min_periods=10).mean()
    df["vol_ratio"] = df["volume"] / vol_avg.replace(0, np.nan)
    return df


def add_daily(df: pd.DataFrame, fast: int, slow: int, regime: int, crypto: bool) -> pd.DataFrame:
    """Colonne giornaliere. 'end_time' = quando la giornata è chiusa: solo da lì in poi
    la riga può essere usata (niente sbirciate nel futuro)."""
    from .common import ET  # import locale per evitare cicli
    df = df.copy()
    df["ema_fast"] = ema(df["close"], fast)
    df["ema_slow"] = ema(df["close"], slow)
    df["ema_regime"] = ema(df["close"], regime)
    df["ret20"] = df["close"] / df["close"].shift(20) - 1
    idx = pd.DatetimeIndex(df.index)
    if crypto:
        df["end_time"] = idx + pd.Timedelta(days=1)
    else:
        d = idx.tz_convert(ET).normalize() + pd.Timedelta(hours=16)
        df["end_time"] = d.tz_convert("UTC")
    return df


def last_closed(daily: pd.DataFrame | None, now) -> pd.Series | None:
    """Ultima giornata chiusa prima di 'now'."""
    if daily is None or daily.empty:
        return None
    i = daily["end_time"].searchsorted(pd.Timestamp(now), side="right") - 1
    return None if i < 0 else daily.iloc[i]
