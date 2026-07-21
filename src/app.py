"""Streamlit-Oberfläche für den Alpenbank-Assistenten (Schritt 4 / Agent).

Die App stellt ein einziges Chat-Fenster bereit. Pro Nutzerfrage ruft
sie ``agent.answer_question`` auf und überlässt Claude die Entscheidung,
welches der zwei Werkzeuge (``dokumenten_suche``,
``datenbank_abfrage``) er nutzt – möglicherweise auch beide
nacheinander. Die Werkzeuge werden in der UI als ausklappbare
Trace-Blöcke unter der Antwort dargestellt, damit der Nutzer
nachvollziehen kann, was Claude getan hat.

Voraussetzungen:
    data/chroma/         (für RAG, erzeugt durch scripts/rag_index.py)
    data/controlling.db  (für SQL, erzeugt durch scripts/daten_erzeugen.py)

Start im Projekt-Root:
    streamlit run src/app.py
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from pathlib import Path

# Projekt-Root in den Importpfad aufnehmen, damit "from src import ..."
# auch beim Aufruf via "streamlit run src/app.py" funktioniert. Streamlit
# legt nur das Verzeichnis der gestarteten Datei (src/) in sys.path,
# nicht das Projekt-Root. Bei Tests übernimmt das pytest.ini, hier
# müssen wir es selbst tun – analog zu scripts/rag_index.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402
import streamlit as st  # noqa: E402
from anthropic import Anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from src import agent, rag, sql  # noqa: E402
from src.logging_config import setup_logging  # noqa: E402

# .env laden, bevor wir auf Umgebungsvariablen zugreifen.
load_dotenv()

setup_logging()
logger = logging.getLogger(__name__)

# Pfade müssen zu den Konstanten in den Indexier-/Erzeugungs-Skripten
# passen – beide laufen aus dem Projekt-Root.
CHROMA_PATH = Path("data/chroma")
CONTROLLING_PATH = Path("data/controlling.db")

# set_page_config muss der erste Streamlit-Aufruf sein.
st.set_page_config(page_title="Alpenbank-Assistent", page_icon="🏔️")

st.title("Alpenbank-Assistent")
st.caption("Schritt 4: Agent mit Tool Use")

# API-Key prüfen, bevor wir den Client bauen. Lieber sofort eine klare
# Fehlermeldung als ein kryptischer Authentifizierungs-Fehler später.
api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    st.error(
        "ANTHROPIC_API_KEY ist nicht gesetzt. "
        "Bitte `.env.example` nach `.env` kopieren und den Schlüssel eintragen."
    )
    st.stop()


@st.cache_resource
def build_client(key: str) -> Anthropic:
    """Erzeugt den Anthropic-Client einmal pro Streamlit-Session."""
    return Anthropic(api_key=key)


@st.cache_resource
def open_collection(chroma_path_str: str):
    """Öffnet die persistierte ChromaDB-Collection einmalig.

    @st.cache_resource sorgt dafür, dass das Embedding-Modell nur einmal
    pro Session geladen wird – sonst würde jeder Klick im Chat-Fenster
    die ~120 MB neu instanzieren und die App wäre unbenutzbar.
    """
    if not Path(chroma_path_str).exists():
        raise FileNotFoundError(
            f"ChromaDB-Pfad {chroma_path_str} existiert nicht. "
            "Bitte zuerst `python scripts/rag_index.py` ausführen."
        )

    client = chromadb.PersistentClient(path=chroma_path_str)

    vorhandene = [c.name for c in client.list_collections()]
    if rag.COLLECTION_NAME not in vorhandene:
        raise LookupError(
            f"Collection '{rag.COLLECTION_NAME}' nicht in {chroma_path_str} "
            "gefunden. Bitte `python scripts/rag_index.py` ausführen."
        )

    return rag.create_collection(client, name=rag.COLLECTION_NAME)


@st.cache_resource
def open_db(db_path_str: str) -> sqlite3.Connection:
    """Öffnet die Controlling-Datenbank read-only und cacht die Verbindung."""
    return sql.connect(db_path_str)


@st.cache_resource
def load_schema(db_path_str: str) -> str:
    """Liest die Schema-Beschreibung einmal pro Session.

    Wir nutzen eine eigene, kurzlebige Verbindung für den Schema-Zugriff
    und schließen sie sofort wieder. Die langlebige Verbindung aus
    ``open_db`` reservieren wir für die eigentlichen SELECT-Abfragen,
    damit beide Lebenszyklen voneinander unabhängig bleiben.
    """
    tmp_conn = sql.connect(db_path_str)
    try:
        return sql.build_schema_description(tmp_conn)
    finally:
        tmp_conn.close()


# Eager-Loading aller Ressourcen. Im Tool-Use-Modus kann Claude jederzeit
# beide Werkzeuge wählen, deshalb müssen Embedding-Modell und DB-Schema
# direkt beim App-Start verfügbar sein. Streamlit zeigt dabei seinen
# eigenen Spinner, der erste Start dauert deshalb spürbar länger.
client = build_client(api_key)
try:
    collection = open_collection(str(CHROMA_PATH))
    connection = open_db(str(CONTROLLING_PATH))
    schema = load_schema(str(CONTROLLING_PATH))
except (FileNotFoundError, LookupError) as exc:
    st.error(str(exc))
    st.stop()


# Historie für die UI. Jede Assistant-Message trägt zusätzlich zu
# ``content`` ihre ``traces`` (Tool-Aufrufe) und ``iterations_used``,
# damit die Trace-Anzeige auch bei einem Streamlit-Re-Run nach Modus-
# unabhängigem Verlauf wieder korrekt aufgebaut wird.
if "messages" not in st.session_state:
    st.session_state.messages = []


def history_for_agent(messages: list[dict]) -> list[dict]:
    """Filtert die UI-Historie auf das, was Claude sehen soll.

    Wir geben Claude pro Frage einen frischen Tool-Use-Loop, aber den
    bisherigen Konversationskontext als reine Text-Messages mit. Die
    UI-spezifischen Felder (``traces``, ``iterations_used``) gehören
    nicht ins API-Payload.
    """
    return [
        {"role": msg["role"], "content": msg["content"]}
        for msg in messages
        if msg["role"] in ("user", "assistant") and msg.get("content")
    ]


def render_trace(trace) -> None:
    """Zeigt einen einzelnen Tool-Aufruf als ausklappbaren Block."""
    fehler_marker = " ⚠️" if trace.ergebnis.is_error else ""
    titel = f"Tool: {trace.name}{fehler_marker}"

    with st.expander(titel):
        # Tool-Input zuerst, damit klar ist, *wonach* gefragt wurde.
        st.markdown("**Aufruf-Parameter**")
        st.code(_format_tool_input(trace.tool_input), language="json")

        if trace.ergebnis.is_error:
            st.error(trace.ergebnis.text)
            return

        # Erfolgreicher Aufruf – tool-spezifische Anzeige der Details.
        if trace.name == "dokumenten_suche":
            _render_dokumenten_suche_details(trace.ergebnis.details)
        elif trace.name == "datenbank_abfrage":
            _render_datenbank_abfrage_details(trace.ergebnis.details)


def _format_tool_input(tool_input: dict) -> str:
    """Formatiert das Tool-Input-Dict als zweizeiliges JSON-Snippet.

    Bewusst kein ``json.dumps`` mit ``indent=2`` für lange SQLs:
    Strings wie SELECT-Statements bleiben als Zeile lesbarer, wenn wir
    sie nicht über Zeilen umbrechen.
    """
    paare = [f'"{k}": {repr(v)}' for k, v in tool_input.items()]
    return "{ " + ", ".join(paare) + " }"


def _render_dokumenten_suche_details(treffer: list) -> None:
    """Zeigt die Trefferliste der Doku-Suche."""
    if not treffer:
        st.info("Keine Treffer.")
        return

    st.markdown(f"**Gefundene Quellen ({len(treffer)})**")
    for eintrag in treffer:
        st.markdown(
            f"**{eintrag['quelle']}** (Distanz {eintrag['distanz']:.3f})"
        )
        auszug = eintrag["inhalt"][:300]
        if len(eintrag["inhalt"]) > 300:
            auszug += " …"
        st.markdown(f"> {auszug}")


def _render_datenbank_abfrage_details(details: dict) -> None:
    """Zeigt das ausgeführte SQL und das Ergebnis als Markdown-Tabelle."""
    st.markdown("**Ausgeführtes SQL**")
    st.code(details["sql"], language="sql")
    st.markdown("**Ergebnis**")
    st.markdown(details["tabelle"])


def render_message(msg: dict) -> None:
    """Zeigt eine UI-Nachricht plus ggf. Trace-Block und Limit-Hinweis."""
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        for trace in msg.get("traces", []):
            render_trace(trace)

        # Iterationslimit-Warnung nur dann, wenn das Limit auch wirklich
        # erreicht wurde. Vergleich mit DEFAULT_MAX_ITERATIONS, weil die
        # App den Default verwendet.
        if msg.get("iterations_used", 0) >= agent.DEFAULT_MAX_ITERATIONS:
            st.warning(
                "Iterationslimit erreicht – Claude hat möglicherweise "
                "nicht alle Werkzeuge sinnvoll einsetzen können."
            )


# Bisherigen Verlauf rendern.
for msg in st.session_state.messages:
    render_message(msg)


user_input = st.chat_input("Stell deine Frage …")

if user_input:
    user_msg = {"role": "user", "content": user_input}
    st.session_state.messages.append(user_msg)
    render_message(user_msg)

    with st.spinner("Claude überlegt und nutzt Werkzeuge …"):
        try:
            antwort = agent.answer_question(
                client,
                frage=user_input,
                history=history_for_agent(st.session_state.messages[:-1]),
                db=connection,
                collection=collection,
                schema=schema,
            )
        except Exception:
            # Generischer Fang für unerwartete Probleme (Netzwerk,
            # Auth, ChromaDB). Spezifische Fehlerklassen kommen, sobald
            # wir sie im Betrieb wirklich beobachten. Die Details
            # (inkl. Traceback) gehen ins Log, nicht ins UI – sonst
            # leaken wir interne Fehlermeldungen an den Nutzer.
            logger.exception("Fehler bei der Beantwortung der Frage")
            st.error(
                "Es ist ein unerwarteter Fehler aufgetreten. Die Details "
                "wurden protokolliert. Bitte versuche es erneut."
            )
            st.stop()

    assistant_msg = {
        "role": "assistant",
        "content": antwort.text,
        "traces": list(antwort.traces),
        "iterations_used": antwort.iterations_used,
    }
    st.session_state.messages.append(assistant_msg)
    render_message(assistant_msg)
