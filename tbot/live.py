"""Esecuzione reale sul conto Paper. Avviato da GitHub Actions ogni 15 minuti.

Ogni esecuzione:
 1. legge il conto e controlla i limiti di rischio (interruttore di sicurezza);
 2. riconcilia le posizioni (registra le operazioni chiuse da stop/take-profit);
 3. gestisce le posizioni aperte (uscite, stop a pareggio);
 4. cerca nuovi ingressi e invia gli ordini;
 5. salva registri e stato nel repository.
"""
from __future__ import annotations

import csv
import json
import traceback
from datetime import datetime, timedelta

import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (GetCalendarRequest, GetOrdersRequest, MarketOrderRequest,
                                     ReplaceOrderRequest, StopLossRequest, TakeProfitRequest)

from .common import ET, ROOT, all_stock_symbols, api_keys, is_crypto, load_config, stock_session, symbol_class, to_pair, universe
from .indicators import add_daily, add_intraday, last_closed
from .market import TF15, TFD, Market, news_window, utcnow
from .strategy import evaluate_entry, manage_position, position_size, regime_on

STATE = ROOT / "state" / "state.json"
LOG = ROOT / "log"


# ------------------------------------------------------------ utilità file
def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"peak_equity": None, "halted": False, "positions": {}, "guests": {"date": None, "symbols": []}}


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


def action(kind: str, symbol: str, qty, price, reason: str) -> None:
    ts = utcnow().astimezone(ET).strftime("%Y-%m-%d %H:%M ET")
    print(f"{ts} {kind:<12} {symbol:<9} qty={qty} prezzo={price} | {reason}")
    append_csv("azioni.csv", ["ora", "azione", "simbolo", "quantita", "prezzo", "motivo"],
               [ts, kind, symbol, qty, price, reason])


def px(p: float) -> float:
    return round(p, 2) if p >= 1 else round(p, 4)


def fnum(x) -> float:
    return float(x) if x is not None else 0.0


# ----------------------------------------------------------------- bot
class Bot:
    def __init__(self):
        self.cfg = load_config()
        key, secret = api_keys()
        self.tc = TradingClient(key, secret, paper=True)
        self.mk = Market(key, secret)
        self.st = load_state()
        self.now = utcnow()

    # ---------------------------------------------------------- conto
    def account(self):
        a = self.tc.get_account()
        self.equity = fnum(a.equity)
        self.last_equity = fnum(a.last_equity) or self.equity
        self.st["peak_equity"] = max(self.st.get("peak_equity") or self.equity, self.equity)
        append_csv("capitale.csv", ["ora_utc", "capitale", "liquidita", "esposizione_long"],
                   [self.now.strftime("%Y-%m-%d %H:%M"), round(self.equity, 2), a.cash, a.long_market_value])

    def positions(self) -> dict[str, dict]:
        out = {}
        for p in self.tc.get_all_positions():
            sym = to_pair(p.symbol) if p.asset_class == AssetClass.CRYPTO else p.symbol
            out[sym] = {"qty": fnum(p.qty), "avg": fnum(p.avg_entry_price), "value": abs(fnum(p.market_value)),
                        "price": fnum(p.current_price)}
        return out

    def open_orders(self) -> list:
        return self.tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=False, limit=500))

    # --------------------------------------------------- sicurezza
    def kill_switch(self) -> bool:
        r = self.cfg["risk"]
        if r.get("halt_reset"):
            self.st["halted"] = False
            self.st["peak_equity"] = self.equity
        if self.st.get("halted"):
            print("Bot FERMO per drawdown massimo. Per riattivarlo: risk.halt_reset: true in config.yaml")
            return True
        dd = 1 - self.equity / self.st["peak_equity"]
        if dd >= r["max_drawdown_halt"]:
            self.tc.close_all_positions(cancel_orders=True)
            self.st["halted"] = True
            self.st["positions"] = {}
            action("HALT", "-", "-", "-", f"drawdown {dd:.1%} >= {r['max_drawdown_halt']:.0%}: chiuso tutto")
            return True
        return False

    # ----------------------------------------------- riconciliazione
    def reconcile(self, live: dict[str, dict]) -> None:
        tracked = self.st["positions"]
        gone = [s for s in tracked if s not in live]
        if gone:
            after = min(datetime.fromisoformat(tracked[s]["entry_time"]) for s in gone) - timedelta(minutes=5)
            closed = self.tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after,
                                                         nested=False, limit=500))
            for s in gone:
                pos = tracked.pop(s)
                sells = [o for o in closed if o.side == OrderSide.SELL and o.filled_at is not None
                         and (o.symbol == s or to_pair(o.symbol) == s)]
                o = max(sells, key=lambda o: o.filled_at) if sells else None
                exit_p = fnum(o.filled_avg_price) if o else pos["entry"]
                kind = str(getattr(o, "order_type", None) or getattr(o, "type", "")).lower() if o else ""
                reason = pos.get("exit_reason") or ("stop-loss" if "stop" in kind else
                                                     "take-profit" if "limit" in kind else "chiusura")
                pnl = (exit_p - pos["entry"]) * pos["qty"]
                append_csv("operazioni.csv",
                           ["simbolo", "ingresso_utc", "uscita_utc", "quantita", "prezzo_ingresso",
                            "prezzo_uscita", "pnl_usd", "pnl_pct", "motivo_uscita", "motivo_ingresso"],
                           [s, pos["entry_time"][:16], (o.filled_at if o else self.now).strftime("%Y-%m-%d %H:%M"),
                            pos["qty"], px(pos["entry"]), px(exit_p), round(pnl, 2),
                            round((exit_p / pos["entry"] - 1) * 100, 2), reason, pos.get("reason", "")])
                action("CHIUSA", s, pos["qty"], px(exit_p), f"{reason}, P&L {pnl:+.2f} $")
        for s, p in live.items():
            if s not in tracked:  # posizione aperta a mano o non registrata
                tracked[s] = {"entry": p["avg"], "qty": p["qty"], "stop": p["avg"] * 0.95, "target": p["avg"] * 1.10,
                              "atr": p["avg"] * 0.01, "entry_time": self.now.isoformat(), "bracket": False,
                              "reason": "posizione trovata sul conto"}
            else:  # aggiorna prezzo e quantità effettivi di esecuzione
                tracked[s]["entry"] = p["avg"] or tracked[s]["entry"]
                tracked[s]["qty"] = p["qty"]

    # ---------------------------------------------------------- dati
    def load_data(self, session: str) -> None:
        cfg, u = self.cfg, universe(self.cfg)
        e, x = cfg["entry"], cfg["exit"]
        held = list(self.st["positions"])
        stocks = []
        if session == "regular":
            stocks = all_stock_symbols(cfg) + self.st["guests"]["symbols"]
        stocks = list(dict.fromkeys(stocks + [s for s in held if not is_crypto(s)] + [cfg["regime"]["stock_benchmark"]]))
        cryptos = list(dict.fromkeys(u["crypto"] + [s for s in held if is_crypto(s)]
                                     + ([cfg["regime"]["crypto_benchmark"]] if u["crypto"] else [])))
        self.intra, self.daily = {}, {}
        start_i, start_d = self.now - timedelta(days=10), self.now - timedelta(days=150)
        if stocks:
            for s, df in self.mk.stock_bars(stocks, TF15, start_i, None, cfg["data"]["live_feed"], rth_only=True).items():
                self.intra[s] = add_intraday(df, e["breakout_bars"], x["atr_period"])
            for s, df in self.mk.stock_bars(stocks, TFD, start_d, self.now - timedelta(minutes=20), "sip").items():
                self.daily[s] = add_daily(df, e["daily_ema_fast"], e["daily_ema_slow"], cfg["regime"]["ema_days"], False)
        if cryptos:
            for s, df in self.mk.crypto_bars(cryptos, TF15, start_i, None).items():
                self.intra[s] = add_intraday(df, e["breakout_bars"], x["atr_period"])
            for s, df in self.mk.crypto_bars(cryptos, TFD, start_d, None).items():
                self.daily[s] = add_daily(df, e["daily_ema_fast"], e["daily_ema_slow"], cfg["regime"]["ema_days"], True)
        cands = [s for s in stocks + cryptos if s not in held]
        try:
            self.news = self.mk.news(cands + held, self.now - timedelta(hours=cfg["data"]["news_lookback_hours"]))
        except Exception as exc:
            print(f"[avviso] notizie non disponibili: {exc}")
            self.news = pd.DataFrame(columns=["time", "symbol", "score", "headline"])

    def last_bar(self, s: str) -> pd.Series | None:
        """Ultima barra da 15 min COMPLETATA e recente (max 45 min)."""
        df = self.intra.get(s)
        if df is None or df.empty:
            return None
        done = df[df.index <= self.now - timedelta(minutes=15)]
        if done.empty or self.now - done.index[-1] > timedelta(minutes=45):
            return None
        return done.iloc[-1]

    # ------------------------------------------------------ uscite
    def close(self, s: str, reason: str, orders: list) -> None:
        pos = self.st["positions"][s]
        if not self.cfg.get("trading_enabled", True):
            action("(sim) VENDI", s, pos["qty"], "-", reason)
            return
        for o in orders:
            if o.symbol == s or to_pair(o.symbol) == s:
                try:
                    self.tc.cancel_order_by_id(o.id)
                except Exception:
                    pass
        self.tc.close_position(s.replace("/", "") if is_crypto(s) else s)
        pos["exit_reason"] = reason
        action("VENDI", s, pos["qty"], "mercato", reason)

    def manage(self, stock_open: bool, orders: list) -> None:
        for s, pos in list(self.st["positions"].items()):
            if not is_crypto(s) and not stock_open:
                continue  # azioni: si interviene solo a mercato aperto
            bar = self.last_bar(s)
            p = {**pos, "entry_time": datetime.fromisoformat(pos["entry_time"])}
            reason, new_stop = manage_position(p, bar, last_closed(self.daily.get(s), self.now), self.now, self.cfg)
            if reason is None and bar is not None and not pos.get("bracket"):
                if bar["close"] <= pos["stop"]:
                    reason = "stop-loss"
                elif bar["close"] >= pos["target"]:
                    reason = "take-profit"
            if reason:
                self.close(s, reason, orders)
                continue
            if new_stop is not None:
                if pos.get("bracket"):
                    legs = [o for o in orders if o.symbol == s and o.side == OrderSide.SELL and o.stop_price is not None]
                    for o in legs:
                        try:
                            self.tc.replace_order_by_id(o.id, ReplaceOrderRequest(stop_price=px(new_stop)))
                        except Exception as exc:
                            print(f"[avviso] stop non aggiornato per {s}: {exc}")
                            new_stop = None
                if new_stop is not None:
                    pos["stop"] = new_stop
                    action("STOP->PAREGGIO", s, pos["qty"], px(new_stop), "guadagno > 1,5 ATR")

    # ----------------------------------------------------- ingressi
    def enter(self, stock_open: bool, live: dict, orders: list) -> None:
        cfg, r = self.cfg, self.cfg["risk"]
        if self.equity < self.last_equity * (1 - r["daily_loss_limit"]):
            print("Limite di perdita giornaliera raggiunto: nessun nuovo ingresso oggi.")
            return
        stock_on = regime_on(last_closed(self.daily.get(cfg["regime"]["stock_benchmark"]), self.now))
        crypto_on = regime_on(last_closed(self.daily.get(cfg["regime"]["crypto_benchmark"]), self.now))
        print(f"Regime: azioni {'RIALZO' if stock_on else 'RIBASSO'} | cripto {'RIALZO' if crypto_on else 'RIBASSO'}")
        pending = {o.symbol for o in orders} | {to_pair(o.symbol) for o in orders}
        u = universe(cfg)
        pool = (all_stock_symbols(cfg) + self.st["guests"]["symbols"] if stock_open else []) + u["crypto"]
        cands = []
        for s in dict.fromkeys(pool):
            if s in live or s in pending or s in self.st["positions"]:
                continue
            bar = self.last_bar(s)
            if bar is None:
                continue
            c = evaluate_entry(s, symbol_class(s, cfg), bar, last_closed(self.daily.get(s), self.now),
                               news_window(self.news, s, self.now, cfg["data"]["news_lookback_hours"]),
                               stock_on, crypto_on, cfg)
            if c:
                cands.append(c)
        cands.sort(key=lambda c: c.score, reverse=True)
        n_pos = len(self.st["positions"])
        n_crypto = sum(is_crypto(s) for s in self.st["positions"])
        exposure = sum(p["value"] for p in live.values())
        done = 0
        for c in cands:
            if done >= cfg["entry"]["max_new_per_run"] or n_pos >= r["max_positions"]:
                break
            if c.cls == "crypto" and n_crypto >= r["max_crypto_positions"]:
                continue
            qty = position_size(c, self.equity, exposure, cfg)
            if qty <= 0:
                continue
            if not cfg.get("trading_enabled", True):
                action("(sim) COMPRA", c.symbol, qty, px(c.price), c.reason)
                continue
            try:
                if c.cls == "crypto":
                    req = MarketOrderRequest(symbol=c.symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.GTC)
                else:
                    req = MarketOrderRequest(symbol=c.symbol, qty=qty, side=OrderSide.BUY,
                                             time_in_force=TimeInForce.GTC, order_class=OrderClass.BRACKET,
                                             take_profit=TakeProfitRequest(limit_price=px(c.target)),
                                             stop_loss=StopLossRequest(stop_price=px(c.stop)))
                self.tc.submit_order(req)
            except Exception as exc:
                print(f"[avviso] ordine rifiutato per {c.symbol}: {exc}")
                continue
            self.st["positions"][c.symbol] = {
                "entry": c.price, "qty": qty, "stop": c.stop, "target": c.target, "atr": c.atr,
                "entry_time": self.now.isoformat(), "bracket": c.cls != "crypto", "reason": c.reason}
            action("COMPRA", c.symbol, qty, px(c.price),
                   f"{c.reason} | stop {px(c.stop)} target {px(c.target)}")
            n_pos += 1
            n_crypto += c.cls == "crypto"
            exposure += qty * c.price
            done += 1
        if not cands:
            print("Nessun segnale di ingresso in questo giro.")

    # ------------------------------------------------- titoli ospiti
    def refresh_guests(self) -> None:
        today = self.now.astimezone(ET).date().isoformat()
        if not self.cfg.get("dynamic_guests") or self.st["guests"]["date"] == today:
            return
        base = set(all_stock_symbols(self.cfg))
        cands = [s for s in self.mk.most_actives(30) if s not in base and s.isalpha()]
        guests = []
        if cands:
            daily = self.mk.stock_bars(cands, TFD, self.now - timedelta(days=40), self.now - timedelta(minutes=20), "sip")
            for s in cands:
                d = daily.get(s)
                if d is None or len(d) < 20:
                    continue
                last = d.iloc[-1]
                dollar_vol = (d["close"] * d["volume"]).tail(20).mean()
                if last["close"] >= 10 and dollar_vol >= 200e6:  # niente penny stock, solo titoli liquidi
                    guests.append(s)
        self.st["guests"] = {"date": today, "symbols": guests[:10]}
        print(f"Titoli ospiti di oggi: {guests[:10] or 'nessuno'}")

    # --------------------------------------------------------- giro
    def run(self) -> None:
        self.account()
        print(f"Capitale {self.equity:,.2f} $ | massimo {self.st['peak_equity']:,.2f} $ | "
              f"ieri {self.last_equity:,.2f} $")
        if self.kill_switch():
            return
        live = self.positions()
        self.reconcile(live)
        cal = self.tc.get_calendar(GetCalendarRequest(start=self.now.astimezone(ET).date(),
                                                      end=self.now.astimezone(ET).date()))
        session = stock_session(self.now, trading_day=bool(cal))
        stock_open = session == "regular"
        print(f"Sessione azioni: {session}")
        if stock_open:
            self.refresh_guests()
        if not stock_open and not universe(self.cfg)["crypto"] and not any(is_crypto(s) for s in live):
            print("Mercato azionario non in seduta regolare e cripto disattivate: niente da fare.")
            return
        self.load_data(session)
        orders = self.open_orders()
        self.manage(stock_open, orders)
        self.enter(stock_open, self.positions(), self.open_orders())


def main() -> None:
    bot = Bot()
    try:
        bot.run()
    except Exception:
        traceback.print_exc()
        append_csv("errori.csv", ["ora_utc", "errore"], [bot.now.strftime("%Y-%m-%d %H:%M"),
                                                         traceback.format_exc(limit=3).replace("\n", " | ")])
    finally:
        save_state(bot.st)


if __name__ == "__main__":
    main()
