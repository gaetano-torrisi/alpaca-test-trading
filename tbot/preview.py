"""Anteprima della classifica: NON invia ordini e non modifica lo stato del bot."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .common import ET, api_keys, load_config
from .market import TFD, Market, utcnow
from .momentum import active_symbols, indicators, ranking, symbol_classes, target_portfolio, to_panel


def main() -> None:
    cfg = load_config()
    key, secret = api_keys()
    mk, now = Market(key, secret), utcnow()
    syms = list(dict.fromkeys(active_symbols(cfg) + [cfg["regime"]["benchmark"]]))
    panel = to_panel(mk.stock_bars(syms, TFD, now - timedelta(days=420), now - timedelta(minutes=20), "sip"))
    today = pd.Timestamp(now.astimezone(ET).date())
    panel = {k: v[v.index < today] for k, v in panel.items()}
    ind = indicators(panel, cfg)
    day = ind["bench"].dropna().index[-1]
    green, ranked = ranking(day, ind, cfg, symbol_classes(cfg))
    b, s = ind["bench"].at[day], ind["sma_regime"].at[day]
    print(f"## Anteprima classifica – chiusura del {day:%d/%m/%Y}\n")
    print(f"Semaforo: **{'VERDE' if green else 'ROSSO'}** – {cfg['regime']['benchmark']} {b:.2f} $ "
          f"contro media {cfg['regime']['sma_days']} giorni {s:.2f} $ ({(b / s - 1) * 100:+.2f}%)\n")
    target = target_portfolio(ranked, [], cfg)
    print(f"Se il ribilanciamento fosse oggi, comprerebbe: **{', '.join(target) or 'nulla'}**\n")
    print("| # | Titolo | Forza 3-6 mesi | Sopra media 50 gg | Idoneo |\n|---|---|---|---|---|")
    rows = []
    for sym in active_symbols(cfg):
        if sym not in ind["close"].columns:
            continue
        sc, c, m = ind["score"].at[day, sym], ind["close"].at[day, sym], ind["sma_trend"].at[day, sym]
        rows.append((sym, sc, c > m if not pd.isna(m) else False, sym in ranked))
    rows.sort(key=lambda r: -9 if pd.isna(r[1]) else r[1], reverse=True)
    for i, (sym, sc, above, ok) in enumerate(rows, 1):
        print(f"| {i} | {sym} | {sc:+.1%} | {'sì' if above else 'no'} | {'✅' if ok else '–'} |")


if __name__ == "__main__":
    main()
