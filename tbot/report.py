"""Report giornaliero (sera, dopo la chiusura USA) e riepilogo per la revisione settimanale."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
from alpaca.trading.client import TradingClient

from .common import ET, ROOT, api_keys, load_config
from .market import TFD, Market, utcnow

LOG, REP = ROOT / "log", ROOT / "report"


def read(name: str) -> pd.DataFrame:
    p = LOG / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def main() -> None:
    cfg = load_config()
    key, secret = api_keys()
    tc, mk = TradingClient(key, secret, paper=True), Market(key, secret)
    now = utcnow()
    today = now.astimezone(ET).date()
    acc = tc.get_account()
    eq, prev = float(acc.equity), float(acc.last_equity or acc.equity)
    positions = tc.get_all_positions()

    cap = read("capitale.csv")
    start_eq = float(cap["capitale"].iloc[0]) if len(cap) else eq
    peak = max(cap["capitale"].max(), eq) if len(cap) else eq
    ops = read("operazioni.csv")
    if len(ops):
        ops["uscita"] = pd.to_datetime(ops["uscita_utc"], utc=True)

    spy_txt = ""
    try:
        d = mk.stock_bars(["SPY"], TFD, now - timedelta(days=10), now - timedelta(minutes=20), "sip")["SPY"]
        spy_txt = f"{(d['close'].iloc[-1] / d['close'].iloc[-2] - 1) * 100:+.2f}%"
    except Exception:
        spy_txt = "n.d."

    day_ops = ops[ops["uscita"].dt.tz_convert(ET).dt.date == today] if len(ops) else ops
    lines = [f"# Report del {today:%d/%m/%Y}", "",
             "| | |", "|---|---|",
             f"| Capitale | {eq:,.2f} $ |",
             f"| Variazione di oggi | {eq - prev:+,.2f} $ ({(eq / prev - 1) * 100:+.2f}%) |",
             f"| S&P 500 (SPY) oggi | {spy_txt} |",
             f"| Dall'inizio del test | {(eq / start_eq - 1) * 100:+.2f}% |",
             f"| Distanza dal massimo | {(eq / peak - 1) * 100:.2f}% |", "",
             f"## Posizioni aperte ({len(positions)})", ""]
    if positions:
        lines += ["| Titolo | Quantità | Prezzo medio | Prezzo attuale | P&L |", "|---|---|---|---|---|"]
        for p in positions:
            lines.append(f"| {p.symbol} | {float(p.qty):g} | {float(p.avg_entry_price):.2f} | "
                         f"{float(p.current_price):.2f} | {float(p.unrealized_pl):+,.2f} $ ({float(p.unrealized_plpc) * 100:+.1f}%) |")
    else:
        lines.append("Nessuna.")
    lines += ["", f"## Operazioni chiuse oggi ({len(day_ops)})", ""]
    if len(day_ops):
        lines += ["| Titolo | P&L | % | Motivo |", "|---|---|---|---|"]
        for _, o in day_ops.iterrows():
            lines.append(f"| {o.simbolo} | {o.pnl_usd:+,.2f} $ | {o.pnl_pct:+.2f}% | {o.motivo_uscita} |")
    else:
        lines.append("Nessuna.")
    err = read("errori.csv")
    if len(err):
        e_today = err[err["ora_utc"].str[:10] == now.strftime("%Y-%m-%d")]
        if len(e_today):
            lines += ["", f"**Errori oggi: {len(e_today)}** (dettagli in log/errori.csv)"]

    REP.mkdir(exist_ok=True)
    (REP / "giornalieri").mkdir(exist_ok=True)
    text = "\n".join(lines) + "\n"
    (REP / "giornalieri" / f"{today}.md").write_text(text, encoding="utf-8")
    (REP / "ultimo.md").write_text(text, encoding="utf-8")
    weekly_summary(ops, cap, eq)
    print(text)


def weekly_summary(ops: pd.DataFrame, cap: pd.DataFrame, eq: float) -> None:
    """Riepilogo compatto degli ultimi 7 giorni: è il file letto nella revisione settimanale."""
    since = pd.Timestamp(utcnow() - timedelta(days=7))
    lines = ["# Riepilogo ultimi 7 giorni", ""]
    if len(cap):
        c = cap.copy()
        c["t"] = pd.to_datetime(c["ora_utc"], utc=True)
        w = c[c["t"] >= since]
        if len(w):
            first = float(w["capitale"].iloc[0])
            lines.append(f"Capitale: {first:,.0f} $ → {eq:,.0f} $ ({(eq / first - 1) * 100:+.2f}%), "
                         f"minimo {w['capitale'].min():,.0f} $, massimo {w['capitale'].max():,.0f} $")
    if len(ops):
        w = ops[ops["uscita"] >= since]
        lines.append(f"Operazioni chiuse: {len(w)}")
        if len(w):
            win = w[w.pnl_usd > 0]
            lines += [f"Vincenti: {len(win)} ({len(win) / len(w) * 100:.0f}%), P&L totale {w.pnl_usd.sum():+,.0f} $", "",
                      "| Motivo uscita | N | P&L $ |", "|---|---|---|"]
            for k, g in w.groupby("motivo_uscita"):
                lines.append(f"| {k} | {len(g)} | {g.pnl_usd.sum():+,.0f} |")
            lines += ["", "| Titolo | N | P&L $ |", "|---|---|---|"]
            for k, g in w.groupby("simbolo"):
                lines.append(f"| {k} | {len(g)} | {g.pnl_usd.sum():+,.0f} |")
    (REP / "riepilogo_settimana.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
