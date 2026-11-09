"""Sentiment delle notizie Benzinga con un dizionario di parole finanziarie.

Volutamente semplice e deterministico: lo stesso titolo dà sempre lo stesso punteggio,
così il backtest e l'operatività reale si comportano allo stesso modo.
Punteggio di un titolo: da -1 (molto negativo) a +1 (molto positivo).
"""
from __future__ import annotations

import re

POSITIVE = {
    "beat", "beats", "tops", "surge", "surges", "soar", "soars", "jump", "jumps", "rally",
    "rallies", "record", "upgrade", "upgrades", "upgraded", "outperform", "buy", "bullish",
    "raises", "raised", "boost", "boosts", "strong", "growth", "profit", "approval",
    "approved", "wins", "win", "partnership", "expands", "breakthrough", "exceeds",
    "higher", "gains", "gain", "rises", "rise", "climbs", "optimistic", "upside",
    "dividend", "buyback", "repurchase", "accelerates", "momentum", "overweight",
}
NEGATIVE = {
    "miss", "misses", "missed", "plunge", "plunges", "sink", "sinks", "drop", "drops",
    "fall", "falls", "slump", "downgrade", "downgrades", "downgraded", "underperform",
    "sell", "bearish", "cuts", "cut", "lowers", "lowered", "weak", "loss", "losses",
    "lawsuit", "probe", "investigation", "recall", "delay", "delays", "warning", "warns",
    "decline", "declines", "lower", "slides", "tumble", "tumbles", "fraud", "layoffs",
    "bankruptcy", "halt", "halted", "subpoena", "fine", "fined", "downside", "underweight",
    "disappoints", "disappointing", "concern", "concerns", "risk", "crash",
}
NEGATORS = {"not", "no", "fails", "without"}
_word = re.compile(r"[a-z']+")


def headline_score(text: str) -> float:
    words = _word.findall((text or "").lower())
    score, hits = 0, 0
    for i, w in enumerate(words):
        s = 1 if w in POSITIVE else -1 if w in NEGATIVE else 0
        if s and i > 0 and words[i - 1] in NEGATORS:
            s = -s
        if s:
            score += s
            hits += 1
    return 0.0 if hits == 0 else max(-1.0, min(1.0, score / hits))


def aggregate(scores: list[float]) -> tuple[float, int]:
    """Media dei punteggi delle notizie, e numero di notizie."""
    return (sum(scores) / len(scores), len(scores)) if scores else (0.0, 0)
