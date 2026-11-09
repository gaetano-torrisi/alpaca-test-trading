"""Bot reale sul conto Paper - strategia momentum giornaliero (regole in tbot/momentum.py).

Avviato da GitHub Actions ogni 15 minuti durante la seduta di Wall Street.
 - Una volta al giorno (primo giro dopo l'apertura): semaforo, classifica, stop, vendite e acquisti.
   Il ribilanciamento della classifica avviene solo il primo giorno di borsa della settimana.
 - Ogni giro: controlla che ogni posizione abbia il suo stop sul broker e sorveglia le notizie.
"""
from __future__ import annotations

import csv
import json
import time
import traceback
from datetime import datetime, timedelta

import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetCalendarRequest, GetOrdersRequest, MarketOrderRequest, StopOrderRequest

from .common import ET, ROOT, api_keys, load_config, stock_session
from .market import TFD, Market, news_window, utcnow
from .momentum import (active_symbols, indicators, initial_stop, ranking, symbol_classes, target_portfolio,
                       to_panel, trail_stop)

STATE = ROOT / "state" / "state.json"
LOG = ROOT / "log"


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"peak_equity": None, "halted": False, "positions": {}, "last_daily": None, "last_rebalance_week": None}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2, default=str), encoding="utf-8")


def append_csv(name: str, header: list[str], row: list) -> None:
    LOG.mkdir(exist_ok=True)
    path = LOG / name
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


def action(kind: str, symbol: str, amount, price, reason: str) -> None:
    ts = utcnow().astimezone(ET).strftime("%Y-%m-%d %H:%M ET")
    print(f"{ts} {kind:<10} {symbol:<6} {amount} @ {price} | {reason}")
    append_csv("azioni.csv", ["ora", "azione", "simbolo", "quantita_o_importo", "prezzo", "motivo"],
               [ts, kind, symbol, amount, price, reason])


def fnum(x) -> float:
    return float(x) if x not in (None, "") else 0.0


def px(p: float) -> float:
    return round(p, 2) if p >= 1 else round(p, 4)


class Bot:
    def __init__(self):
        self.cfg = load_config()
        key, secret = api_keys()
        self.tc = TradingClient(key, secret, paper=True)
        self.mk = Market(key, secret)
        self.st = load_state()
        self.now = utcnow()
        self.today = self.now.astimezone(ET).date()
        self.classes = symbol_classes(self.cfg)
        self.live_trading = self.cfg.get("trading_enabled", True)

    # ------------------------------------------------------------ conto
    def account(self) -> None:
        a = self.tc.get_account()
        self.equity, self.cash = fnum(a.equity), fnum(a.cash)
        self.st["peak_equity"] = max(self.st.get("peak_equity") or self.equity, self.equity)
        append_csv("capitale.csv", ["ora_utc", "capitale", "liquidita", "esposizione_long"],
                   [self.now.strftime("%Y-%m-%d %H:%M"), round(self.equity, 2), a.cash, a.long_market_value])

    def positions(self) -> dict[str, dict]:
        out = {}
        for p in self.tc.get_all_positions():
            if p.asset_class == AssetClass.CRYPTO:
                continue
            out[p.symbol] = {"qty": fnum(p.qty), "avg": fnum(p.avg_entry_price),
                             "value": abs(fnum(p.market_value)), "price": fnum(p.current_price)}
        return out

    def open_orders(self) -> list:
        return self.tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=False, limit=500))

    def cancel_for(self, sym: str, orders: list) -> None:
        for o in orders:
            if o.symbol == sym:
                try:
                    self.tc.cancel_order_by_id(o.id)
                except Exception:
                    pass

    # -------------------------------------------------------- sicurezza
    def kill_switch(self) -> bool:
        r = self.cfg["risk"]
        if r.get("halt_reset"):
            self.st["halted"] = False
            self.st["peak_equity"] = self.equity
        if self.st.get("halted"):
            print("Bot FERMO per perdita massima. Per riattivarlo: risk.halt_reset: true in config.yaml")
            return True
        dd = 1 - self.equity / self.st["peak_equity"]
        if dd >= r["max_drawdown_halt"]:
            if self.live_trading:
                self.tc.close_all_positions(cancel_orders=True)
            self.st["halted"] = True
            action("BLOCCO", "-", "-", "-", f"perdita dal massimo {dd:.1%}: chiuso tutto")
            return True
        return False

    # -------------------------------------------------- riconciliazione
    def reconcile(self, live: dict) -> None:
        tracked = self.st["positions"]
        gone = [s for s in tracked if s not in live]
        if gone:
            after = min(datetime.fromisoformat(tracked[s]["entry_time"]) for s in gone) - timedelta(minutes=5)
            closed = self.tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after,
                                                         nested=False, limit=500))
            open_buys = {o.symbol for o in self.open_orders() if o.side == OrderSide.BUY}
            for s in gone:
                if tracked[s].get("pending"):
                    if s not in open_buys:
                        print(f"Acquisto di {s} non eseguito: rimosso.")
                        tracked.pop(s)
                    continue
                pos = tracked.pop(s)
                sells = [o for o in closed if o.symbol == s and o.side == OrderSide.SELL and o.filled_at is not None]
                o = max(sells, key=lambda o: o.filled_at) if sells else None
                exit_p = fnum(o.filled_avg_price) if o else pos["entry"]
                kind = str(getattr(o, "order_type", None) or getattr(o, "type", "")).lower() if o else ""
                reason = pos.get("exit_reason") or ("stop" if "stop" in kind else "chiusura")
                pnl = (exit_p - pos["entry"]) * pos["qty"]
                append_csv("operazioni.csv",
                           ["simbolo", "ingresso_utc", "uscita_utc", "quantita", "prezzo_ingresso", "prezzo_uscita",
                            "pnl_usd", "pnl_pct", "motivo_uscita", "motivo_ingresso"],
                           [s, pos["entry_time"][:16], (o.filled_at if o else self.now).strftime("%Y-%m-%d %H:%M"),
                            round(pos["qty"], 6), px(pos["entry"]), px(exit_p), round(pnl, 2),
                            round((exit_p / pos["entry"] - 1) * 100, 2), reason, pos.get("reason", "")])
                action("CHIUSA", s, round(pos["qty"], 4), px(exit_p), f"{reason}, P&L {pnl:+.2f} $")
        for s, p in live.items():
            if s not in tracked:
                tracked[s] = {"entry": p["avg"], "qty": p["qty"], "stop": None,
                              "entry_time": self.now.isoformat(), "reason": "posizione trovata sul conto"}
            else:
                tracked[s]["entry"] = p["avg"] or tracked[s]["entry"]
                tracked[s]["qty"] = p["qty"]
                tracked[s].pop("pending", None)

    # ------------------------------------------------------- dati e segnali
    def signals(self) -> None:
        cfg = self.cfg
        syms = list(dict.fromkeys(active_symbols(cfg) + list(self.st["positions"]) + [cfg["regime"]["benchmark"]]))
        bars = self.mk.stock_bars(syms, TFD, self.now - timedelta(days=420), self.now - timedelta(minutes=20), "sip")
        panel = to_panel(bars)
        today = pd.Timestamp(self.today)
        panel = {k: v[v.index < today] for k, v in panel.items()}  # solo giornate CHIUSE
        self.ind = indicators(panel, cfg)
        self.day = self.ind["bench"].dropna().index[-1]
        self.green, self.ranked = ranking(self.day, self.ind, cfg, self.classes)
        print(f"Ultima chiusura: {self.day:%d/%m/%Y} | semaforo {'VERDE' if self.green else 'ROSSO'} | "
              f"classifica: {', '.join(self.ranked[:8]) or 'nessun titolo idoneo'}")

    def news_score(self, syms: list[str]) -> None:
        n = self.cfg["news"]
        self.news = pd.DataFrame(columns=["time", "symbol", "score", "headline"])
        if not n.get("enabled") or not syms:
            return
        try:
            self.news = self.mk.news(syms, self.now - timedelta(hours=n["lookback_hours"]))
        except Exception as exc:
            print(f"[avviso] notizie non disponibili: {exc}")

    # ------------------------------------------------------------- ordini
    def sell(self, sym: str, reason: str, orders: list) -> None:
        pos = self.st["positions"].get(sym, {})
        if not self.live_trading:
            action("(sim)VENDI", sym, pos.get("qty"), "-", reason)
            return
        self.cancel_for(sym, orders)
        time.sleep(1)
        try:
            self.tc.close_position(sym)
            pos["exit_reason"] = reason
            action("VENDI", sym, round(pos.get("qty", 0), 4), "mercato", reason)
        except Exception as exc:
            print(f"[avviso] vendita non riuscita per {sym}: {exc}")

    def buy(self, sym: str, notional: float, reason: str) -> bool:
        if not self.live_trading:
            action("(sim)COMPRA", sym, f"{notional:.2f}$", "-", reason)
            return False
        try:
            self.tc.submit_order(MarketOrderRequest(symbol=sym, notional=round(notional, 2), side=OrderSide.BUY,
                                                    time_in_force=TimeInForce.DAY))
        except Exception as exc:
            print(f"[avviso] acquisto rifiutato per {sym}: {exc}")
            return False
        self.st["positions"][sym] = {"entry": float(self.ind["close"].at[self.day, sym]), "qty": 0.0,
                                     "stop": initial_stop(self.day, sym, self.ind, self.cfg),
                                     "entry_time": self.now.isoformat(), "reason": reason, "pending": True}
        action("COMPRA", sym, f"{notional:.2f}$", "mercato", reason)
        return True

    def ensure_stops(self) -> None:
        """Ogni posizione deve avere il suo ordine stop (valido per la giornata) sul broker."""
        if not self.live_trading:
            return
        live, orders = self.positions(), self.open_orders()
        for sym, p in live.items():
            stop = (self.st["positions"].get(sym) or {}).get("stop")
            if stop is None or stop <= 0:
                continue
            mine = [o for o in orders if o.symbol == sym and o.side == OrderSide.SELL and o.stop_price is not None]
            ok = [o for o in mine if abs(fnum(o.stop_price) - px(stop)) < 0.01 and abs(fnum(o.qty) - p["qty"]) < 1e-6]
            if ok:
                continue
            self.cancel_for(sym, mine)
            try:
                self.tc.submit_order(StopOrderRequest(symbol=sym, qty=p["qty"], side=OrderSide.SELL,
                                                      time_in_force=TimeInForce.DAY, stop_price=px(stop)))
                print(f"Stop su {sym} a {px(stop)} $")
            except Exception as exc:
                print(f"[avviso] stop non piazzato per {sym}: {exc}")

    # --------------------------------------------------- routine giornaliera
    def daily(self, live: dict) -> None:
        cfg, n_cfg = self.cfg, self.cfg["news"]
        self.signals()
        orders = self.open_orders()
        # 1) aggiorna gli stop (non scendono mai)
        for s, pos in self.st["positions"].items():
            if s not in self.ind["close"].columns:
                continue
            base = pos.get("stop")
            if base is None:
                base = initial_stop(self.day, s, self.ind, cfg)
            pos["stop"] = trail_stop(base, self.day, s, self.ind, cfg)
        # 2) vendite: semaforo rosso
        to_sell: dict[str, str] = {}
        if cfg["regime"].get("enabled", True) and not self.green:
            for s in live:
                if self.classes.get(s, "stocks") in ("stocks", "etf", "leveraged"):
                    to_sell[s] = "semaforo rosso"
        # 3) ribilanciamento settimanale
        week = f"{self.today.isocalendar()[0]}-{self.today.isocalendar()[1]}"
        if cfg["ranking"].get("rebalance", "weekly") == "daily":
            week = self.today.isoformat()
        rebalance = self.st.get("last_rebalance_week") != week
        buys: list[str] = []
        if rebalance:
            target = target_portfolio(self.ranked, [s for s in live if s not in to_sell], cfg)
            for s in live:
                if s not in target:
                    to_sell.setdefault(s, "uscito dalla classifica")
            buys = [s for s in target if s not in live]
            self.st["last_rebalance_week"] = week
            print(f"Ribilanciamento. Obiettivo: {target or 'tutto in liquidità'}")
        for s, why in to_sell.items():
            self.sell(s, why, orders)
        # 4) acquisti (importo uguale per ogni posto in classifica)
        if buys:
            self.news_score(buys)
            time.sleep(3)
            remaining = sum(p["value"] for s, p in live.items() if s not in to_sell)
            budget = self.equity * (1 - cfg["risk"]["cash_buffer"]) - remaining
            slot = self.equity / cfg["ranking"]["top_n"]
            for s in buys:
                score, n = news_window(self.news, s, self.now, n_cfg["lookback_hours"])
                if n >= 2 and score <= n_cfg["block_buy_below"]:
                    action("SALTATO", s, "-", "-", f"notizie molto negative ({score:+.2f} su {n})")
                    continue
                notional = min(slot, budget)
                if notional < 1:
                    break
                sc = self.ind["score"].at[self.day, s]
                if self.buy(s, notional, f"classifica #{self.ranked.index(s) + 1}, forza {sc:+.1%}, "
                                         f"semaforo {'verde' if self.green else 'rosso'}"):
                    budget -= notional
        self.st["last_daily"] = self.today.isoformat()

    def news_watch(self, live: dict, orders: list) -> None:
        n = self.cfg["news"]
        if not n.get("enabled") or not live:
            return
        self.news_score(list(live))
        for s in live:
            score, k = news_window(self.news, s, self.now, n["lookback_hours"])
            if k >= 3 and score <= n["emergency_sell_below"]:
                self.sell(s, f"uscita d'emergenza: notizie molto negative ({score:+.2f} su {k})", orders)

    # --------------------------------------------------------------- giro
    def run(self) -> None:
        self.account()
        print(f"Capitale {self.equity:,.2f} $ | massimo {self.st['peak_equity']:,.2f} $")
        if self.kill_switch():
            return
        live = self.positions()
        self.reconcile(live)
        cal = self.tc.get_calendar(GetCalendarRequest(start=self.today, end=self.today))
        session = stock_session(self.now, trading_day=bool(cal))
        if session != "regular":
            print(f"Borsa non in seduta regolare ({session}): nessuna azione.")
            return
        if self.st.get("last_daily") != self.today.isoformat():
            self.daily(live)
            time.sleep(5)
            self.reconcile(self.positions())
        else:
            self.news_watch(live, self.open_orders())
        self.ensure_stops()


def main() -> None:
    bot = Bot()
    try:
        bot.run()
    except Exception:
        traceback.print_exc()
        append_csv("errori.csv", ["ora_utc", "errore"],
                   [bot.now.strftime("%Y-%m-%d %H:%M"), traceback.format_exc(limit=3).replace("\n", " | ")])
    finally:
        save_state(bot.st)


if __name__ == "__main__":
    main()
