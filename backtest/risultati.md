# Backtest momentum giornaliero  (18/10/2016 – 07/11/2026)

Capitale iniziale 1,000 $. Costi: 5 punti base per operazione. Periodo A = fino al 01/01/2022 (scelta), periodo B = dopo (verifica).

## Riepilogo

| Variante | Capitale finale $ | Rend. annuo % | Perdita max % | Sharpe | Annuo A % | Annuo B % | Operazioni |
|---|---|---|---|---|---|---|---|
| spy_compra_e_tieni | 3,925 | 14.6 | 33.4 | 0.87 | 18.2 | 10.7 | 1 |
| spy_con_semaforo | 2,793 | 10.8 | 16.6 | 0.94 | 13.7 | 7.6 | 17 |
| etf_rotazione | 1,695 | 5.4 | 18.8 | 0.45 | 6.6 | 4.1 | 463 |
| etf_aggressiva | 1,493 | 4.1 | 51.6 | 0.28 | 7.4 | 0.3 | 490 |
| etf_aggressiva_top3 | 1,447 | 3.7 | 53.3 | 0.28 | 6.3 | 0.7 | 371 |
| azioni_etf_leva | 7,717 | 22.5 | 49.1 | 0.81 | 37.1 | 8.3 | 710 |

## Rendimento anno per anno (%)

| Variante | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| spy_compra_e_tieni | +4.4 | +21.3 | -4.9 | +30.6 | +18.2 | +28.3 | -18.0 | +25.9 | +24.7 | +17.6 | +8.6 |
| spy_con_semaforo | +4.4 | +21.3 | -4.3 | +12.4 | +11.6 | +28.1 | -10.7 | +10.0 | +24.4 | +11.3 | +5.4 |
| etf_rotazione | +6.1 | +10.7 | +1.8 | -4.2 | +14.5 | +6.5 | -4.4 | +5.9 | +4.3 | +20.7 | -4.9 |
| etf_aggressiva | +8.8 | +4.3 | +3.4 | +1.5 | +52.1 | -20.1 | -7.9 | +5.0 | +8.0 | +0.0 | -1.2 |
| etf_aggressiva_top3 | +12.2 | +4.8 | +1.0 | +2.5 | +45.2 | -22.2 | -10.7 | +10.3 | +7.7 | -10.8 | +11.3 |
| azioni_etf_leva | +16.3 | +30.4 | +24.0 | +13.6 | +138.8 | +1.1 | -11.5 | +42.8 | +9.0 | -1.2 | +10.0 |

## Nei momenti difficili (perdita massima nel periodo, %)

| Variante | Crollo Covid (feb–mar 2020) | Anno 2022 | Calo apr 2025 |
|---|---|---|---|
| spy_compra_e_tieni | 33.4 | 24.3 | 18.6 |
| spy_con_semaforo | 14.5 | 11.3 | 8.7 |
| etf_rotazione | 8.2 | 9.1 | 6.4 |
| etf_aggressiva | 12.7 | 14.1 | 6.4 |
| etf_aggressiva_top3 | 15.4 | 15.7 | 5.6 |
| azioni_etf_leva | 15.1 | 15.4 | 23.3 |

## Dettaglio operazioni per variante

**spy_compra_e_tieni**: 1 operazioni, 100% in guadagno, durata media 3665 giorni. Uscite: fine backtest 1.
Migliori: SPY +2,925$. Peggiori: SPY +2,925$.

**spy_con_semaforo**: 17 operazioni, 47% in guadagno, durata media 177 giorni. Uscite: semaforo rosso 16, fine backtest 1.
Migliori: SPY +1,793$. Peggiori: SPY +1,793$.

**etf_rotazione**: 463 operazioni, 43% in guadagno, durata media 24 giorni. Uscite: stop 303, uscito dalla classifica 121, semaforo rosso 36, fine backtest 3.
Migliori: SMH +259$, KRE +193$, GLD +173$, GDX +65$. Peggiori: XLI -40$, XBI -46$, XLP -65$.

**etf_aggressiva**: 490 operazioni, 44% in guadagno, durata media 22 giorni. Uscite: stop 309, uscito dalla classifica 141, semaforo rosso 37, fine backtest 3.
Migliori: TQQQ +367$, KRE +179$, SMH +97$, GDX +88$. Peggiori: UPRO -61$, XLE -83$, TNA -256$.

**etf_aggressiva_top3**: 371 operazioni, 46% in guadagno, durata media 23 giorni. Uscite: stop 228, uscito dalla classifica 111, semaforo rosso 30, fine backtest 2.
Migliori: TQQQ +512$, KRE +195$, GDX +100$, SMH +87$. Peggiori: XLE -49$, UPRO -202$, TNA -421$.

**azioni_etf_leva**: 710 operazioni, 43% in guadagno, durata media 23 giorni. Uscite: stop 434, uscito dalla classifica 200, semaforo rosso 74, fine backtest 2.
Migliori: PLTR +1,756$, MU +1,480$, MSTR +1,213$, NVDA +923$. Peggiori: AMD -595$, RIVN -735$, ARM -848$.

