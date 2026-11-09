# Alpaca Test Trading – bot di trading simulato

Bot che opera **solo sul conto Paper** di Alpaca ("Test Trading") con una strategia
*momentum* aggressiva su azioni USA liquide, ETF (anche a leva) e cripto.
Gira da solo su GitHub Actions: nessun computer deve restare acceso.

> Progetto sperimentale e didattico. Non è una consulenza finanziaria.

## Come funziona

| Quando | Cosa succede |
|---|---|
| Ogni 15 minuti | `tbot/live.py`: legge prezzi e notizie, gestisce le posizioni, apre nuove operazioni |
| Ogni sera alle 22:30 (ora italiana) | `tbot/report.py`: report del giorno in `report/ultimo.md` |
| Su richiesta | `tbot/backtest.py`: prova la strategia sugli anni passati, risultati in `backtest/risultati.md` |

**Strategia (dettagli e soglie in `config.yaml`):**
1. *Regime di mercato*: se l'S&P 500 è sopra la sua media a 50 giorni il bot compra azioni ed ETF al rialzo;
   se è sotto usa solo ETF al ribasso (SQQQ, SOXS…). Per le cripto vale lo stesso con Bitcoin.
2. *Ingresso*: tendenza giornaliera al rialzo + rottura del massimo delle ultime 20 barre da 15 minuti
   + RSI tra 50 e 78 + volume sopra la media + notizie Benzinga non negative.
   Si scelgono i candidati più forti del momento.
3. *Uscita*: stop-loss a 2 ATR, take-profit a 4 ATR (azioni: ordini *bracket* che restano sul broker),
   stop a pareggio dopo +1,5 ATR, chiusura dopo 5 giorni o se la tendenza giornaliera si rompe.
4. *Rischio*: 1,5% del capitale per operazione, max 20% per posizione, max 8 posizioni,
   stop ai nuovi ingressi dopo −5% nel giorno, **chiusura totale e blocco a −20% dal massimo**.

## Configurazione iniziale (una volta sola)

1. Dalla dashboard Alpaca (conto Paper "Test Trading") → **API Keys** → genera la coppia di chiavi.
2. Qui su GitHub: **Settings → Secrets and variables → Actions → New repository secret**, e crea:
   - `ALPACA_API_KEY` = la "API Key ID"
   - `ALPACA_SECRET_KEY` = la "Secret Key"
3. **Actions → Backtest → Run workflow** per vedere i risultati storici.
4. Per attivare il bot: in `.github/workflows/trade.yml` togli il `#` dalle righe `schedule`.

## Comandi utili

- **Fermare tutto subito**: `trading_enabled: false` in `config.yaml` (il bot gira ma non invia ordini),
  oppure *Actions → Bot trading → ⋯ → Disable workflow*.
- **Togliere le cripto**: `crypto_enabled: false`.
- **Riattivare dopo un blocco per drawdown**: `risk.halt_reset: true`, attendi un giro, poi rimetti `false`.

## Dove leggere i risultati

- `report/ultimo.md` – report dell'ultima sera · `report/giornalieri/` – archivio
- `report/riepilogo_settimana.md` – riepilogo usato per la revisione settimanale
- `log/operazioni.csv` – operazioni chiuse con P&L · `log/azioni.csv` – ogni decisione con il motivo
- `log/capitale.csv` – andamento del capitale · `log/errori.csv` – eventuali errori

## Limiti noti (per leggere i risultati con onestà)

- **Dati gratuiti**: in tempo reale arrivano solo da IEX (una borsa), lo storico da tutte le borse.
- **Notte (20:00–04:00 ET)**: senza abbonamento a pagamento non ci sono dati sulle azioni, quindi il bot
  non apre posizioni azionarie fuori dalla seduta regolare. Notti e weekend sono coperti dalle cripto.
- **Esecuzioni del Paper ottimistiche**: niente slippage reale ed esecuzioni sempre piene.
  Il backtest aggiunge slippage e commissioni per compensare.
- **GitHub Actions** può avviare le esecuzioni con qualche minuto di ritardo.
- I "titoli ospiti" (i più attivi del giorno) non sono inclusi nel backtest.
