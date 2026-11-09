# Alpaca Test Trading – bot di trading simulato

Bot che opera **solo sul conto Paper** di Alpaca ("Test Trading", capitale 1.000 $) con una strategia
**momentum giornaliera**: tiene i titoli/ETF più forti delle ultime settimane, li cambia una volta alla
settimana, protegge ogni posizione con uno stop che sale e si mette al riparo quando il mercato scende.
Gira da solo su GitHub Actions: nessun computer deve restare acceso.

> Progetto sperimentale e didattico. Non è una consulenza finanziaria.

## La strategia in breve (dettagli e soglie in `config.yaml`)

1. **Semaforo**: VERDE se l'S&P 500 (SPY) chiude sopra la media degli ultimi 200 giorni. Con il ROSSO
   si vendono azioni ed ETF a rischio e si possono tenere solo titoli difensivi (TLT, IEF, GLD).
2. **Classifica** (primo giorno di borsa di ogni settimana): forza = media dei rendimenti a 3 e 6 mesi,
   esclusa l'ultima settimana. Si tengono i primi 4; un titolo già in portafoglio resta finché è nei primi 8.
3. **Stop che sale**: massima chiusura dall'acquisto meno 3 volte l'oscillazione media giornaliera (ATR).
   Non scende mai. Ogni mattina viene piazzato sul broker come ordine stop.
4. **Notizie**: non compra titoli con notizie molto negative; vende d'urgenza in caso di raffica di notizie
   molto negative (solo nel bot reale, non verificabile nel backtest).
5. **Frazioni di azione**: con 1.000 $ si comprano importi (es. 250 $ di un ETF), non azioni intere.
6. **Blocco di sicurezza**: a −35% dal massimo chiude tutto e si ferma.

## Come funziona

| Quando | Cosa succede |
|---|---|
| Ogni 15 min, lun–ven, 15:30–22:00 ora italiana | `tbot/live.py`: il primo giro del giorno applica semaforo, classifica e stop; i successivi sorvegliano stop e notizie |
| Ogni sera alle 22:30 | `tbot/report.py`: report del giorno in `report/ultimo.md` |
| Su richiesta | `tbot/backtest.py`: prova le varianti dal 2016 a oggi, risultati in `backtest/risultati.md` |

## Configurazione iniziale (una volta sola)

1. Chiavi API del conto Paper nei *Secrets* del repository: `ALPACA_API_KEY` e `ALPACA_SECRET_KEY`.
2. **Actions → Backtest → Run workflow** per vedere i risultati storici.
3. Per attivare il bot: in `.github/workflows/trade.yml` togli il `#` dalle righe `schedule`.

## Comandi utili

- **Fermare gli ordini**: `trading_enabled: false` in `config.yaml`, oppure *Actions → Bot trading → Disable workflow*.
- **Riattivare dopo un blocco**: `risk.halt_reset: true`, attendi un giro, poi rimetti `false`.

## Dove leggere i risultati

- `report/ultimo.md`, `report/giornalieri/`, `report/riepilogo_settimana.md`
- `log/operazioni.csv` (operazioni chiuse con P&L), `log/azioni.csv` (ogni decisione con il motivo),
  `log/capitale.csv`, `log/errori.csv`

## Limiti noti

- Il backtest usa prezzi di apertura/chiusura giornalieri e un costo stimato di 5 punti base per operazione.
- L'elenco delle azioni singole è scelto oggi: nel backtest favorisce i titoli che sappiamo essere andati bene
  (distorsione da "senno di poi"). Le varianti solo-ETF non hanno questo problema.
- Il filtro notizie non è incluso nel backtest.
- La prima versione (intraday a 15 minuti) è in `legacy/`: il backtest l'ha bocciata.
