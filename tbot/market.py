"""Lettura dati da Alpaca: barre azioni/cripto, notizie Benzinga, titoli più attivi."""
from __future__ import annotations

import json
import time as _time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from .common import UTC, is_rth
from .sentiment import headline_score

TF15 = TimeFrame(15, TimeFrameUnit.Minute)
TFD = TimeFrame(1, TimeFrameUnit.Day)
DATA_URL = "https://data.alpaca.markets"


class Market:
    def __init__(self, key: str, secret: str):
        self.key, self.secret = key, secret
        self.stock = StockHistoricalDataClient(key, secret)
        self.crypto = CryptoHistoricalDataClient(key, secret)

    # ------------------------------------------------------------ barre
    @staticmethod
    def _split(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        out = {}
        if df is None or df.empty:
            return out
        for sym, g in df.groupby(level=0):
            g = g.droplevel(0).sort_index()
            g.index = pd.DatetimeIndex(g.index).tz_convert(UTC)
            out[sym] = g[["open", "high", "low", "close", "volume"]].astype(float)
        return out

    def stock_bars(self, symbols: list[str], tf, start: datetime, end: datetime | None,
                   feed: str, rth_only: bool = False) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for i in range(0, len(symbols), 40):
            req = StockBarsRequest(symbol_or_symbols=symbols[i:i + 40], timeframe=tf, start=start,
                                   end=end, feed=DataFeed(feed), adjustment=Adjustment.ALL)
            out.update(self._split(self.stock.get_stock_bars(req).df))
        if rth_only:
            for s, g in out.items():
                out[s] = g[[is_rth(t) for t in g.index]]
        return out

    def crypto_bars(self, symbols: list[str], tf, start: datetime, end: datetime | None):
        if not symbols:
            return {}
        req = CryptoBarsRequest(symbol_or_symbols=symbols, timeframe=tf, start=start, end=end)
        return self._split(self.crypto.get_crypto_bars(req).df)

    # ---------------------------------------------------------- notizie
    def _get(self, path: str, params: dict) -> dict:
        headers = {"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret}
        for attempt in range(5):
            r = requests.get(DATA_URL + path, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                _time.sleep(3 + attempt * 3)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    def news(self, symbols: list[str], start: datetime, end: datetime | None = None) -> pd.DataFrame:
        """Notizie con punteggio di sentiment: colonne time, symbol, score, headline."""
        rows = []
        news_syms = [s.replace("/", "") for s in symbols]
        for i in range(0, len(news_syms), 30):
            params = {"symbols": ",".join(news_syms[i:i + 30]), "start": start.isoformat(),
                      "limit": 50, "sort": "asc"}
            if end is not None:
                params["end"] = end.isoformat()
            token = None
            while True:
                if token:
                    params["page_token"] = token
                data = self._get("/v1beta1/news", params)
                for a in data.get("news", []):
                    sc = headline_score(a.get("headline", ""))
                    for s in a.get("symbols", []):
                        if s in news_syms:
                            pair = next((x for x in symbols if x.replace("/", "") == s), s)
                            rows.append((a["created_at"], pair, sc, a.get("headline", "")))
                token = data.get("next_page_token")
                if not token:
                    break
        df = pd.DataFrame(rows, columns=["time", "symbol", "score", "headline"])
        if not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time").reset_index(drop=True)
        return df

    # ------------------------------------------------ titoli più attivi
    def most_actives(self, top: int = 20) -> list[str]:
        try:
            data = self._get("/v1beta1/screener/stocks/most-actives", {"by": "volume", "top": top})
            return [a["symbol"] for a in data.get("most_actives", [])]
        except Exception as exc:  # non deve mai bloccare il bot
            print(f"[avviso] screener non disponibile: {exc}")
            return []


def news_window(news: pd.DataFrame, symbol: str, now, hours: int) -> tuple[float, int]:
    if news is None or news.empty:
        return 0.0, 0
    lo = pd.Timestamp(now) - pd.Timedelta(hours=hours)
    m = (news["symbol"] == symbol) & (news["time"] > lo) & (news["time"] <= pd.Timestamp(now))
    s = news.loc[m, "score"]
    return (float(s.mean()), int(len(s))) if len(s) else (0.0, 0)


def cache_path(name: str) -> Path:
    p = Path(__file__).resolve().parent.parent / "cache"
    p.mkdir(exist_ok=True)
    return p / name


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str, ensure_ascii=False), encoding="utf-8")


def utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = ["Market", "TF15", "TFD", "news_window", "utcnow", "save_json", "cache_path", "timedelta"]
