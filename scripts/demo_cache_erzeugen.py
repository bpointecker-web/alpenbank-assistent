"""Erzeugt den Demo-Cache für den kostenlosen, öffentlichen Demo-Modus.

Führt alle zehn Demo-Fragen (``src.demo.DEMO_FRAGEN``) einmal live über
den echten Agenten (``agent.answer_question``) mit einem gültigen
``ANTHROPIC_API_KEY`` aus und schreibt die vollständigen Antworten
(Text, Tool-Traces, Quellen, ausgeführtes SQL) nach
``data/demo_cache.json``.

Dieser Cache wird von ``src/app.py`` im Demo-Modus
(``ALPENBANK_DEMO_MODE=1``) abgespielt, ohne dass dort ein API-Key
oder eine Live-Verbindung zu Claude nötig ist. Das Skript selbst
braucht beides – es ist der einzige Ort, an dem für den Demo-Modus
echte API-Kosten anfallen (einmalig, zehn Anfragen).

Voraussetzungen wie bei der App:
    data/chroma/         (python scripts/rag_index.py)
    data/controlling.db  (python scripts/daten_erzeugen.py)
    .env mit ANTHROPIC_API_KEY

Aufruf aus dem Projekt-Root:
    .venv/Scripts/python.exe scripts/demo_cache_erzeugen.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Projekt-Root in den Importpfad aufnehmen, damit "from src import ..."
# auch beim direkten Skript-Aufruf funktioniert.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402
from anthropic import Anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from src import agent, demo, rag, sql  # noqa: E402

CHROMA_PATH = Path("data/chroma")
CONTROLLING_PATH = Path("data/controlling.db")


def main() -> None:
    load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY ist nicht gesetzt. Der Demo-Cache braucht "
            "einen echten Key, um die Antworten einmalig live zu erzeugen."
        )

    client = Anthropic(api_key=api_key)

    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = rag.create_collection(chroma_client, name=rag.COLLECTION_NAME)

    connection = sql.connect(str(CONTROLLING_PATH))
    schema = sql.build_schema_description(connection)

    eintraege: list[dict] = []
    for index, frage in enumerate(demo.DEMO_FRAGEN, start=1):
        print(f"[{index}/{len(demo.DEMO_FRAGEN)}] {frage}")
        antwort = agent.answer_question(
            client,
            frage=frage,
            history=[],
            db=connection,
            collection=collection,
            schema=schema,
        )
        eintraege.append({"frage": frage, **demo.serialize_antwort(antwort)})
        print(f"    -> {len(antwort.traces)} Tool-Aufruf(e), Antwort erhalten.")

    demo.DEMO_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    demo.DEMO_CACHE_PATH.write_text(
        json.dumps(eintraege, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nDemo-Cache geschrieben nach {demo.DEMO_CACHE_PATH}")


if __name__ == "__main__":
    main()
