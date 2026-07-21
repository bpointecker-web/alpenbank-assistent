"""Unit-Tests für src/agent.py.

Pro Funktion / Konstante mindestens drei Fälle (Normalfall, Randfall,
Fehlerfall) gemäß CLAUDE.md. Bei TOOL_DEFINITIONS interpretieren wir
"Fälle" als unterschiedliche Eigenschaften der Konstante:
Inhalt-Korrektheit, Struktur-Konformität, Anti-Regressionen
(z. B. Eindeutigkeit der Namen).
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from src import agent


# ---------------------------------------------------------------------------
# Hilfskonstrukte
# ---------------------------------------------------------------------------


class FakeCollection:
    """Minimaler Stub einer ChromaDB-Collection für Unit-Tests.

    Wir replizieren das Antwortformat von ``collection.query`` (Liste-
    von-Listen) statt eine echte ChromaDB anzulegen – das spart das
    Embedding-Modell und macht den Test deterministisch.
    """

    def __init__(self, antwort: dict):
        self.antwort = antwort
        self.aufrufe: list[dict] = []

    def query(self, query_texts, n_results):
        self.aufrufe.append({"query_texts": query_texts, "n_results": n_results})
        return self.antwort


def make_chroma_antwort(treffer: list[dict]) -> dict:
    """Baut das geschachtelte Listen-Format, das ChromaDB.query liefert."""
    return {
        "ids": [[t["id"] for t in treffer]],
        "documents": [[t["inhalt"] for t in treffer]],
        "metadatas": [[{"quelle": t["quelle"]} for t in treffer]],
        "distances": [[t["distanz"] for t in treffer]],
    }


def make_test_db() -> sqlite3.Connection:
    """In-Memory-DB mit zwei Zeilen, ausreichend für die SQL-Tool-Tests."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE konten (id INTEGER PRIMARY KEY, name TEXT, betrag REAL)"
    )
    conn.execute("INSERT INTO konten (name, betrag) VALUES ('Zinsertrag', 1000.5)")
    conn.execute("INSERT INTO konten (name, betrag) VALUES ('IT-Kosten', 200.0)")
    conn.commit()
    return conn


# Antwort-Bauer für den MockClient – wir ahmen Anthropic-Antwort-Objekte
# mit SimpleNamespace nach (Attribut-Zugriff statt Dict-Zugriff). Das
# macht die Tests gut lesbar und entkoppelt sie von der echten SDK.


def make_text_response(text: str):
    """Antwort mit ``stop_reason='end_turn'`` und einem Textblock."""
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


def make_tool_use_response(
    tool_use_id: str, tool_name: str, tool_input: dict
):
    """Antwort mit ``stop_reason='tool_use'`` und einem Tool-Use-Block."""
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(
                type="tool_use",
                id=tool_use_id,
                name=tool_name,
                input=tool_input,
            )
        ],
    )


def make_multi_tool_use_response(blocks: list[tuple[str, str, dict]]):
    """Antwort mit mehreren Tool-Use-Blöcken in einer einzigen Response.

    ``blocks`` ist eine Liste von Tripeln ``(tool_use_id, tool_name,
    tool_input)``. Anthropic liefert dieses Muster, wenn Claude
    mehrere Tools parallel anfordert.
    """
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(
                type="tool_use",
                id=tool_use_id,
                name=tool_name,
                input=tool_input,
            )
            for tool_use_id, tool_name, tool_input in blocks
        ],
    )


def make_unexpected_response(stop_reason: str = "max_tokens"):
    """Antwort mit unerwartetem Stop-Grund für den defensiven Abbruch."""
    return SimpleNamespace(stop_reason=stop_reason, content=[])


class MockClient:
    """Minimaler Stub für ``anthropic.Anthropic``.

    Liefert vordefinierte Antworten der Reihe nach und protokolliert
    alle Aufrufe samt Argumenten – damit lässt sich verifizieren, dass
    der Loop System-Prompt, Tools und messages korrekt zusammenstellt.
    """

    def __init__(self, responses):
        self._antworten = list(responses)
        self.aufrufe: list[dict] = []
        self.messages = self  # erlaubt client.messages.create(...)

    def create(self, **kwargs):
        self.aufrufe.append(kwargs)
        if not self._antworten:
            raise AssertionError(
                "MockClient: keine Antworten mehr, aber create() wurde "
                "erneut aufgerufen."
            )
        return self._antworten.pop(0)


# ---------------------------------------------------------------------------
# AGENT_SYSTEM_PROMPT
# ---------------------------------------------------------------------------


class TestAgentSystemPrompt:
    def test_normalfall_enthaelt_pflichtstichworte(self):
        # Drei Anker, die der Prompt zwingend enthalten muss, damit
        # Rolle und Sprache eindeutig sind.
        prompt_lower = agent.AGENT_SYSTEM_PROMPT.lower()

        assert "alpenbank" in prompt_lower
        assert "deutsch" in prompt_lower
        assert "assistent" in prompt_lower

    def test_normalfall_erwaehnt_beide_tool_namen(self):
        # Tool-Namen müssen wörtlich auftauchen, damit Claude sie mit
        # den Tool-Definitionen verknüpfen kann.
        assert "dokumenten_suche" in agent.AGENT_SYSTEM_PROMPT
        assert "datenbank_abfrage" in agent.AGENT_SYSTEM_PROMPT

    def test_normalfall_hat_schema_platzhalter(self):
        # Der ``{schema}``-Platzhalter ist die einzige Stelle, an der
        # die DB-Beschreibung pro Konversation eingesetzt wird – ohne
        # ihn würde Claude blind raten.
        assert "{schema}" in agent.AGENT_SYSTEM_PROMPT

    def test_randfall_format_mit_schema_funktioniert(self):
        # str.format darf nicht an unerwarteten geschweiften Klammern
        # scheitern. Ein einfacher Befüllungstest sichert das ab,
        # ohne den eigentlichen Befüllungs-Helper schon zu kennen.
        gefuellt = agent.AGENT_SYSTEM_PROMPT.format(schema="<schema/>")

        assert "{schema}" not in gefuellt
        assert "<schema/>" in gefuellt

    def test_normalfall_verbietet_schreibende_sql_anweisungen(self):
        # Defense in Depth gegenüber der Whitelist: auch der Prompt
        # muss Claude klarmachen, dass DML/DDL tabu sind.
        prompt_upper = agent.AGENT_SYSTEM_PROMPT.upper()

        for keyword in ("INSERT", "UPDATE", "DELETE", "DROP"):
            assert keyword in prompt_upper

    def test_normalfall_geld_format_regel_vorhanden(self):
        # Konsistenz mit Schritt 3: Geldbeträge in deutscher
        # Schreibweise. Ohne diese Regel wechselt Claude oft zu
        # "$123,456.78".
        assert "€" in agent.AGENT_SYSTEM_PROMPT
        assert "deutscher Schreibweise" in agent.AGENT_SYSTEM_PROMPT

    def test_fehlerfall_nicht_leer_und_substanziell(self):
        # Ein versehentlich leerer Prompt würde Claude komplett
        # haltlos machen. 200 Zeichen ist ein bewusst niedriger,
        # aber wirksamer Anti-Regressions-Schwellwert.
        assert agent.AGENT_SYSTEM_PROMPT.strip() != ""
        assert len(agent.AGENT_SYSTEM_PROMPT) >= 200


# ---------------------------------------------------------------------------
# TOOL_DEFINITIONS
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    def test_normalfall_genau_zwei_tools_definiert(self):
        # Schritt 4 sieht exakt zwei Tools vor – mehr wäre Scope-Creep,
        # weniger würde die Agent-Idee aushöhlen.
        assert len(agent.TOOL_DEFINITIONS) == 2

    def test_normalfall_namen_sind_korrekt_und_eindeutig(self):
        namen = [tool["name"] for tool in agent.TOOL_DEFINITIONS]

        assert set(namen) == {"dokumenten_suche", "datenbank_abfrage"}
        # Eindeutigkeit ist Anti-Regression: doppelte Namen würden die
        # Tool-Use-API beim Aufruf sofort scheitern lassen.
        assert len(namen) == len(set(namen))

    def test_randfall_jedes_tool_hat_pflichtfelder(self):
        # Anthropic-API verlangt name, description, input_schema.
        # Fehlt eines, gibt es zur Laufzeit einen kryptischen 400-er.
        for tool in agent.TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_randfall_descriptions_nicht_leer(self):
        # Claude wählt das passende Tool ausschließlich anhand der
        # Beschreibung. Eine leere oder zu kurze Beschreibung führt
        # empirisch zu falscher Tool-Wahl.
        for tool in agent.TOOL_DEFINITIONS:
            assert tool["description"].strip() != ""
            assert len(tool["description"]) >= 50

    def test_randfall_alle_input_schemas_sind_object_schemas(self):
        # Tool-Use-API erwartet zwingend ein JSON-Schema mit
        # type=object auf der obersten Ebene; alles andere wird
        # mit 400 abgelehnt.
        for tool in agent.TOOL_DEFINITIONS:
            schema = tool["input_schema"]
            assert schema["type"] == "object"
            assert "properties" in schema
            assert "required" in schema

    def test_normalfall_dokumenten_suche_hat_frage_als_pflichtfeld(self):
        tool = next(
            t for t in agent.TOOL_DEFINITIONS if t["name"] == "dokumenten_suche"
        )

        assert tool["input_schema"]["required"] == ["frage"]
        assert tool["input_schema"]["properties"]["frage"]["type"] == "string"

    def test_normalfall_datenbank_abfrage_hat_sql_als_pflichtfeld(self):
        tool = next(
            t for t in agent.TOOL_DEFINITIONS if t["name"] == "datenbank_abfrage"
        )

        assert tool["input_schema"]["required"] == ["sql"]
        assert tool["input_schema"]["properties"]["sql"]["type"] == "string"

    def test_fehlerfall_keine_unbekannten_pflichtfelder(self):
        # Jedes 'required'-Feld muss auch in 'properties' deklariert
        # sein – sonst könnte Claude einen Pflicht-Parameter setzen,
        # der nicht typisiert ist, oder die API lehnt ab.
        for tool in agent.TOOL_DEFINITIONS:
            schema = tool["input_schema"]
            for required_feld in schema["required"]:
                assert required_feld in schema["properties"]


# ---------------------------------------------------------------------------
# execute_tool – dokumenten_suche
# ---------------------------------------------------------------------------


class TestExecuteToolDokumentenSuche:
    def test_normalfall_treffer_werden_als_kontext_zurueckgegeben(self):
        treffer = [
            {
                "id": "doc1#0",
                "quelle": "reisekostenrichtlinie.txt",
                "inhalt": "Hotelkategorie maximal vier Sterne.",
                "distanz": 0.12,
            }
        ]
        collection = FakeCollection(make_chroma_antwort(treffer))

        ergebnis = agent.execute_tool(
            "dokumenten_suche",
            {"frage": "Welche Hotelkategorie?"},
            db=None,
            collection=collection,
        )

        assert ergebnis.is_error is False
        assert "Hotelkategorie maximal vier Sterne." in ergebnis.text
        assert "reisekostenrichtlinie.txt" in ergebnis.text
        assert ergebnis.details == treffer

    def test_randfall_leere_treffer_kein_fehler(self):
        # Per Architektur-Skizze A4: keine Treffer ist eine valide
        # Auskunft, kein Fehler. Claude entscheidet selbst, was er
        # damit macht.
        collection = FakeCollection(make_chroma_antwort([]))

        ergebnis = agent.execute_tool(
            "dokumenten_suche",
            {"frage": "Etwas, das nirgends steht"},
            db=None,
            collection=collection,
        )

        assert ergebnis.is_error is False
        assert "keine" in ergebnis.text.lower()
        assert ergebnis.details == []

    def test_fehlerfall_leere_frage(self):
        collection = FakeCollection(make_chroma_antwort([]))

        ergebnis = agent.execute_tool(
            "dokumenten_suche",
            {"frage": "   "},
            db=None,
            collection=collection,
        )

        assert ergebnis.is_error is True
        assert "leer" in ergebnis.text.lower()
        # Bei Eingabe-Fehler darf das Tool die Collection erst gar
        # nicht anfassen – sonst kosten wir das Embedding sinnlos.
        assert collection.aufrufe == []

    def test_fehlerfall_fehlendes_frage_feld(self):
        collection = FakeCollection(make_chroma_antwort([]))

        ergebnis = agent.execute_tool(
            "dokumenten_suche",
            {},
            db=None,
            collection=collection,
        )

        assert ergebnis.is_error is True
        assert collection.aufrufe == []


# ---------------------------------------------------------------------------
# execute_tool – datenbank_abfrage
# ---------------------------------------------------------------------------


class TestExecuteToolDatenbankAbfrage:
    def test_normalfall_select_liefert_markdown_tabelle(self):
        db = make_test_db()
        try:
            ergebnis = agent.execute_tool(
                "datenbank_abfrage",
                {"sql": "SELECT name, betrag FROM konten ORDER BY name"},
                db=db,
                collection=None,
            )
        finally:
            db.close()

        assert ergebnis.is_error is False
        assert "name" in ergebnis.text and "betrag" in ergebnis.text
        assert "Zinsertrag" in ergebnis.text
        assert ergebnis.details["sql"].startswith("SELECT")
        assert "Zinsertrag" in ergebnis.details["tabelle"]

    def test_randfall_select_mit_leerer_ergebnismenge(self):
        db = make_test_db()
        try:
            ergebnis = agent.execute_tool(
                "datenbank_abfrage",
                {"sql": "SELECT name FROM konten WHERE name = 'gibt-es-nicht'"},
                db=db,
                collection=None,
            )
        finally:
            db.close()

        # Leere Ergebnismenge ist kein Fehler – ``format_result_for_claude``
        # liefert "(keine Zeilen)" als expliziten Marker.
        assert ergebnis.is_error is False
        assert "(keine Zeilen)" in ergebnis.text

    def test_fehlerfall_whitelist_verstoss(self):
        db = make_test_db()
        try:
            ergebnis = agent.execute_tool(
                "datenbank_abfrage",
                {"sql": "DELETE FROM konten"},
                db=db,
                collection=None,
            )
        finally:
            db.close()

        assert ergebnis.is_error is True
        assert "sicherheit" in ergebnis.text.lower()
        # Tabelle muss unverändert sein – Whitelist greift vor der
        # Ausführung.
        db2 = make_test_db()
        try:
            anzahl = db2.execute("SELECT COUNT(*) FROM konten").fetchone()[0]
        finally:
            db2.close()
        assert anzahl == 2

    def test_fehlerfall_sqlite_syntax_fehler(self):
        db = make_test_db()
        try:
            ergebnis = agent.execute_tool(
                "datenbank_abfrage",
                {"sql": "SELECT * FROM nicht_existente_tabelle"},
                db=db,
                collection=None,
            )
        finally:
            db.close()

        assert ergebnis.is_error is True
        assert "sqlite" in ergebnis.text.lower()
        assert ergebnis.details["sql"] == "SELECT * FROM nicht_existente_tabelle"

    def test_fehlerfall_leeres_sql(self):
        db = make_test_db()
        try:
            ergebnis = agent.execute_tool(
                "datenbank_abfrage",
                {"sql": "   "},
                db=db,
                collection=None,
            )
        finally:
            db.close()

        assert ergebnis.is_error is True
        assert "leer" in ergebnis.text.lower()


# ---------------------------------------------------------------------------
# execute_tool – Dispatcher-Verhalten
# ---------------------------------------------------------------------------


class TestExecuteToolDispatcher:
    def test_fehlerfall_unbekannter_tool_name(self):
        # Programmierfehler / API-Fehlverhalten – nicht stillschweigend
        # schlucken, sondern lautstark melden.
        with pytest.raises(ValueError, match="Unbekannter Tool-Name"):
            agent.execute_tool(
                "irgendein_falscher_name",
                {"frage": "x"},
                db=None,
                collection=None,
            )


# ---------------------------------------------------------------------------
# answer_question – Multi-Turn-Loop
# ---------------------------------------------------------------------------


class TestAnswerQuestion:
    def test_normalfall_keine_tool_nutzung_direkter_text(self):
        # Claude antwortet sofort ohne Tools (z. B. bei Smalltalk).
        client = MockClient([make_text_response("Hallo, gerne!")])
        collection = FakeCollection(make_chroma_antwort([]))

        antwort = agent.answer_question(
            client,
            frage="Hallo",
            history=[],
            db=None,
            collection=collection,
            schema="<dummy/>",
        )

        assert antwort.text == "Hallo, gerne!"
        assert antwort.traces == []
        assert antwort.iterations_used == 1
        assert len(client.aufrufe) == 1

    def test_normalfall_ein_tool_aufruf_dann_antwort(self):
        # Claude ruft einmal die Doku-Suche auf und antwortet danach.
        treffer = [
            {
                "id": "doc1#0",
                "quelle": "reisekostenrichtlinie.txt",
                "inhalt": "Hotelkategorie maximal vier Sterne.",
                "distanz": 0.1,
            }
        ]
        collection = FakeCollection(make_chroma_antwort(treffer))
        client = MockClient(
            [
                make_tool_use_response(
                    "tu_001",
                    "dokumenten_suche",
                    {"frage": "Welche Hotelkategorie?"},
                ),
                make_text_response(
                    "Maximal vier Sterne (reisekostenrichtlinie.txt)."
                ),
            ]
        )

        antwort = agent.answer_question(
            client,
            frage="Welche Hotelkategorie darf ich buchen?",
            history=[],
            db=None,
            collection=collection,
            schema="<dummy/>",
        )

        assert antwort.iterations_used == 2
        assert len(antwort.traces) == 1
        trace = antwort.traces[0]
        assert trace.name == "dokumenten_suche"
        assert trace.tool_use_id == "tu_001"
        assert trace.tool_input == {"frage": "Welche Hotelkategorie?"}
        assert trace.ergebnis.is_error is False
        assert "vier Sterne" in antwort.text

    def test_randfall_mehrere_tool_use_bloecke_in_einer_antwort(self):
        # Anthropic kann mehrere tool_use-Blöcke in EINER Response
        # liefern, wenn Claude mehrere Tools gleichzeitig braucht. Der
        # Loop muss alle ausführen, beide Traces protokollieren und
        # beide Tool-Results in einer einzigen User-Message
        # zurückschicken (nicht in zwei).
        treffer = [
            {
                "id": "doc1#0",
                "quelle": "kontenplan.txt",
                "inhalt": "Konto X bedeutet Y.",
                "distanz": 0.1,
            }
        ]
        collection = FakeCollection(make_chroma_antwort(treffer))
        db = make_test_db()
        try:
            client = MockClient(
                [
                    make_multi_tool_use_response(
                        [
                            (
                                "tu_a",
                                "datenbank_abfrage",
                                {"sql": "SELECT name FROM konten"},
                            ),
                            (
                                "tu_b",
                                "dokumenten_suche",
                                {"frage": "Konto X"},
                            ),
                        ]
                    ),
                    make_text_response("Beide Antworten kombiniert."),
                ]
            )

            antwort = agent.answer_question(
                client,
                frage="Was sagt das Konto X aus und wie heißen unsere Konten?",
                history=[],
                db=db,
                collection=collection,
                schema="<dummy/>",
            )
        finally:
            db.close()

        # Beide Traces in der Reihenfolge der Blöcke.
        assert [t.tool_use_id for t in antwort.traces] == ["tu_a", "tu_b"]
        assert antwort.iterations_used == 2

        # Zweiter API-Aufruf: messages enthält genau EINE User-Message
        # mit beiden tool_result-Blöcken.
        zweiter_aufruf = client.aufrufe[1]
        letzte_msg = zweiter_aufruf["messages"][-1]
        assert letzte_msg["role"] == "user"
        results = letzte_msg["content"]
        assert len(results) == 2
        assert {r["tool_use_id"] for r in results} == {"tu_a", "tu_b"}
        assert all(r["type"] == "tool_result" for r in results)
        assert all(r["is_error"] is False for r in results)

    def test_normalfall_zwei_sequenzielle_tool_aufrufe(self):
        # Erst SQL, dann RAG – wie bei einer kombinierten Demo-Frage.
        treffer = [
            {
                "id": "doc1#0",
                "quelle": "kostenstellenhandbuch.txt",
                "inhalt": "Allokationsregel X",
                "distanz": 0.2,
            }
        ]
        collection = FakeCollection(make_chroma_antwort(treffer))
        db = make_test_db()
        try:
            client = MockClient(
                [
                    make_tool_use_response(
                        "tu_001",
                        "datenbank_abfrage",
                        {"sql": "SELECT name, betrag FROM konten"},
                    ),
                    make_tool_use_response(
                        "tu_002",
                        "dokumenten_suche",
                        {"frage": "Allokationsregel"},
                    ),
                    make_text_response("Antwort kombiniert."),
                ]
            )

            antwort = agent.answer_question(
                client,
                frage="Warum ist der Aufwand gestiegen?",
                history=[],
                db=db,
                collection=collection,
                schema="<dummy/>",
            )
        finally:
            db.close()

        assert antwort.iterations_used == 3
        assert [t.name for t in antwort.traces] == [
            "datenbank_abfrage",
            "dokumenten_suche",
        ]
        assert antwort.text == "Antwort kombiniert."

    def test_randfall_iterationslimit_erreicht(self):
        # Claude ruft endlos Tools auf – Loop muss abbrechen.
        treffer = [
            {
                "id": "x",
                "quelle": "q",
                "inhalt": "Inhalt",
                "distanz": 0.5,
            }
        ]
        collection = FakeCollection(make_chroma_antwort(treffer))
        # Drei Iterationen erlaubt → drei Tool-Use-Antworten reichen
        # für ein erreichtes Limit.
        client = MockClient(
            [
                make_tool_use_response(
                    f"tu_{i}", "dokumenten_suche", {"frage": "x"}
                )
                for i in range(3)
            ]
        )

        antwort = agent.answer_question(
            client,
            frage="x",
            history=[],
            db=None,
            collection=collection,
            schema="<dummy/>",
            max_iterations=3,
        )

        assert antwort.iterations_used == 3
        assert len(antwort.traces) == 3
        assert "Iterationslimit" in antwort.text

    def test_normalfall_tool_fehler_wird_an_claude_zurueckgegeben(self):
        # SQL-Tool antwortet mit is_error=True – im nächsten API-
        # Aufruf muss der tool_result-Block dieses Flag tragen.
        db = make_test_db()
        try:
            client = MockClient(
                [
                    make_tool_use_response(
                        "tu_001",
                        "datenbank_abfrage",
                        {"sql": "DELETE FROM konten"},
                    ),
                    make_text_response("Diese Anfrage wird abgelehnt."),
                ]
            )

            antwort = agent.answer_question(
                client,
                frage="Lösch alles",
                history=[],
                db=db,
                collection=None,
                schema="<dummy/>",
            )
        finally:
            db.close()

        assert antwort.traces[0].ergebnis.is_error is True
        # Zweiter API-Aufruf: messages enthält am Ende einen tool_result
        # mit is_error=True.
        zweiter_aufruf = client.aufrufe[1]
        letzte_msg = zweiter_aufruf["messages"][-1]
        assert letzte_msg["role"] == "user"
        tool_result = letzte_msg["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["is_error"] is True
        assert tool_result["tool_use_id"] == "tu_001"

    def test_randfall_history_wird_nicht_mutiert(self):
        original_history = [
            {"role": "user", "content": "frühere Frage"},
            {"role": "assistant", "content": "frühere Antwort"},
        ]
        # Bewusste tiefe Kopie für den Vergleich – wir wollen sehen,
        # dass weder Liste noch Inhalte mutiert wurden.
        snapshot = [dict(m) for m in original_history]

        client = MockClient([make_text_response("ok")])

        agent.answer_question(
            client,
            frage="neue Frage",
            history=original_history,
            db=None,
            collection=None,
            schema="<dummy/>",
        )

        assert original_history == snapshot

    def test_normalfall_schema_wird_in_system_prompt_eingesetzt(self):
        client = MockClient([make_text_response("ok")])

        agent.answer_question(
            client,
            frage="x",
            history=[],
            db=None,
            collection=None,
            schema="<MEIN-SCHEMA-MARKER/>",
        )

        system_arg = client.aufrufe[0]["system"]
        assert "<MEIN-SCHEMA-MARKER/>" in system_arg
        assert "{schema}" not in system_arg
        # Tools müssen ebenfalls beim Aufruf mitgegeben werden.
        assert client.aufrufe[0]["tools"] == agent.TOOL_DEFINITIONS

    def test_fehlerfall_unerwarteter_stop_reason(self):
        client = MockClient([make_unexpected_response("max_tokens")])

        antwort = agent.answer_question(
            client,
            frage="x",
            history=[],
            db=None,
            collection=None,
            schema="<dummy/>",
        )

        assert antwort.iterations_used == 1
        assert antwort.traces == []
        assert "max_tokens" in antwort.text

    def test_fehlerfall_leere_frage(self):
        # Anti-Regression für den Eingabe-Check oben in answer_question.
        client = MockClient([])

        with pytest.raises(ValueError, match="leer"):
            agent.answer_question(
                client,
                frage="   ",
                history=[],
                db=None,
                collection=None,
                schema="<dummy/>",
            )
