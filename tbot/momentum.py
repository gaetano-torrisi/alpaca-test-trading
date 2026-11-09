"""Regole della strategia MOMENTUM GIORNALIERO. Usate identiche dal bot reale e dal backtest.

In parole semplici:
 1. semaforo: VERDE se l'S&P 500 (SPY) chiude sopra la sua media a 200 giorni;
 2. classifica: forza = media dei rendimenti a 3 e 6 mesi, esclusa l'ultima settimana;
 3. si tengono i primi N titoli idonei (sopra la media a 50 giorni, forza positiva);
    un titolo già in portafoglio resta finché è nei primi `hold_buffer`;
 4. con semaforo ROSSO sono idonei solo i titoli difensivi (TLT, IEF, GLD);
    gli ETF a leva solo con semaforo VERDE;
 5. ogni posizione ha uno stop = massima chiusura dall'acquisto - 3 ATR, che non scende mai.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import ET


# ------------------------------------------------------------- universo
def symbol_classes(cfg: dict) -> dict[str, str]:
    u, out = cfg["universe"], {}
    for cls in ("stocks", "etf", "defensive", "leveraged"):
        for s in u.get(cls, []):
            out.setdefault(s, cls)
    for name, lst in u.items():  # elenchi aggiuntivi (es. tech2016): sono azioni
        for s in lst:
            out.setdefault(s, "stocks")
    out.setdefault(cfg["regime"]["benchmark"], "etf")
    return out


def active_symbols(cfg: dict) -> list[str]:
    act = cfg["universo_attivo"]
    if act == ["benchmark_only"]:
        return [cfg["regime"]["benchmark"]]
    syms = []
    for cls in act:
        syms += cfg["universe"].get(cls, [])
    return list(dict.fromkeys(syms))


def all_symbols(cfg: dict) -> list[str]:
    syms = [s for lst in cfg["universe"].values() for s in lst]
    return list(dict.fromkeys(syms + [cfg["regime"]["benchmark"], "SPY", "QQQ"]))


# ------------------------------------------------------------ indicatori
def to_panel(daily: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Da {simbolo: barre giornaliere} a tabelle date x simboli (open, high, low, close)."""
    frames = {}
    for s, df in daily.items():
        d = df.copy()
        d.index = pd.DatetimeIndex(d.index).tz_convert(ET).normalize().tz_localize(None)
        frames[s] = d[~d.index.duplicated(keep="last")]
    return {f: pd.DataFrame({s: d[f] for s, d in frames.items()}).sort_index() for f in ("open", "high", "low", "close")}


def indicators(panel: dict, cfg: dict) -> dict:
    c, h, lo = panel["close"], panel["high"], panel["low"]
    rk, st, rg = cfg["ranking"], cfg["stop"], cfg["regime"]
    pc = c.shift(1)
    tr = np.maximum(h - lo, np.maximum((h - pc).abs(), (lo - pc).abs()))
    atr = tr.rolling(st["atr_days"], min_periods=st["atr_days"]).mean()
    score = sum(c.shift(rk["skip_days"]) / c.shift(L) - 1 for L in rk["lookbacks"]) / len(rk["lookbacks"])
    sma_trend = c.rolling(rk["trend_sma"], min_periods=rk["trend_sma"]).mean()
    bench = c[rg["benchmark"]]
    sma_reg = bench.rolling(rg["sma_days"], min_periods=rg["sma_days"]).mean()
    return {"close": c, "atr": atr, "score": score, "sma_trend": sma_trend,
            "bench": bench, "sma_regime": sma_reg}


# --------------------------------------------------------------- regole
def regime_green(ind: dict, day, cfg: dict) -> bool:
    if not cfg["regime"].get("enabled", True):
        return True
    b, s = ind["bench"].get(day), ind["sma_regime"].get(day)
    return bool(b is not None and s is not None and not pd.isna(s) and b > s)


def eligible(sym: str, day, ind: dict, green: bool, classes: dict, cfg: dict) -> bool:
    rk = cfg["ranking"]
    cls = classes.get(sym, "stocks")
    if cls == "defensive" and green and rk.get("defensive_only_when_red"):
        return False
    if cls == "leveraged" and not green:
        return False
    if cls in ("stocks", "etf") and not green:
        return False
    try:
        close = ind["close"].at[day, sym]
        score = ind["score"].at[day, sym]
        sma = ind["sma_trend"].at[day, sym]
        atr = ind["atr"].at[day, sym]
    except KeyError:
        return False
    if pd.isna(close) or pd.isna(atr):
        return False
    if cls in rk.get("no_filter_classes", []):
        return True
    if close < rk["min_price"]:
        return False
    if rk.get("require_positive", True) and (pd.isna(score) or score <= 0):
        return False
    if rk.get("require_trend", True) and (pd.isna(sma) or close <= sma):
        return False
    return True


def ranking(day, ind: dict, cfg: dict, classes: dict) -> tuple[bool, list[str]]:
    """Restituisce (semaforo verde?, simboli idonei ordinati dal più forte)."""
    green = regime_green(ind, day, cfg)
    elig = [s for s in active_symbols(cfg) if eligible(s, day, ind, green, classes, cfg)]
    sc = ind["score"].loc[day] if day in ind["score"].index else pd.Series(dtype=float)
    elig.sort(key=lambda s: (sc.get(s) if not pd.isna(sc.get(s, np.nan)) else -9e9), reverse=True)
    return green, elig


def target_portfolio(ranked: list[str], held: list[str], cfg: dict) -> list[str]:
    """Titoli da tenere: quelli già in mano ancora nei primi `hold_buffer`, poi i più forti fino a N."""
    rk = cfg["ranking"]
    n, buf = rk["top_n"], rk["hold_buffer"]
    keep = [s for s in ranked[:buf] if s in held][:n]
    for s in ranked:
        if len(keep) >= n:
            break
        if s not in keep:
            keep.append(s)
    return keep


def initial_stop(day, sym: str, ind: dict, cfg: dict) -> float:
    return float(ind["close"].at[day, sym] - cfg["stop"]["atr_mult"] * ind["atr"].at[day, sym])


def trail_stop(prev_stop: float, day, sym: str, ind: dict, cfg: dict) -> float:
    c, a = ind["close"].at[day, sym], ind["atr"].at[day, sym]
    if pd.isna(c) or pd.isna(a):
        return prev_stop
    return max(prev_stop, float(c - cfg["stop"]["atr_mult"] * a))


def is_rebalance_day(day, next_day, freq: str = "weekly") -> bool:
    """Il segnale si calcola alla chiusura dell'ultimo giorno di borsa della settimana
    (l'esecuzione avviene all'apertura del primo giorno della settimana dopo)."""
    if next_day is None:
        return False
    if freq == "daily":
        return True
    return pd.Timestamp(day).isocalendar()[1] != pd.Timestamp(next_day).isocalendar()[1]
