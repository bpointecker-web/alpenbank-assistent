"""Streamlit-Oberfläche für den Alpenbank-Assistenten (Schritt 4 / Agent).

Die App stellt ein einziges Chat-Fenster bereit. Pro Nutzerfrage ruft
sie ``agent.answer_question`` auf und überlässt Claude die Entscheidung,
welches der zwei Werkzeuge (``dokumenten_suche``,
``datenbank_abfrage``) er nutzt – möglicherweise auch beide
nacheinander. Die Werkzeuge werden in der UI als ausklappbare
Trace-Blöcke unter der Antwort dargestellt, damit der Nutzer
nachvollziehen kann, was Claude getan hat.

Voraussetzungen (Live-Modus):
    data/chroma/         (für RAG, erzeugt durch scripts/rag_index.py)
    data/controlling.db  (für SQL, erzeugt durch scripts/daten_erzeugen.py)
    ANTHROPIC_API_KEY in .env

Demo-Modus (ALPENBANK_DEMO_MODE=1, siehe src/demo.py):
    data/demo_cache.json (erzeugt durch scripts/demo_cache_erzeugen.py)
    Kein API-Key nötig – nur die Demo-Fragen (siehe demo.DEMO_FRAGEN)
    werden beantwortet.

Start im Projekt-Root:
    streamlit run src/app.py
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Projekt-Root in den Importpfad aufnehmen, damit "from src import ..."
# auch beim Aufruf via "streamlit run src/app.py" funktioniert. Streamlit
# legt nur das Verzeichnis der gestarteten Datei (src/) in sys.path,
# nicht das Projekt-Root. Bei Tests übernimmt das pytest.ini, hier
# müssen wir es selbst tun – analog zu scripts/rag_index.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402
from anthropic import Anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from src import agent, audit, demo, guardrails, rag, sql  # noqa: E402
from src.settings import SETTINGS  # noqa: E402
from src.logging_config import setup_logging  # noqa: E402

# .env laden, bevor wir auf Umgebungsvariablen zugreifen.
load_dotenv()

setup_logging()
logger = logging.getLogger(__name__)

# Demo-Modus: spielt vorab aufgezeichnete Antworten aus data/demo_cache.json
# ab, statt Claude live aufzurufen. Ermöglicht eine öffentlich verlinkbare,
# kostenlose Demo (z. B. auf Streamlit Community Cloud) ohne API-Key auf
# dem Server – siehe src/demo.py und scripts/demo_cache_erzeugen.py.
DEMO_MODE = os.environ.get("ALPENBANK_DEMO_MODE") == "1"

# Pfade müssen zu den Konstanten in den Indexier-/Erzeugungs-Skripten
# passen – beide laufen aus dem Projekt-Root.
CHROMA_PATH = Path("data/chroma")
CONTROLLING_PATH = Path("data/controlling.db")

# set_page_config muss der erste Streamlit-Aufruf sein.
st.set_page_config(page_title="Alpenbank-Assistent", page_icon="🏔️")

# Gebrandeter Header statt st.title(): kein echtes Logo vorhanden, daher
# ein sauber gestalteter Text-Banner in der Bank-Farbpalette aus
# .streamlit/config.toml (Petrol/Navy + Gold-Akzent). unsafe_allow_html
# ist hier unkritisch, weil der HTML-Inhalt eine feste Konstante ist –
# keine Nutzereingabe fließt hinein.
st.markdown(
    """
    <style>
    .alpenbank-header {
        background: linear-gradient(135deg, #0f2a3d 0%, #1b3a52 100%);
        color: #f5f1e6;
        padding: 1.75rem 2rem;
        border-radius: 0.5rem;
        border-bottom: 3px solid #c9a227;
        margin-bottom: 1.25rem;
    }
    .alpenbank-header h1 {
        margin: 0 0 0.75rem 0;
        font-size: 1.9rem;
        color: #f5f1e6;
    }
    .alpenbank-header p, .alpenbank-header li {
        color: #cfd9e0;
        font-size: 0.95rem;
        line-height: 1.5;
    }
    .alpenbank-header strong {
        color: #f5f1e6;
    }
    .alpenbank-header a {
        color: #e8c65a;
        font-weight: 600;
    }
    .alpenbank-header ul {
        margin: 0.5rem 0;
        padding-left: 1.25rem;
    }
    </style>
    <div class="alpenbank-header">
        <h1>🏔️ ALPENBANK KI-ASSISTENT (RAG)</h1>
        <p>Ein Sprachmodell (LLM), das ausschließlich auf den internen Daten der (frei erfundenen) Alpenbank AG arbeitet: ihren Richtlinien-Dokumenten und ihrer Controlling-Datenbank (relationale Datenbank).</p>
        <p>Statt allgemeines Wissen aus dem Internet wiederzugeben, beantwortet es Fragen belegbar aus dem eigenen Datenbestand der Bank – die Daten verlassen das Haus nicht. Genau das macht diese Technik für regulierte Branchen einsetzbar.</p>
        <p>Zwei Arten von Fragen – der Assistent erkennt selbst, welche gemeint ist, und wählt das passende Werkzeug:</p>
        <ul>
            <li><strong>Richtlinien</strong> (Text-Dokumente): <em>„Welche Hotelkategorie darf ich auf Dienstreisen buchen?“</em></li>
            <li><strong>Kennzahlen</strong> (Controlling-Datenbank): <em>„Wie hoch waren die Erträge 2024?“</em></li>
        </ul>
        <p>Beides lässt sich auch kombinieren. Bei jeder Antwort legt er offen, welche Quelle er benutzt hat – nachvollziehbar statt „vertrau mir“.</p>
        <p>Einen Chatbot baut man schnell. Die eigentliche Arbeit steckt darin, ihn so abzusichern, dass eine regulierte Bank ihn tatsächlich einsetzen darf. Genau diese Schicht zeigt die Demo:</p>
        <ul>
            <li><strong>Nachvollziehbarkeit</strong> – jede Antwort ist auf ihre Quelle zurückführbar, jede Anfrage wird protokolliert (Audit-Trail nach EU-AI-Act-Logik). Sichtbar unten im Governance-Panel.</li>
            <li><strong>Manipulationsschutz</strong> – ein präpariertes Dokument, das dem Assistenten heimlich neue Anweisungen unterjubeln will, wird erkannt und neutralisiert. Live ausprobierbar mit dem Chip <em>„Welche Regeln gelten für die Kundenkommunikation?“</em>.</li>
            <li><strong>Datenschutz</strong> – personenbezogene Daten (E-Mail, IBAN, Telefonnummer) werden automatisch aus dem Protokoll entfernt.</li>
        </ul>
    </div>
    """,
    unsafe_allow_html=True,
)

# Architektur-Diagramm direkt in der App (statt Link nach außen): der
# Besucher bleibt im Showroom. Die SVG liegt versioniert unter docs/ und
# wird beim Aufruf gelesen (App läuft aus dem Projekt-Root, analog zu den
# data/-Pfaden). Fehlt die Datei, wird der Abschnitt einfach weggelassen –
# ein fehlendes Diagramm darf die App nicht blockieren.
ARCHITEKTUR_DIAGRAMM_PATH = Path("docs/diagramme/architektur_high_level.svg")
if ARCHITEKTUR_DIAGRAMM_PATH.exists():
    with st.expander("📐 Systemarchitektur ansehen"):
        st.image(str(ARCHITEKTUR_DIAGRAMM_PATH), use_container_width=True)

st.divider()

if DEMO_MODE:
    st.caption("Demo-Modus – kostenlos, ohne Live-API")
    st.info(
        "**Demo-Modus:** Diese Instanz beantwortet nur die "
        "Beispielfragen unten mit vorab aufgezeichneten, echten "
        "Claude-Antworten – kein API-Key, keine laufenden Kosten. "
        "Für eigene Fragen: Projekt lokal mit eigenem "
        "Anthropic-API-Key betreiben (siehe README).",
        icon="🧪",
    )
else:
    # API-Key prüfen, bevor wir den Client bauen. Lieber sofort eine klare
    # Fehlermeldung als ein kryptischer Authentifizierungs-Fehler später.
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error(
            "ANTHROPIC_API_KEY ist nicht gesetzt. Bitte `.env.example` "
            "nach `.env` kopieren und den Schlüssel eintragen."
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
def open_bm25_index(chroma_path_str: str) -> rag.Bm25Index:
    """Baut den In-Memory-BM25-Index einmalig pro Session (Hybrid-Search).

    Öffnet eine eigene, leichte Collection-Referenz OHNE Embedding-
    Funktion – ``collection.get()`` (das ``build_bm25_index`` intern
    aufruft) braucht sie nicht. Vermeidet, das ~120-MB-Embedding-Modell
    ein zweites Mal zu laden, nur um an die Chunk-Texte zu kommen (analog
    zu ``scripts/rag_inspect.py``s ``with_embedding=False``-Pfad).
    """
    client = chromadb.PersistentClient(path=chroma_path_str)
    collection = client.get_collection(name=rag.COLLECTION_NAME)
    return rag.build_bm25_index(collection)


@st.cache_resource
def open_reranker() -> Any:
    """Lädt den Cross-Encoder für Reranking einmalig pro Session."""
    return rag.get_default_reranker()


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


@st.cache_resource
def load_demo_cache(cache_path_str: str) -> dict:
    """Lädt den Demo-Cache einmal pro Session (siehe ``src/demo.py``)."""
    return demo.load_cache(cache_path_str)


# Eager-Loading der Ressourcen. Im Demo-Modus reicht der Cache – Embedding-
# Modell, ChromaDB und die Controlling-DB werden dort gar nicht erst
# angerührt, was den Cloud-Deploy leichtgewichtig hält. Im Live-Modus
# müssen Embedding-Modell und DB-Schema direkt beim App-Start verfügbar
# sein, weil Claude im Tool-Use-Modus jederzeit beide Werkzeuge wählen
# kann. Streamlit zeigt dabei seinen eigenen Spinner, der erste Start
# dauert deshalb spürbar länger.
if DEMO_MODE:
    client = None
    rag_index = None
    connection = None
    schema = None
    try:
        demo_cache = load_demo_cache(str(demo.DEMO_CACHE_PATH))
    except FileNotFoundError as exc:
        st.error(str(exc))
        st.stop()
else:
    demo_cache = None
    client = build_client(api_key)
    try:
        collection = open_collection(str(CHROMA_PATH))
        bm25_index = open_bm25_index(str(CHROMA_PATH))
        reranker = open_reranker()
        rag_index = rag.RagIndex(
            collection=collection, bm25_index=bm25_index, reranker=reranker
        )
        connection = open_db(str(CONTROLLING_PATH))
        schema = load_schema(str(CONTROLLING_PATH))
    except (FileNotFoundError, LookupError, ValueError) as exc:
        st.error(str(exc))
        st.stop()


# Historie für die UI. Jede Assistant-Message trägt zusätzlich zu
# ``content`` ihre ``traces`` (Tool-Aufrufe) und ``iterations_used``,
# damit die Trace-Anzeige auch bei einem Streamlit-Re-Run nach Modus-
# unabhängigem Verlauf wieder korrekt aufgebaut wird.
if "messages" not in st.session_state:
    st.session_state.messages = []

# Kumulierter Token-Verbrauch der Session (Stage 4.4 – Budget-Bremse).
# Bleibt im Demo-Modus bei 0, weil dort nie ein echter API-Call
# stattfindet (agent.AgentAntwort.input_tokens/output_tokens sind dann
# per Default 0).
if "session_tokens_gesamt" not in st.session_state:
    st.session_state.session_tokens_gesamt = 0


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
    """Zeigt die Trefferliste der Doku-Suche: Hybrid-Vorauswahl + Reranking.

    Seit Stage 2.5 ist die Liste nach ``rerank_score`` sortiert (Cross-
    Encoder, höher = relevanter) – das ist der Score, der die finale
    Reihenfolge bestimmt. ``fusion_score`` (Hybrid-Vorstufe, Stage 2.4)
    wird zusätzlich angezeigt: macht die zweistufige Pipeline
    (Hybrid-Vorauswahl → Reranking) im UI nachvollziehbar, statt nur das
    Endergebnis zu zeigen.
    """
    if not treffer:
        st.info("Keine Treffer.")
        return

    st.markdown(f"**Gefundene Quellen ({len(treffer)})**")
    for eintrag in treffer:
        st.markdown(
            f"**{eintrag['quelle']}** "
            f"(Rerank-Score {eintrag['rerank_score']:.4f}, "
            f"Hybrid-Fusion-Score {eintrag['fusion_score']:.4f})"
        )
        # Stage 4.3: Prompt-Injection-Heuristik. Der Schutz selbst
        # (XML-Escaping) greift immer; diese Warnung macht einen
        # erkannten Versuch zusätzlich direkt im Trace sichtbar, nicht
        # erst im Governance-Panel.
        guardrail_hinweise = eintrag.get("guardrail_hinweise")
        if guardrail_hinweise:
            st.warning(
                "⚠️ Verdächtiges Muster in diesem Chunk erkannt "
                f"(Prompt-Injection-Heuristik): {', '.join(guardrail_hinweise)}"
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


def render_governance_panel() -> None:
    """Governance-Panel (Stage 4.6): macht Compliance sichtbar statt nur behauptet.

    Nutzt ``audit.session_zusammenfassung`` auf der aktuellen
    Chat-Historie – funktioniert dadurch identisch im Demo- und im
    Live-Modus, ohne dass im Demo-Modus ein echtes Audit-Log nötig
    wäre (dort entsteht ohnehin keine echte Interaktion).
    """
    zusammenfassung = audit.session_zusammenfassung(st.session_state.messages)

    with st.expander("🛡️ Governance & Transparenz dieser Session"):
        spalten = st.columns(3 if DEMO_MODE else 4)
        spalten[0].metric("Fragen gestellt", zusammenfassung["anzahl_fragen"])
        spalten[1].metric("Genutzte Quellen", len(zusammenfassung["quellen"]))
        spalten[2].metric(
            "Guardrail-Hinweise", len(zusammenfassung["guardrail_hinweise"])
        )
        if not DEMO_MODE:
            verbrauch_de = f"{st.session_state.session_tokens_gesamt:,}".replace(
                ",", "."
            )
            budget_de = f"{SETTINGS.session_token_budget:,}".replace(",", ".")
            spalten[3].metric("Token-Budget", f"{verbrauch_de} / {budget_de}")

        if zusammenfassung["guardrail_hinweise"]:
            st.warning(
                "⚠️ In dieser Session erkannte Guardrail-Hinweise "
                "(Prompt-Injection-Heuristik):\n\n"
                + "\n".join(f"- {h}" for h in zusammenfassung["guardrail_hinweise"])
            )

        if zusammenfassung["quellen"]:
            st.markdown(
                "**Verwendete Quellen:** " + ", ".join(zusammenfassung["quellen"])
            )

        if DEMO_MODE:
            st.caption(
                "Im Demo-Modus wird nichts persistiert (keine echten "
                "API-Aufrufe) – diese Kennzahlen spiegeln nur die aktuell "
                "sichtbare Chat-Historie. Im Live-Modus protokolliert das "
                "Audit-Log (`data/audit_log.jsonl`) jede Interaktion "
                "dauerhaft, siehe `src/audit.py`."
            )
        else:
            anzahl_geloggt = len(audit.lies_audit_log())
            st.caption(
                f"Persistiertes Audit-Log: {anzahl_geloggt} Einträge in "
                f"`{audit.DEFAULT_AUDIT_LOG_PATH}`."
            )


# Beispielfrage-Chips: alle Demo-Fragen (zehn aus KONZEPT.md plus der
# Prompt-Injection-Sicherheitsfall, Stage 4.3) als klickbare Buttons,
# zweispaltig. Ein Klick setzt "chip_frage" in den Session-State;
# Streamlit rendert dabei automatisch neu, der eigentliche Verlauf unten
# behandelt Chip-Klick und Freitext-Eingabe danach einheitlich.
st.markdown("**Beispielfragen zum Ausprobieren:**")
chip_spalten = st.columns(2)
for index, frage in enumerate(demo.DEMO_FRAGEN):
    spalte = chip_spalten[index % 2]
    if spalte.button(frage, key=f"chip_{index}", use_container_width=True):
        st.session_state["chip_frage"] = frage
st.divider()


# Bisherigen Verlauf rendern.
for msg in st.session_state.messages:
    render_message(msg)


user_input = st.chat_input("Stell deine Frage …")

# Chip-Klick zählt wie eine getippte Frage, hat aber Vorrang nur, wenn im
# selben Durchlauf nichts eingegeben wurde – chat_input() liefert nach
# einem Klick auf einen Button ohnehin None.
chip_frage = st.session_state.pop("chip_frage", None)
if chip_frage and not user_input:
    user_input = chip_frage

if user_input:
    # Guardrails (Stage 4.4) gelten nur im Live-Modus: Input-Sanitisierung
    # und Budget-Bremse schützen vor unnötigem/exzessivem API-Verbrauch –
    # im Demo-Modus entsteht ohnehin keiner. Bewusst VOR dem Anhängen an
    # die Historie geprüft, damit eine abgelehnte Eingabe nicht als
    # regulärer Chat-Turn erscheint.
    if not DEMO_MODE:
        try:
            guardrails.pruefe_nutzereingabe(user_input)
        except guardrails.EingabeAbgelehnt as exc:
            st.error(str(exc))
            st.stop()

        if guardrails.budget_ueberschritten(
            st.session_state.session_tokens_gesamt, SETTINGS.session_token_budget
        ):
            budget_de = f"{SETTINGS.session_token_budget:,}".replace(",", ".")
            st.error(
                f"Das Token-Budget dieser Session ({budget_de} Tokens) "
                "ist ausgeschöpft. Bitte starte eine neue Session "
                "(Seite neu laden)."
            )
            st.stop()

    user_msg = {"role": "user", "content": user_input}
    st.session_state.messages.append(user_msg)
    render_message(user_msg)

    spinner_text = (
        "Antwort wird geladen …" if DEMO_MODE else "Claude überlegt und nutzt Werkzeuge …"
    )
    with st.spinner(spinner_text):
        try:
            if DEMO_MODE:
                cache_treffer = demo.lookup(demo_cache, user_input)
                if cache_treffer is None:
                    antwort = agent.AgentAntwort(
                        text=demo.KEIN_CACHE_TREFFER_HINWEIS,
                        traces=[],
                        iterations_used=0,
                    )
                else:
                    antwort = demo.deserialize_antwort(cache_treffer)
            else:
                antwort = agent.answer_question(
                    client,
                    frage=user_input,
                    history=history_for_agent(st.session_state.messages[:-1]),
                    db=connection,
                    rag_index=rag_index,
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

    # Audit-Log und Budget-Zähler nur im Live-Modus: eine Demo-Modus-
    # Antwort ist keine echte Interaktion mit dem System (kein API-Call,
    # kein echter Tool-Zugriff) und hat im Audit-Trail nichts verloren.
    if not DEMO_MODE:
        audit.log_audit_eintrag(
            audit.baue_audit_eintrag(user_input, antwort, agent.MODEL)
        )
        st.session_state.session_tokens_gesamt += (
            antwort.input_tokens + antwort.output_tokens
        )

    assistant_msg = {
        "role": "assistant",
        "content": antwort.text,
        "traces": list(antwort.traces),
        "iterations_used": antwort.iterations_used,
    }
    st.session_state.messages.append(assistant_msg)
    render_message(assistant_msg)


# Erst HIER (nach dem gesamten Frage-Antwort-Zyklus) aufrufen, nicht
# weiter oben im Skript: Streamlit führt das komplette Skript pro
# Interaktion einmal linear von oben nach unten aus, ohne reaktives
# Nach-Rendern bereits ausgegebener Widgets. Ein Aufruf vor dem
# "if user_input:"-Block würde deshalb immer den Stand VOR der gerade
# beantworteten Frage zeigen (eine Interaktion Verzögerung) - siehe
# Bug bei der ursprünglichen Platzierung vor den Beispielfrage-Chips.
#
# Defensiv gekapselt: das Governance-Panel ist reine Zusatz-Transparenz,
# kein kritischer Pfad. Ein Fehler hier (z. B. eine unerwartete Objekt-
# form im Session-State auf Streamlit Cloud) darf niemals die ganze App
# mit einem Traceback abstürzen lassen - Details ins Log, unauffälliger
# Hinweis ins UI, Chat bleibt bedienbar.
try:
    render_governance_panel()
except Exception:
    logger.exception("Governance-Panel konnte nicht gerendert werden")
    st.caption("ℹ️ Governance-Panel momentan nicht verfügbar.")


# Streamlit steckt die Hauptspalte wegen st.chat_input in einen
# ``stAppScrollToBottomContainer`` und scrollt diesen beim Laden
# automatisch ganz nach unten (Chat-Verhalten: Eingabefeld sichtbar
# halten). Bei unserer hohen Einordnungs-Box landet dadurch der Header
# außerhalb des sichtbaren Bereichs. Nur im Anfangszustand (noch keine
# Frage gestellt) scrollen wir den Container aktiv wieder nach oben,
# damit der Besucher zuerst die Erklärung sieht. Sobald Nachrichten
# existieren, überlassen wir Streamlit das Scroll-to-bottom – dann will
# man ja die frische Antwort unten sehen. Der Container braucht nach
# Streamlits eigenem Scroll kurz Zeit, deshalb ein paar Wiederholungen.
if not st.session_state.messages:
    components.html(
        """
        <script>
        const doc = window.parent.document;
        const nachOben = () => {
            const c = doc.querySelector('[data-testid="stAppScrollToBottomContainer"]');
            if (c) { c.scrollTop = 0; }
        };
        nachOben();
        let n = 0;
        const iv = setInterval(() => { nachOben(); if (++n > 12) clearInterval(iv); }, 60);
        </script>
        """,
        height=0,
    )
