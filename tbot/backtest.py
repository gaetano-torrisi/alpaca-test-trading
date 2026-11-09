"""Backtest della strategia momentum giornaliero (regole in tbot/momentum.py).

Modello di esecuzione, uguale al bot reale:
 - segnali calcolati alla chiusura del giorno D, ordini eseguiti all'apertura del giorno D+1;
 - stop sul broker durante il giorno: se il minimo tocca lo stop si esce a quel prezzo
   (o all'apertura, se il titolo apre già sotto);
 - frazioni di azione ammesse (capitale 1.000 $), costo di 5 punti base per ogni operazione.
"""
from __future__ import annotations

import argparse
import copy
import math
import pickle
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .common import ROOT, UTC, api_keys, load_config
from .momentum import (all_symbols, indicators, initial_stop, is_rebalance_day, ranking, symbol_classes,
                       target_portfolio, to_panel, trail_stop)

OUT = ROOT / "backtest"


def fetch_daily(cfg: dict, start: datetime, end: datetime) -> dict:
    from .market import TFD, Market, cache_path
    cp = cache_path(f"daily_{start:%Y%m%d}_{end:%Y%m%d}_{len(all_symbols(cfg))}.pkl")
    if cp.exists():
        return pickle.loads(cp.read_bytes())
    key, secret = api_keys()
    mk = Market(key, secret)
    syms = all_symbols(cfg)
    print(f"Scarico i prezzi giornalieri di {len(syms)} strumenti dal {start:%d/%m/%Y}...")
    data = mk.stock_bars(syms, TFD, start - timedelta(days=10), end, "sip")
    cp.write_bytes(pickle.dumps(data))
    return data


def apply_overrides(cfg: dict, overrides: dict) -> dict:
    out = copy.deepcopy(cfg)
    for dotted, val in (overrides or {}).items():
        d = out
        *path, last = dotted.split(".")
        for k in path:
            d = d[k]
        d[last] = val
    return out


def run(cfg: dict, panel: dict, eval_start, initial: float) -> dict:
    ind = indicators(panel, cfg)
    classes = symbol_classes(cfg)
    o, h, lo, c = panel["open"], panel["high"], panel["low"], panel["close"]
    slip = cfg["costs"]["slippage_bps"] / 1e4
    buf = cfg["risk"]["cash_buffer"]
    n = cfg["ranking"]["top_n"]
    days = [d for d in ind["bench"].dropna().index if d >= eval_start]

    cash, pos, trades, curve = initial, {}, [], []
    pending_sell: set[str] = set()
    pending_buy: list[str] = []

    def value(day):
        return cash + sum(p["qty"] * (c.at[day, s] if not pd.isna(c.at[day, s]) else p["last"]) for s, p in pos.items())

    def sell(s, price, day, reason):
        nonlocal cash
        p = pos.pop(s)
        cash += p["qty"] * price
        pnl = p["qty"] * (price - p["entry"])
        trades.append({"simbolo": s, "classe": classes.get(s), "ingresso": p["day"], "uscita": day,
                       "prezzo_ingresso": round(p["entry"], 4), "prezzo_uscita": round(price, 4),
                       "pnl_usd": round(pnl, 2), "pnl_pct": round((price / p["entry"] - 1) * 100, 2),
                       "motivo_uscita": reason})

    for i, day in enumerate(days):
        # ---- apertura: esegue gli ordini decisi ieri sera
        for s in sorted(pending_sell):
            if s in pos and not pd.isna(o.at[day, s]):
                sell(s, o.at[day, s] * (1 - slip), day, pos[s].get("why", "ribilanciamento"))
        pending_sell = set()
        if pending_buy:
            eq_open = cash + sum(p["qty"] * (o.at[day, s] if not pd.isna(o.at[day, s]) else p["last"]) for s, p in pos.items())
            slot = eq_open / n
            for s, stop in pending_buy:
                px_ = o.at[day, s]
                if s in pos or pd.isna(px_):
                    continue
                notional = min(slot, cash - eq_open * buf)
                if notional < 1:
                    continue
                fill = px_ * (1 + slip)
                pos[s] = {"qty": notional / fill, "entry": fill, "stop": stop, "day": day, "last": fill}
                cash -= notional
        pending_buy = []

        # ---- durante il giorno: stop sul broker
        for s in list(pos):
            p = pos[s]
            if not pd.isna(lo.at[day, s]) and lo.at[day, s] <= p["stop"]:
                sell(s, min(o.at[day, s], p["stop"]) * (1 - slip), day, "stop")

        # ---- chiusura: aggiorna stop, valuta, decide per domani
        for s, p in pos.items():
            if not pd.isna(c.at[day, s]):
                p["last"] = c.at[day, s]
            p["stop"] = trail_stop(p["stop"], day, s, ind, cfg)
        curve.append((day, value(day)))

        nxt = days[i + 1] if i + 1 < len(days) else None
        if nxt is None:
            break
        green, ranked = ranking(day, ind, cfg, classes)
        # uscite giornaliere: titolo non più idoneo per il semaforo (es. ROSSO -> fuori dalle azioni)
        for s in pos:
            if classes.get(s) in ("stocks", "etf", "leveraged") and not green and cfg["regime"].get("enabled", True):
                pending_sell.add(s)
                pos[s]["why"] = "semaforo rosso"
        if is_rebalance_day(day, nxt, cfg["ranking"].get("rebalance", "weekly")):
            target = target_portfolio(ranked, list(pos), cfg)
            for s in pos:
                if s not in target:
                    pending_sell.add(s)
                    pos[s].setdefault("why", "uscito dalla classifica")
            pending_buy = [(s, initial_stop(day, s, ind, cfg)) for s in target if s not in pos]

    last = days[-1] if days else None
    for s in list(pos):
        sell(s, c.at[last, s], last, "fine backtest")
    curve_s = pd.Series(dict(curve))
    return {"curve": curve_s, "trades": pd.DataFrame(trades), "initial": initial}


# --------------------------------------------------------------- metriche
def stats(curve: pd.Series) -> dict:
    if len(curve) < 2:
        return {}
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    r = curve.pct_change().dropna()
    dd = 1 - curve / curve.cummax()
    return {"finale": curve.iloc[-1], "totale": (curve.iloc[-1] / curve.iloc[0] - 1) * 100,
            "annuo": ((curve.iloc[-1] / curve.iloc[0]) ** (1 / max(years, 1e-9)) - 1) * 100,
            "dd": dd.max() * 100, "sharpe": r.mean() / r.std() * math.sqrt(252) if r.std() > 0 else 0}


def period(curve, a, b):
    return curve[(curve.index >= pd.Timestamp(a)) & (curve.index < pd.Timestamp(b))]


def report(cfg: dict, results: list, eval_start, end) -> str:
    split = pd.Timestamp(cfg["backtest"]["split_date"])
    L = [f"# Backtest momentum giornaliero  ({eval_start:%d/%m/%Y} – {end:%d/%m/%Y})", "",
         f"Capitale iniziale {cfg['backtest']['initial_equity']:,} $. Costi: {cfg['costs']['slippage_bps']} punti base "
         f"per operazione. Periodo A = fino al {split:%d/%m/%Y} (scelta), periodo B = dopo (verifica).", "",
         "## Riepilogo", "",
         "| Variante | Capitale finale $ | Rend. annuo % | Perdita max % | Sharpe | Annuo A % | Annuo B % | Operazioni |",
         "|---|---|---|---|---|---|---|---|"]
    for name, res in results:
        f, a, b = stats(res["curve"]), stats(period(res["curve"], eval_start, split)), stats(period(res["curve"], split, end))
        L.append(f"| {name} | {f['finale']:,.0f} | {f['annuo']:.1f} | {f['dd']:.1f} | {f['sharpe']:.2f} "
                 f"| {a.get('annuo', float('nan')):.1f} | {b.get('annuo', float('nan')):.1f} | {len(res['trades'])} |")
    years = sorted({d.year for d in results[0][1]["curve"].index})
    L += ["", "## Rendimento anno per anno (%)", "", "| Variante | " + " | ".join(map(str, years)) + " |",
          "|---|" + "---|" * len(years)]
    for name, res in results:
        cv = res["curve"]
        row = []
        for y in years:
            yc = cv[cv.index.year == y]
            prev = cv[cv.index.year < y]
            base = prev.iloc[-1] if len(prev) else yc.iloc[0]
            row.append(f"{(yc.iloc[-1] / base - 1) * 100:+.1f}" if len(yc) else "–")
        L.append(f"| {name} | " + " | ".join(row) + " |")
    L += ["", "## Nei momenti difficili (perdita massima nel periodo, %)", "",
          "| Variante | Crollo Covid (feb–mar 2020) | Anno 2022 | Calo apr 2025 |", "|---|---|---|---|"]
    for name, res in results:
        out = []
        for a, b in (("2020-02-15", "2020-04-30"), ("2022-01-01", "2023-01-01"), ("2025-02-15", "2025-05-15")):
            p = period(res["curve"], a, b)
            out.append(f"{(1 - p / p.cummax()).max() * 100:.1f}" if len(p) else "–")
        L.append(f"| {name} | " + " | ".join(out) + " |")
    L += ["", "## Dettaglio operazioni per variante", ""]
    for name, res in results:
        t = res["trades"]
        if not len(t):
            continue
        win = (t.pnl_usd > 0).mean() * 100
        hold = (pd.to_datetime(t.uscita) - pd.to_datetime(t.ingresso)).dt.days.mean()
        L.append(f"**{name}**: {len(t)} operazioni, {win:.0f}% in guadagno, durata media {hold:.0f} giorni. "
                 f"Uscite: " + ", ".join(f"{k} {v}" for k, v in t.motivo_uscita.value_counts().items()) + ".")
        best = t.groupby("simbolo").pnl_usd.sum().sort_values(ascending=False)
        L.append(f"Migliori: {', '.join(f'{s} {v:+,.0f}$' for s, v in best.head(4).items())}. "
                 f"Peggiori: {', '.join(f'{s} {v:+,.0f}$' for s, v in best.tail(3).items())}.")
        L.append("")
    return "\n".join(L) + "\n"


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
    panel = to_panel(fetch_daily(cfg, start, end))
    base_ind = indicators(panel, cfg)
    eval_start = base_ind["sma_regime"].dropna().index[0] + pd.Timedelta(days=1)
    results = []
    OUT.mkdir(exist_ok=True)
    for v in bt["variants"]:
        vcfg = apply_overrides(cfg, v.get("modifiche"))
        res = run(vcfg, panel, eval_start, bt["initial_equity"])
        results.append((v["nome"], res))
        res["trades"].to_csv(OUT / f"operazioni_{v['nome']}.csv", index=False)
    pd.DataFrame({n: r["curve"] for n, r in results}).round(2).to_csv(OUT / "capitale_varianti.csv", index_label="data")
    text = report(cfg, results, eval_start, pd.Timestamp(end.date()))
    (OUT / "risultati.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
