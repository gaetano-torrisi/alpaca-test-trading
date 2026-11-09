"""Backtest: applica le regole della strategia (tbot/strategy.py) ai dati storici.

Modello di esecuzione, il più vicino possibile al bot reale:
 - decisione alla chiusura di ogni barra da 15 min, esecuzione a quel prezzo + slippage;
 - azioni: stop-loss e take-profit lato broker (bracket) -> verificati sul minimo/massimo
   della barra; se nella stessa barra si toccano entrambi si assume lo STOP (prudente);
 - cripto: uscite controllate dal bot a fine barra, commissione 0,25% per lato;
 - stessi limiti di rischio, stesso interruttore di sicurezza.
Non include i "titoli ospiti" (non si possono ricostruire nel passato).
"""
from __future__ import annotations

import argparse
import math
import pickle
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .common import ET, ROOT, UTC, all_stock_symbols, api_keys, is_crypto, load_config, symbol_class, universe
from .indicators import add_daily, add_intraday, last_closed
from .market import news_window
from .strategy import evaluate_entry, manage_position, position_size, regime_on

OUT = ROOT / "backtest"


# ------------------------------------------------------------------ dati
def fetch_data(cfg: dict, start: datetime, end: datetime) -> dict:
    from .market import TF15, TFD, Market, cache_path
    key, secret = api_keys()
    mk = Market(key, secret)
    tag = f"{start:%Y%m%d}_{end:%Y%m%d}"
    cp = cache_path(f"bt_{tag}.pkl")
    if cp.exists():
        return pickle.loads(cp.read_bytes())
    stocks = list(dict.fromkeys(all_stock_symbols(cfg) + [cfg["regime"]["stock_benchmark"]]))
    cryptos = universe(cfg)["crypto"]
    if cryptos:
        cryptos = list(dict.fromkeys(cryptos + [cfg["regime"]["crypto_benchmark"]]))
    feed = cfg["data"]["backtest_feed"]
    print(f"Scarico barre 15 min per {len(stocks)} titoli e {len(cryptos)} cripto...")
    data = {
        "intra": {**mk.stock_bars(stocks, TF15, start - timedelta(days=10), end, feed, rth_only=True),
                  **mk.crypto_bars(cryptos, TF15, start - timedelta(days=10), end)},
        "daily": {"stock": mk.stock_bars(stocks, TFD, start - timedelta(days=150), end, feed),
                  "crypto": mk.crypto_bars(cryptos, TFD, start - timedelta(days=150), end)},
        "news": pd.DataFrame(columns=["time", "symbol", "score", "headline"]),
    }
    if cfg["backtest"].get("use_news", True):
        print("Scarico le notizie storiche (può richiedere alcuni minuti)...")
        data["news"] = mk.news(stocks + cryptos, start - timedelta(days=1), end)
    cp.write_bytes(pickle.dumps(data))
    return data


# --------------------------------------------------------------- motore
def run_backtest(cfg: dict, data: dict, start: datetime, end: datetime, initial: float) -> dict:
    e, x, r, c = cfg["entry"], cfg["exit"], cfg["risk"], cfg["costs"]
    intra, daily = {}, {}
    for s, df in data["intra"].items():
        intra[s] = add_intraday(df, e["breakout_bars"], x["atr_period"])
    for kind, group in data["daily"].items():
        for s, df in group.items():
            daily[s] = add_daily(df, e["daily_ema_fast"], e["daily_ema_slow"], cfg["regime"]["ema_days"], kind == "crypto")
    news = data["news"]
    lookback = cfg["data"]["news_lookback_hours"]

    # pre-filtro vettoriale: solo le barre dove il segnale tecnico è possibile
    # (la decisione finale la prende comunque strategy.evaluate_entry)
    rows, raw = {}, {}
    for s, df in intra.items():
        df = df[(df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end))]
        intra[s] = df
        rows[s] = df.to_dict("index")
        m = ((df["close"] > df["prior_high"]) & df["rsi"].between(e["rsi_min"], e["rsi_max"])
             & (df["vol_ratio"] >= e["volume_ratio_min"]))
        raw[s] = set(df.index[m.fillna(False)])

    timeline = sorted(set().union(*[set(df.index) for df in intra.values()])) if intra else []
    u = universe(cfg)
    tradable = [s for s in all_stock_symbols(cfg) + u["crypto"] if s in intra]
    bench_s, bench_c = cfg["regime"]["stock_benchmark"], cfg["regime"]["crypto_benchmark"]

    cash, positions, trades, curve = initial, {}, [], []
    last_px: dict[str, float] = {}
    peak, halted, halt_time = initial, False, None
    day_key, day_start_eq = None, initial

    def slip(s):
        return (c["crypto_slippage_bps"] if is_crypto(s) else c["stock_slippage_bps"]) / 1e4

    def fee(s, value):
        return value * c["crypto_fee_bps"] / 1e4 if is_crypto(s) else 0.0

    def equity():
        return cash + sum(p["qty"] * last_px.get(s, p["entry"]) for s, p in positions.items())

    def close_pos(s, price, when, reason):
        nonlocal cash
        p = positions.pop(s)
        value = p["qty"] * price
        cash += value - fee(s, value)
        pnl = value - fee(s, value) - p["cost"]
        trades.append({"simbolo": s, "ingresso": p["entry_time"], "uscita": when, "quantita": p["qty"],
                       "prezzo_ingresso": round(p["entry"], 4), "prezzo_uscita": round(price, 4),
                       "pnl_usd": round(pnl, 2), "pnl_pct": round(pnl / p["cost"] * 100, 2),
                       "motivo_uscita": reason, "classe": p["cls"]})

    for t in timeline:
        now = t + pd.Timedelta(minutes=15)  # la barra è chiusa
        for s in list(rows):
            b = rows[s].get(t)
            if b is not None:
                last_px[s] = b["close"]

        dk = now.astimezone(ET).date()
        if dk != day_key:
            day_key, day_start_eq = dk, equity()

        # ---- uscite
        for s in list(positions):
            b = rows.get(s, {}).get(t)
            if b is None:
                continue
            p = positions[s]
            if p["bracket"]:
                if b["low"] <= p["stop"]:
                    close_pos(s, min(b["open"], p["stop"]) * (1 - slip(s)), now, "stop-loss")
                    continue
                if b["high"] >= p["target"]:
                    close_pos(s, max(b["open"], p["target"]), now, "take-profit")
                    continue
            else:
                if b["close"] <= p["stop"]:
                    close_pos(s, b["close"] * (1 - slip(s)), now, "stop-loss")
                    continue
                if b["close"] >= p["target"]:
                    close_pos(s, b["close"] * (1 - slip(s)), now, "take-profit")
                    continue
            reason, new_stop = manage_position(p, b, last_closed(daily.get(s), now), now.to_pydatetime(), cfg)
            if reason:
                close_pos(s, b["close"] * (1 - slip(s)), now, reason)
            elif new_stop is not None:
                p["stop"] = new_stop

        eq = equity()
        peak = max(peak, eq)
        if not halted and 1 - eq / peak >= r["max_drawdown_halt"]:
            for s in list(positions):
                close_pos(s, last_px[s] * (1 - slip(s)), now, "HALT drawdown")
            halted, halt_time = True, now
            eq = equity()
        curve.append((now, eq))

        # ---- ingressi
        if halted or eq < day_start_eq * (1 - r["daily_loss_limit"]):
            continue
        cands_syms = [s for s in tradable if t in raw.get(s, ()) and s not in positions]
        if not cands_syms:
            continue
        stock_on = regime_on(last_closed(daily.get(bench_s), now))
        crypto_on = regime_on(last_closed(daily.get(bench_c), now))
        cands = []
        for s in cands_syms:
            cnd = evaluate_entry(s, symbol_class(s, cfg), rows[s][t], last_closed(daily.get(s), now),
                                 news_window(news, s, now, lookback), stock_on, crypto_on, cfg)
            if cnd:
                cands.append(cnd)
        cands.sort(key=lambda k: k.score, reverse=True)
        exposure = sum(p["qty"] * last_px.get(s, p["entry"]) for s, p in positions.items())
        n_crypto = sum(is_crypto(s) for s in positions)
        done = 0
        for cnd in cands:
            if done >= e["max_new_per_run"] or len(positions) >= r["max_positions"]:
                break
            if cnd.cls == "crypto" and n_crypto >= r["max_crypto_positions"]:
                continue
            qty = position_size(cnd, eq, exposure, cfg)
            if qty <= 0:
                continue
            fill = cnd.price * (1 + slip(cnd.symbol))
            value = qty * fill
            cost = value + fee(cnd.symbol, value)
            cash -= cost
            positions[cnd.symbol] = {"entry": fill, "qty": qty, "stop": cnd.stop, "target": cnd.target,
                                     "atr": cnd.atr, "entry_time": now.to_pydatetime(), "cost": cost,
                                     "bracket": cnd.cls != "crypto", "cls": cnd.cls}
            exposure += value
            n_crypto += cnd.cls == "crypto"
            done += 1

    end_t = timeline[-1] + pd.Timedelta(minutes=15) if timeline else pd.Timestamp(end)
    for s in list(positions):
        close_pos(s, last_px[s], end_t, "fine backtest")
    if curve:
        curve[-1] = (curve[-1][0], equity())

    bench = data["daily"]["stock"].get(bench_s)
    return {"curve": pd.Series(dict(curve)), "trades": pd.DataFrame(trades), "initial": initial,
            "halted": halt_time, "bench": bench[(bench.index >= pd.Timestamp(start)) & (bench.index < pd.Timestamp(end))] if bench is not None else None}


# ---------------------------------------------------------------- metriche
def metrics(res: dict) -> dict:
    curve, tr, init = res["curve"], res["trades"], res["initial"]
    if curve.empty:
        return {}
    daily = curve.groupby(curve.index.tz_convert(ET).date).last()
    rets = daily.pct_change().dropna()
    years = max((curve.index[-1] - curve.index[0]).days / 365.25, 1e-9)
    final = curve.iloc[-1]
    dd = 1 - curve / curve.cummax()
    m = {
        "capitale_iniziale": init, "capitale_finale": round(final, 2),
        "rendimento_totale_pct": round((final / init - 1) * 100, 2),
        "rendimento_annuo_pct": round(((final / init) ** (1 / years) - 1) * 100, 2),
        "drawdown_massimo_pct": round(dd.max() * 100, 2),
        "sharpe": round(rets.mean() / rets.std() * math.sqrt(252), 2) if rets.std() > 0 else 0.0,
        "operazioni": int(len(tr)),
    }
    if len(tr):
        wins, losses = tr[tr.pnl_usd > 0], tr[tr.pnl_usd <= 0]
        m.update({
            "percentuale_vincenti": round(len(wins) / len(tr) * 100, 1),
            "profit_factor": round(wins.pnl_usd.sum() / -losses.pnl_usd.sum(), 2) if losses.pnl_usd.sum() < 0 else float("inf"),
            "guadagno_medio_usd": round(wins.pnl_usd.mean(), 2) if len(wins) else 0,
            "perdita_media_usd": round(losses.pnl_usd.mean(), 2) if len(losses) else 0,
            "durata_media_ore": round(((pd.to_datetime(tr.uscita, utc=True) - pd.to_datetime(tr.ingresso, utc=True))
                                      .dt.total_seconds() / 3600).mean(), 1),
        })
    b = res.get("bench")
    if b is not None and len(b) > 1:
        bret = b["close"].iloc[-1] / b["close"].iloc[0] - 1
        bdd = (1 - b["close"] / b["close"].cummax()).max()
        m["spy_rendimento_pct"] = round(bret * 100, 2)
        m["spy_drawdown_massimo_pct"] = round(bdd * 100, 2)
    return m


def write_report(cfg: dict, res: dict, m: dict, start, end) -> None:
    OUT.mkdir(exist_ok=True)
    tr = res["trades"]
    tr.to_csv(OUT / "operazioni.csv", index=False)
    curve = res["curve"]
    daily = curve.groupby(curve.index.tz_convert(ET).date).last()
    daily.rename("capitale").to_csv(OUT / "capitale_giornaliero.csv", index_label="data")
    lines = [f"# Risultati backtest  ({start:%d/%m/%Y} – {end:%d/%m/%Y})", "",
             f"Generato il {datetime.now(UTC).astimezone(ET):%d/%m/%Y %H:%M} ET. "
             "Costi inclusi: slippage azioni {} bps, cripto {} bps, commissione cripto {} bps.".format(
                 cfg["costs"]["stock_slippage_bps"], cfg["costs"]["crypto_slippage_bps"], cfg["costs"]["crypto_fee_bps"]),
             "", "| Metrica | Valore |", "|---|---|"]
    labels = {"capitale_iniziale": "Capitale iniziale ($)", "capitale_finale": "Capitale finale ($)",
              "rendimento_totale_pct": "Rendimento totale (%)", "rendimento_annuo_pct": "Rendimento annuo (%)",
              "drawdown_massimo_pct": "Perdita massima dal picco (%)", "sharpe": "Sharpe ratio",
              "operazioni": "Operazioni", "percentuale_vincenti": "Operazioni in guadagno (%)",
              "profit_factor": "Profit factor", "guadagno_medio_usd": "Guadagno medio ($)",
              "perdita_media_usd": "Perdita media ($)", "durata_media_ore": "Durata media (ore)",
              "spy_rendimento_pct": "Confronto: SPY compra-e-tieni (%)",
              "spy_drawdown_massimo_pct": "Confronto: perdita massima SPY (%)"}
    for k, v in m.items():
        lines.append(f"| {labels.get(k, k)} | {v:,} |" if isinstance(v, (int, float)) else f"| {labels.get(k, k)} | {v} |")
    if res.get("halted"):
        lines += ["", f"**Attenzione:** l'interruttore di sicurezza è scattato il {res['halted']:%d/%m/%Y}."]
    if len(tr):
        lines += ["", "## Risultato per tipo di strumento", "", "| Classe | Operazioni | P&L ($) | Vincenti (%) |", "|---|---|---|---|"]
        for cls, g in tr.groupby("classe"):
            lines.append(f"| {cls} | {len(g)} | {g.pnl_usd.sum():,.0f} | {(g.pnl_usd > 0).mean() * 100:.0f} |")
        lines += ["", "## Motivi di uscita", "", "| Motivo | Operazioni | P&L ($) |", "|---|---|---|"]
        for why, g in tr.groupby("motivo_uscita"):
            lines.append(f"| {why} | {len(g)} | {g.pnl_usd.sum():,.0f} |")
        by_sym = tr.groupby("simbolo").pnl_usd.sum().sort_values()
        lines += ["", "## Titoli migliori e peggiori", "", "| Titolo | P&L ($) |", "|---|---|"]
        shown = by_sym[::-1] if len(by_sym) <= 10 else pd.concat([by_sym.tail(5)[::-1], by_sym.head(5)])
        for s, v in shown.items():
            lines.append(f"| {s} | {v:,.0f} |")
    (OUT / "risultati.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    a = ap.parse_args()
    cfg = load_config()
    bt = cfg["backtest"]
    start = datetime.fromisoformat(a.start or bt["start"]).replace(tzinfo=UTC)
    end_s = a.end or bt.get("end")
    end = (datetime.fromisoformat(end_s).replace(tzinfo=UTC) if end_s
           else datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0))
    data = fetch_data(cfg, start, end)
    res = run_backtest(cfg, data, start, end, bt["initial_equity"])
    write_report(cfg, res, metrics(res), start, end)


if __name__ == "__main__":
    main()
