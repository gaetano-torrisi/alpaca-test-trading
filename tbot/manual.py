"""Acquisti manuali decisi da Gaetano: ordini a importo, registrati nei log come 'manuale'."""
from __future__ import annotations

import argparse

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from .common import api_keys
from .live import action, load_state, save_state
from .market import utcnow


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simboli", required=True, help="es. CRWD,AAPL,MSFT")
    ap.add_argument("--importo", type=float, required=True, help="dollari per ciascun titolo")
    a = ap.parse_args()
    key, secret = api_keys()
    tc = TradingClient(key, secret, paper=True)
    st = load_state()
    cash = float(tc.get_account().cash)
    syms = [s.strip().upper() for s in a.simboli.split(",") if s.strip()]
    print(f"Liquidità disponibile: {cash:.2f} $ | richiesti {len(syms)} x {a.importo:.2f} $")
    for s in syms:
        if a.importo > cash:
            print(f"[avviso] liquidità insufficiente per {s}: saltato")
            continue
        try:
            tc.submit_order(MarketOrderRequest(symbol=s, notional=round(a.importo, 2), side=OrderSide.BUY,
                                               time_in_force=TimeInForce.DAY))
        except Exception as exc:
            print(f"[avviso] ordine rifiutato per {s}: {exc}")
            continue
        cash -= a.importo
        st["positions"][s] = {"entry": 0.0, "qty": 0.0, "stop": None, "entry_time": utcnow().isoformat(),
                              "reason": "acquisto manuale (Gaetano)", "pending": True}
        action("COMPRA", s, f"{a.importo:.2f}$", "mercato", "acquisto manuale (Gaetano)")
    save_state(st)


if __name__ == "__main__":
    main()
