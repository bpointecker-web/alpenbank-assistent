"""Reine Metrik-Funktionen für die Retrieval-Evaluation (Stage 3).

Bewusst ohne LLM-as-Judge (kein RAGAS): Hit-Rate und MRR sind rein
mechanisch aus der Rangfolge der zurückgegebenen Quellen berechenbar,
brauchen keinen zusätzlichen API-Call und sind deterministisch
reproduzierbar. Frei von ChromaDB-/Anthropic-Code, daher ohne Mocks
testbar.
"""

from __future__ import annotations

from typing import Any


def quellen_rangfolge(treffer: list[dict[str, Any]]) -> list[str]:
    """Dedupliziert eine Chunk-Trefferliste zu einer Quellen-Rangfolge.

    Hit-Rate/MRR werden auf Dokumentebene gemessen, nicht Chunk-Ebene:
    mehrere Chunks desselben Dokuments unter den Top-k zählen nicht
    mehrfach. Reihenfolge = erstes Vorkommen in der (bereits nach
    Relevanz sortierten) Chunk-Liste.
    """
    gesehen: list[str] = []
    for eintrag in treffer:
        quelle = eintrag["quelle"]
        if quelle not in gesehen:
            gesehen.append(quelle)
    return gesehen


def hit_at_k(quellen: list[str], erwartete_quelle: str, k: int) -> bool:
    """True, wenn ``erwartete_quelle`` unter den ersten ``k`` Quellen ist.

    Wirft ``ValueError`` bei nicht-positivem ``k``.
    """
    if k <= 0:
        raise ValueError(f"k muss positiv sein, war {k}.")
    return erwartete_quelle in quellen[:k]


def reciprocal_rank(quellen: list[str], erwartete_quelle: str) -> float:
    """1 / Rang der ersten Fundstelle von ``erwartete_quelle``.

    0.0, wenn die Quelle gar nicht in der Liste vorkommt.
    """
    for rang, quelle in enumerate(quellen, start=1):
        if quelle == erwartete_quelle:
            return 1.0 / rang
    return 0.0
