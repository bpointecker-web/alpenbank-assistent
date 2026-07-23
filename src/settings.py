"""Zentrale Konfiguration für den Alpenbank-Assistenten.

Bündelt Werte, die bisher als Modul-Konstanten in ``rag.py``/``agent.py``
hartkodiert waren, in einem env-gesteuerten Settings-Objekt. Macht das
System konfigurierbar (z. B. für die Chunk-Größen-Experimente in Stage 2),
ohne die bestehenden Funktionssignaturen anzufassen: ``rag.py``/``agent.py``
importieren ``SETTINGS`` und weisen die Werte weiterhin ihren eigenen
Modul-Konstanten zu.

Bewusst frei von Streamlit-/Anthropic-Code, damit einzeln testbar.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import NamedTuple


class Settings(NamedTuple):
    """Konfigurierbare Parameter für RAG-Chunking, Retrieval und den Agenten."""

    woerter_pro_chunk: int
    wort_overlap: int
    n_results: int
    model: str
    max_tokens: int
    max_iterations: int
    session_token_budget: int


# Chunk-Größe seit Stage 2.2: 150 Wörter/30 Overlap statt vormals 500/50.
# Bei den fünf (später sechs) Corpus-Dokumenten mit 275-323 Wörtern ergab
# 500/50 genau 1 Chunk pro Dokument – Retrieval war damit nie granularer
# als "ganzes Dokument", Overlap kam nie zum Tragen. 150/30 ergibt 3
# Chunks/Dokument in diesem Größenbereich, der letzte Chunk bleibt mit
# 35-90 Wörtern noch sinnvoll groß. Siehe scripts/rag_inspect.py zur
# manuellen QA der Chunk-Grenzen nach einer Änderung dieser Werte.
_DEFAULT_WOERTER_PRO_CHUNK = 150
_DEFAULT_WORT_OVERLAP = 30
_DEFAULT_N_RESULTS = 5
_DEFAULT_MODEL = "claude-sonnet-4-6"
# 2048 statt vormals 1024: seit dem kleineren Chunking (Stage 2.2) braucht
# Claude bei kombinierten Fragen mit mehreren Tool-Aufrufen mehr Tokens,
# um Zahlen (SQL) und Regeln (RAG) in einer Antwort zusammenzuführen –
# mit 1024 brach eine Demo-Antwort nachweislich mit stop_reason=max_tokens
# vorzeitig ab (siehe scripts/demo_cache_erzeugen.py-Lauf nach 2.2).
_DEFAULT_MAX_TOKENS = 2048
_DEFAULT_MAX_ITERATIONS = 5
# Session-Token-Budget (Stage 4.4): grobe Kostenbremse für den Live-Modus.
# 50.000 Tokens erlauben bei typischem Verbrauch (~1.000-3.000 Tokens pro
# Antwort, siehe data/demo_cache.json-Erzeugung) rund 15-30 Fragen pro
# Session, bevor der Nutzer eine neue Session starten muss. Gilt nicht im
# Demo-Modus (dort entsteht ohnehin kein Token-Verbrauch).
_DEFAULT_SESSION_TOKEN_BUDGET = 50_000


def _read_int(env: Mapping[str, str], key: str, default: int) -> int:
    """Liest eine positive Ganzzahl aus der Umgebung, mit Default-Fallback.

    Wirft ``ValueError`` bei einem gesetzten, aber ungültigen Wert (nicht
    numerisch oder <= 0) – ein Tippfehler in der Env-Variable soll laut
    CLAUDE.md nicht still zu falschem Verhalten führen, sondern beim
    Start sofort auffallen.
    """
    rohwert = env.get(key)
    if rohwert is None:
        return default

    try:
        wert = int(rohwert)
    except ValueError as exc:
        raise ValueError(f"{key}={rohwert!r} ist keine gültige Ganzzahl.") from exc

    if wert <= 0:
        raise ValueError(f"{key} muss positiv sein, war {wert}.")

    return wert


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Baut die Settings aus Umgebungsvariablen, mit Ist-Zustand als Default.

    ``env`` ist injizierbar (Default: ``os.environ``), damit Tests ohne
    echte Prozess-Umgebungsvariablen arbeiten können.
    """
    if env is None:
        env = os.environ

    woerter_pro_chunk = _read_int(
        env, "ALPENBANK_WOERTER_PRO_CHUNK", _DEFAULT_WOERTER_PRO_CHUNK
    )
    wort_overlap = _read_int(env, "ALPENBANK_WORT_OVERLAP", _DEFAULT_WORT_OVERLAP)
    if wort_overlap >= woerter_pro_chunk:
        raise ValueError(
            "ALPENBANK_WORT_OVERLAP muss kleiner sein als "
            f"ALPENBANK_WOERTER_PRO_CHUNK ({wort_overlap} >= {woerter_pro_chunk})."
        )

    n_results = _read_int(env, "ALPENBANK_N_RESULTS", _DEFAULT_N_RESULTS)
    max_tokens = _read_int(env, "ALPENBANK_MAX_TOKENS", _DEFAULT_MAX_TOKENS)
    max_iterations = _read_int(
        env, "ALPENBANK_MAX_ITERATIONS", _DEFAULT_MAX_ITERATIONS
    )
    session_token_budget = _read_int(
        env, "ALPENBANK_SESSION_TOKEN_BUDGET", _DEFAULT_SESSION_TOKEN_BUDGET
    )

    model = env.get("ALPENBANK_MODEL", _DEFAULT_MODEL)
    if not model.strip():
        raise ValueError("ALPENBANK_MODEL darf nicht leer sein.")

    return Settings(
        woerter_pro_chunk=woerter_pro_chunk,
        wort_overlap=wort_overlap,
        n_results=n_results,
        model=model,
        max_tokens=max_tokens,
        max_iterations=max_iterations,
        session_token_budget=session_token_budget,
    )


# Einmalig beim Modulimport ausgewertet – analog zum bestehenden
# ``DEMO_MODE = os.environ.get(...)``-Muster in ``app.py``. Änderungen an
# den Env-Variablen wirken erst nach einem Neustart des Prozesses.
SETTINGS = load_settings()
