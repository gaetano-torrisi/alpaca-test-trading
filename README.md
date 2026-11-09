# Alpaca Test Trading – bot di trading simulato

Bot che opera **solo sul conto Paper** di Alpaca ("Test Trading", capitale 1.000 $) con una strategia
**momentum giornaliera**: tiene i titoli/ETF più forti delle ultime settimane, li cambia una volta alla
settimana, protegge ogni posizione con uno stop che sale e si mette al riparo quando il mercato scende.
Gira da solo su GitHub Actions: nessun computer deve restare acceso.

> Progetto sperimentale e didattico. Non è una consulenza finanziaria.

## La strategia in uso: Nasdaq ×3 con semaforo (`config.yaml`)

1. **Semaforo**, controllato ogni giorno: VERDE se il Nasdaq 100 (QQQ) chiude sopra la media degli ultimi
   200 giorni, ROSSO se chiude sotto.
2. **VERDE** → tutto il capitale su **TQQQ** (ETF che replica il Nasdaq 100 ×3).
3. **ROSSO** → vende TQQQ il giorno dopo e passa al titolo difensivo più forte tra TLT, IEF e GLD
   (se nessuno è in tendenza positiva resta in liquidità).
4. Niente stop stretti: la protezione è il semaforo. Freno d'emergenza solo a −70% dal massimo.
5. Notizie: blocco acquisti e uscita d'emergenza in caso di raffica di notizie molto negative (non incluse nel backtest).
6. Frazioni di azione: si investe un importo in dollari (capitale del test: 1.000 $).

**Backtest 10/2016–11/2026** (`backtest/risultati.md`): circa +34,7% l'anno contro +14,6% dell'S&P 500,
ma con perdite massime fino al −62% (crollo Covid 2020) e −46% (2022). Strategia volutamente aggressiva.

Il motore supporta anche la rotazione momentum su più ETF/azioni (vedi varianti in `config.yaml`).

## Secondo conto: "Test Tech" (`config_tech.yaml`)

Stesso semaforo sul Nasdaq, ma invece di TQQQ il bot tiene **le 5 aziende tecnologiche più forti**
(20% del capitale ciascuna) scelte ogni settimana tra le ~33 maggiori tecnologiche USA del 2026.
Con semaforo ROSSO passa ai difensivi (TLT, IEF, GLD) o resta in liquidità.
Backtest 2016–2026 con l'elenco *del 2016*: circa +26% l'anno, perdita massima −32%.
Registri separati in `log/tech/`, `state/tech/`, `report/tech/`. Chiavi: secrets `ALPACA_TECH_API_KEY` e
`ALPACA_TECH_SECRET_KEY`. Per fermarlo: *Actions → Bot Test Tech → Disable workflow*.

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
