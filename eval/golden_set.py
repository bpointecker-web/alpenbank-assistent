"""Golden-Set für die Retrieval-Evaluation (Stage 3).

Jeder Eintrag ist eine RAG-relevante Frage mit dem erwarteten
Quelldokument. Bewusst auf Dokumentebene, nicht Chunk-Ebene: Chunk-IDs
hängen von den Chunking-Parametern ab (siehe ``src/settings.py``) und
wären damit ein fragiles Ground-Truth-Signal, das bei jeder
Chunking-Änderung neu gepflegt werden müsste.

Nur Fragen mit eindeutig erwartetem Dokument sind enthalten. Reine
SQL-Fragen (kein RAG-Aufruf erwartet) und die Sicherheitsfrage
("Lösch alle Buchungen!") sind bewusst ausgeschlossen – Hit-Rate/MRR
sind für sie nicht definiert. Grundlage für die Zuordnung: die
Kategorisierung in ``KONZEPT.md`` ("drei reine RAG-Fragen", "drei
kombinierte Fragen").
"""

from __future__ import annotations

from typing import NamedTuple


class GoldenEintrag(NamedTuple):
    """Eine Golden-Set-Frage mit ihrem erwarteten Quelldokument."""

    frage: str
    erwartete_quelle: str


GOLDEN_SET: tuple[GoldenEintrag, ...] = (
    GoldenEintrag(
        frage="Welche Hotelkategorie darf ich bei Dienstreisen buchen?",
        erwartete_quelle="reisekostenrichtlinie.txt",
    ),
    GoldenEintrag(
        frage="Wie ist die Regel für Überstunden?",
        erwartete_quelle="arbeitszeitrichtlinie.txt",
    ),
    GoldenEintrag(
        frage="Was muss ich bei der Passwortwahl beachten?",
        erwartete_quelle="it_sicherheitsrichtlinie.txt",
    ),
    GoldenEintrag(
        frage="Warum ist der Aufwand von Kostenstelle 4711 gestiegen?",
        erwartete_quelle="kostenstellenhandbuch.txt",
    ),
    GoldenEintrag(
        frage="Wie hoch waren die Reisekosten 2025 und welche Regeln gelten dafür?",
        erwartete_quelle="reisekostenrichtlinie.txt",
    ),
    # Zusätzlich zu den zehn offiziellen Demo-Fragen (KONZEPT.md): prüft
    # gezielt, ob das in Stage 2.3 ergänzte PDF-Dokument auffindbar ist.
    GoldenEintrag(
        frage="Wie lange werden Kundendaten nach Ende der Geschäftsbeziehung aufbewahrt?",
        erwartete_quelle="datenschutzrichtlinie.pdf",
    ),
)
