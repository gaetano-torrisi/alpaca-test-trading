# Confronto varianti  (01/11/2024 – 09/11/2026)

Costi inclusi (slippage e commissioni). Interruttore -20% solo annotato, per vedere l'intero periodo. Periodo A = fino al 01/01/2026, periodo B = dopo (verifica su dati 'nuovi').

| Variante | Rend. totale % | Perdita max % | Sharpe | Operazioni | Vincenti % | Profit factor | Rend. A % | Rend. B % | Interruttore scatterebbe |
|---|---|---|---|---|---|---|---|---|---|
| base | -47.37 | 54.74 | -1.01 | 3,227 | 27.9 | 0.89 | -34.2 | -20.02 | 21/03/2025 |
| solo_azioni | -7.99 | 25.93 | -0.09 | 2,600 | 28.2 | 0.98 | 1.43 | -9.29 | 23/02/2026 |
| solo_azioni_senza_notizie | -11.91 | 30.17 | -0.17 | 2,693 | 28.1 | 0.97 | 0.19 | -12.08 | 02/12/2025 |
| solo_azioni_stop_larghi | -1.58 | 27.22 | 0.07 | 2,105 | 25.2 | 1.0 | 4.16 | -5.51 | 02/09/2025 |
| solo_azioni_lascia_correre | 16.94 | 23.58 | 0.38 | 2,110 | 16.0 | 1.04 | 18.41 | -1.24 | 01/10/2026 |

Confronto: SPY compra-e-tieni 31.74% (perdita massima 18.75%).

## Dettaglio per variante

### base

Modifiche: `nessuna`

| Classe | Operazioni | P&L ($) | Vincenti (%) |
|---|---|---|---|
| crypto | 493 | -65,852 | 25 |
| inverse | 82 | 8,067 | 28 |
| leveraged_long | 269 | 7,778 | 28 |
| stock | 2383 | 2,633 | 28 |

### solo_azioni

Modifiche: `{'crypto_enabled': False, 'universe.leveraged_long': [], 'universe.inverse': []}`

| Classe | Operazioni | P&L ($) | Vincenti (%) |
|---|---|---|---|
| stock | 2600 | -7,988 | 28 |

### solo_azioni_senza_notizie

Modifiche: `{'crypto_enabled': False, 'universe.leveraged_long': [], 'universe.inverse': [], 'entry.news_min_score': -1.0}`

| Classe | Operazioni | P&L ($) | Vincenti (%) |
|---|---|---|---|
| stock | 2693 | -11,912 | 28 |

### solo_azioni_stop_larghi

Modifiche: `{'crypto_enabled': False, 'universe.leveraged_long': [], 'universe.inverse': [], 'exit.stop_atr': 3.0, 'exit.target_atr': 6.0}`

| Classe | Operazioni | P&L ($) | Vincenti (%) |
|---|---|---|---|
| stock | 2105 | -1,580 | 25 |

### solo_azioni_lascia_correre

Modifiche: `{'crypto_enabled': False, 'universe.leveraged_long': [], 'universe.inverse': [], 'exit.target_atr': 8.0, 'exit.max_hold_days': 10}`

| Classe | Operazioni | P&L ($) | Vincenti (%) |
|---|---|---|---|
| stock | 2110 | 16,942 | 16 |

