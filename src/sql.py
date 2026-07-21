"""SQL-Logik für den Alpenbank-Assistenten (Schritt 3).

Dieses Modul kapselt den Lesezugriff auf die Controlling-Datenbank:
Verbindungsaufbau (read-only), Schema-Beschreibung für Claude,
Whitelist-Validierung und Ausführung von SELECT-Abfragen. Bewusst
frei von Streamlit- und Anthropic-Code, damit jede Funktion einzeln
und ohne UI / API-Key testbar ist.

Wir öffnen die Datenbank konsequent im Read-Only-Modus per SQLite-URI.
Der Schutz auf DB-Ebene ist die zweite Verteidigungslinie – die erste
ist die SELECT-Whitelist im Validator. Beide Linien zusammen verhindern,
dass eine durch Claude erzeugte oder von einem Nutzer eingegebene
Schreib-Anweisung versehentlich Daten verändert.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, NamedTuple


class QueryResult(NamedTuple):
    """Ergebnis einer SELECT-Abfrage in zwei Sichten.

    ``rows`` ist eine Liste von Dicts (Spalte -> Wert) und damit direkt
    iterier- und filterbar. ``columns`` hält die Spaltennamen separat,
    damit auch ein leeres Ergebnis (``rows=[]``) noch das Schema der
    Abfrage trägt – das brauchen Anzeige und Formatierung.
    """

    rows: list[dict[str, Any]]
    columns: list[str]

# Anzahl Beispielzeilen, die wir Claude pro Tabelle zeigen. Zwei reichen,
# damit Claude die typischen Wertebereiche erkennt (z. B. dass typ in
# konten nur "Ertrag" oder "Aufwand" ist), ohne unnötig Tokens zu
# verbrennen.
BEISPIELZEILEN_PRO_TABELLE = 2

# Hartes Limit für die Anzahl Zeilen, die wir Claude zur Antwort-
# Formulierung zeigen. Bei aggregierten Fragen (SUM, COUNT, GROUP BY)
# kommen ohnehin wenige Zeilen zurück; bei flachen SELECTs würde eine
# Tabelle mit 2000 Buchungen den Token-Verbrauch explodieren lassen,
# ohne Mehrwert für die Antwort. Claude soll zusammenfassen, nicht
# vorlesen.
MAX_ZEILEN_FUER_CLAUDE = 50

# Schlüsselwörter, die schreiben oder die Datenbank manipulieren. Ein
# einzelnes Vorkommen als Top-Level-Token (außerhalb von String-Literalen
# und Kommentaren) genügt, um das Statement zu blockieren. PRAGMA und
# ATTACH/DETACH sind technisch nicht immer schreibend, eröffnen aber
# Wege zur Manipulation des DB-Verhaltens und werden deshalb ebenfalls
# abgelehnt.
VERBOTENE_KEYWORDS = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "CREATE",
        "ALTER",
        "REPLACE",
        "TRUNCATE",
        "PRAGMA",
        "ATTACH",
        "DETACH",
        "VACUUM",
        "REINDEX",
        "ANALYZE",
    }
)

# Erlaubte Anfangs-Keywords. WITH ist nötig, damit Common Table
# Expressions (CTEs) funktionieren – die werden bei komplexeren
# Auswertungen erfahrungsgemäß von Claude erzeugt.
ERLAUBTE_START_KEYWORDS = frozenset({"SELECT", "WITH"})

# SQL-Kommentar-Formen: Zeilen-Kommentar (-- bis Zeilenende) und
# Block-Kommentar (/* ... */, auch über Zeilen). re.DOTALL, damit
# . in Block-Kommentaren auch Zeilenumbrüche frisst.
_KOMMENTAR_REGEX = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)

# Einfache String-Literale. Reicht für unsere Demo-Queries; kennt
# bewusst keine Escape-Quotes ('don''t'), weil das die Komplexität
# verdoppeln würde, ohne Sicherheitsgewinn für Bank-Daten zu liefern.
_STRING_LITERAL_REGEX = re.compile(r"'[^']*'")

# Markdown-Codeblock mit optionaler Sprachkennung. Wir tolerieren
# bewusst auch ``` ohne "sql", weil Claude die Sprachkennung manchmal
# weglässt – obwohl der System-Prompt sie verlangt.
_CODEBLOCK_REGEX = re.compile(
    r"```(?:sql)?\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Öffnet die SQLite-Datenbank read-only und gibt die Verbindung zurück.

    Read-Only-Modus per URI (``mode=ro``): SQLite verweigert dann jeden
    Schreibvorgang auf Connection-Ebene. Damit ist – selbst wenn die
    SELECT-Whitelist eines Tages umgangen würde – die Datenbank durch
    eine Claude-Antwort nicht veränderbar.

    Wirft ``ValueError`` bei leerem oder ``None``-Pfad und
    ``FileNotFoundError`` bei fehlender Datei. Beide Fälle prüfen wir
    explizit, weil SQLite sonst erst beim ersten Befehl mit einem
    kryptischen ``OperationalError`` abbricht.
    """
    if db_path is None or (isinstance(db_path, str) and db_path.strip() == ""):
        raise ValueError("db_path darf nicht leer sein.")

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"SQLite-Datei nicht gefunden: {path}. "
            "Bitte zuerst `python scripts/daten_erzeugen.py` ausführen."
        )

    # as_posix() wandelt Windows-Backslashes in Forward-Slashes, die
    # SQLite in URIs verlangt. Ohne diese Umwandlung schlägt der Aufbau
    # auf Windows mit "unable to open database file" fehl.
    uri = f"file:{path.as_posix()}?mode=ro"
    # check_same_thread=False: Streamlit re-runt das App-Skript bei
    # jedem Event in einem anderen Thread, würde aber dieselbe gecachte
    # Connection wiederverwenden. Da wir read-only sind, ist gleichzeitiges
    # Lesen aus mehreren Threads ungefährlich – die SQLite-Default-
    # Restriktion brauchen wir hier also nicht.
    return sqlite3.connect(uri, uri=True, check_same_thread=False)


def _quote_identifier(name: str) -> str:
    """Kapselt einen Tabellennamen sicher für eine SQL-Abfrage.

    SQLite erlaubt jeden Tabellennamen in doppelten Anführungszeichen;
    enthaltene ``"`` werden durch Verdoppelung escaped. Für unsere
    Bank-DB ist das überflüssig, aber das Pattern ist Standardpraxis
    und schützt vor unangenehmen Überraschungen, falls eine Tabelle
    irgendwann ungewöhnlich benannt wird.
    """
    return '"' + name.replace('"', '""') + '"'


def _format_beispielzeile(spalten: list[str], werte: tuple[Any, ...]) -> str:
    """Formatiert eine Datenzeile als ``(spalte=wert, ...)``-String.

    ``repr()`` setzt String-Werte automatisch in Anführungszeichen und
    lässt Zahlen unverändert – das macht den Output für Claude direkt
    lesbar, ohne dass wir Typunterscheidungen selbst implementieren.
    """
    paare = [f"{spalte}={repr(wert)}" for spalte, wert in zip(spalten, werte)]
    return "(" + ", ".join(paare) + ")"


def build_schema_description(connection: sqlite3.Connection) -> str:
    """Baut eine XML-strukturierte Schema-Beschreibung für Claude.

    Liest alle Nutzer-Tabellen aus ``sqlite_master`` (interne
    ``sqlite_*``-Tabellen werden gefiltert) und gibt pro Tabelle die
    DDL plus zwei Beispielzeilen aus. Claude soll daraus erkennen
    können, welche Tabellen existieren, welche Spalten sie haben und
    welche Wertebereiche typisch sind.

    Format-Wahl XML: konsistent zur Kontext-Übergabe in
    ``rag.format_context`` – Anthropic empfiehlt XML-Tags, weil Claude
    sie zuverlässig erkennt. Eine leere Datenbank liefert eine leere,
    aber gültige Hülle ``<datenbank></datenbank>`` zurück; das macht
    den Aufrufer-Code einfacher als ein Sonderfall mit ``None``.

    Wirft ``ValueError`` bei ``None`` als Verbindung – ein klarer
    Programmierfehler, den wir nicht stillschweigend übergehen.
    """
    if connection is None:
        raise ValueError("connection darf nicht None sein.")

    # Nur "echte" Nutzer-Tabellen. Views und SQLite-interne Tabellen
    # (sqlite_sequence, sqlite_stat1 etc.) blenden wir aus, weil sie
    # für die Beantwortung fachlicher Fragen irrelevant sind und die
    # Schema-Beschreibung nur unnötig aufblähen würden.
    cursor = connection.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    )
    tabellen = cursor.fetchall()

    if not tabellen:
        return "<datenbank></datenbank>"

    bloecke: list[str] = ["<datenbank>"]
    for name, ddl in tabellen:
        # Spaltennamen via PRAGMA holen – funktioniert auch dann, wenn
        # die Tabelle leer ist (anders als cursor.description nach einem
        # SELECT erst nach fetchone()).
        spalten_info = connection.execute(
            f"PRAGMA table_info({_quote_identifier(name)})"
        ).fetchall()
        spalten = [zeile[1] for zeile in spalten_info]

        beispielzeilen_cursor = connection.execute(
            f"SELECT * FROM {_quote_identifier(name)} "
            f"LIMIT {BEISPIELZEILEN_PRO_TABELLE}"
        )
        zeilen = beispielzeilen_cursor.fetchall()

        if zeilen:
            beispiel_block = "\n".join(
                _format_beispielzeile(spalten, zeile) for zeile in zeilen
            )
        else:
            beispiel_block = "(keine Daten)"

        bloecke.append(
            f'  <tabelle name="{name}">\n'
            f"    <ddl>{ddl}</ddl>\n"
            f"    <beispielzeilen>\n{beispiel_block}\n    </beispielzeilen>\n"
            f"  </tabelle>"
        )

    bloecke.append("</datenbank>")
    return "\n".join(bloecke)


def is_safe_select(sql_text: str) -> bool:
    """Prüft, ob ``sql_text`` ein einzelnes, lesendes SELECT-Statement ist.

    Erlaubt:
      * SELECT-Statements und WITH-CTE-Abfragen
      * Optionales Trailing-Semikolon und führende SQL-Kommentare
      * Beliebige Whitespace- oder Groß-/Kleinschreibung

    Abgelehnt:
      * Jede Form von DML/DDL (INSERT/UPDATE/DELETE/DROP/CREATE/...)
      * PRAGMA, ATTACH, DETACH, VACUUM, REINDEX, ANALYZE
      * Mehrfach-Statements (Semikolon mit Folge-Inhalt)
      * Leere oder reine Whitespace-Eingaben

    Konservativer Filter: Wir lehnen Eingaben ab, in denen ein
    verbotenes Keyword als Token außerhalb von Kommentaren und
    String-Literalen vorkommt – auch dann, wenn es syntaktisch
    harmlos wäre. Lieber falsche Ablehnung als falsches Durchwinken,
    weil diese Funktion die letzte Verteidigungslinie vor der
    Read-Only-Verbindung ist.

    Wirft ``ValueError`` nur bei ``None`` oder Nicht-String – das
    wäre ein Programmierfehler. Leere oder syntaktisch ungültige
    Strings liefern ``False``, weil sie inhaltlich kein gültiges
    SELECT sind.
    """
    if sql_text is None or not isinstance(sql_text, str):
        raise ValueError("sql_text muss ein String sein.")

    # Kommentare und String-Literale neutralisieren, damit verbotene
    # Wörter darin (z. B. ein Kostenstellen-Name "Update" oder ein
    # Kommentar "-- DELETE later") das echte SELECT nicht blockieren.
    bereinigt = _KOMMENTAR_REGEX.sub(" ", sql_text)
    bereinigt = _STRING_LITERAL_REGEX.sub("''", bereinigt)

    # Trailing-Semikolon ist erlaubt, alles andere danach wäre ein
    # zweites Statement und damit unsafe.
    bereinigt = bereinigt.strip().rstrip(";").strip()

    if not bereinigt:
        return False

    if ";" in bereinigt:
        return False

    # \w-Tokens reichen für unsere Zwecke: SQL-Schlüsselwörter und
    # Bezeichner bestehen nur aus ASCII-Wortzeichen. Operatoren
    # interessieren uns hier nicht.
    tokens = re.findall(r"\w+", bereinigt)
    if not tokens:
        return False

    if tokens[0].upper() not in ERLAUBTE_START_KEYWORDS:
        return False

    upper_tokens = {token.upper() for token in tokens}
    if upper_tokens & VERBOTENE_KEYWORDS:
        return False

    return True


def run_select(
    connection: sqlite3.Connection, sql_text: str
) -> QueryResult:
    """Führt ein SELECT-Statement aus und gibt das Ergebnis strukturiert zurück.

    Vorbedingung: ``is_safe_select(sql_text)`` muss True sein. Sonst
    wirft die Funktion ``ValueError`` und das Statement landet gar
    nicht erst an der Datenbank. Das ist die zentrale Stelle, an der
    Whitelist und DB-Zugriff zusammenfinden.

    SQL-Syntaxfehler oder Verweise auf nicht existierende Tabellen
    führen zu ``sqlite3.OperationalError`` – diesen Fehler reichen wir
    bewusst durch, damit der Aufrufer (in der UI) eine echte
    SQLite-Fehlermeldung anzeigen kann. So sieht der Nutzer, *warum*
    die Abfrage scheiterte, statt einer generischen Fehlermeldung.

    Wirft ``ValueError`` bei ``None``-Verbindung oder unsafe Statement.
    """
    if connection is None:
        raise ValueError("connection darf nicht None sein.")

    if not is_safe_select(sql_text):
        raise ValueError(
            f"Statement nicht erlaubt (Whitelist verletzt): {sql_text!r}"
        )

    cursor = connection.execute(sql_text)

    # cursor.description ist None für DDL-Statements – das wird hier
    # eigentlich nicht passieren, weil is_safe_select solche Anweisungen
    # vorher abfängt. Wir behandeln den Fall trotzdem defensiv, damit
    # der Code bei einem hypothetischen Bypass nicht crasht.
    columns = (
        [beschreibung[0] for beschreibung in cursor.description]
        if cursor.description
        else []
    )
    rows = [dict(zip(columns, zeile)) for zeile in cursor.fetchall()]
    return QueryResult(rows=rows, columns=columns)


def extract_sql_from_response(antwort_text: str) -> str:
    """Holt das SQL-Statement aus einer Claude-Antwort.

    Drei akzeptierte Formen:
      * `````sql\\n...\\n````` (bevorzugt, wie im System-Prompt verlangt)
      * `````\\n...\\n````` (Codeblock ohne Sprachkennung)
      * Nackter SQL-Text ohne Codeblock (Fallback)

    Findet die Funktion einen Codeblock, nimmt sie dessen Inhalt –
    auch wenn rundherum noch Erklärungstext steht. Das ist die
    typische Form, in der Claude antwortet, wenn der System-Prompt
    eingehalten wird.

    Nach der Extraktion prüfen wir heuristisch, ob der Inhalt
    überhaupt mit ``SELECT`` oder ``WITH`` beginnt. Wenn nicht, war
    die Antwort offensichtlich kein SQL (z. B. eine ehrliche
    "kann ich nicht beantworten"-Antwort von Claude). Dann werfen
    wir ``ValueError`` mit einem Auszug der Antwort, damit der
    Aufrufer dem Nutzer zeigen kann, was Claude stattdessen gesagt
    hat.

    Wirft ``ValueError`` bei leerer oder Nicht-String-Eingabe sowie
    bei Antworten ohne erkennbares SELECT/WITH.
    """
    if not isinstance(antwort_text, str) or antwort_text.strip() == "":
        raise ValueError("antwort_text darf nicht leer sein.")

    treffer = _CODEBLOCK_REGEX.search(antwort_text)
    sql_text = treffer.group(1).strip() if treffer else antwort_text.strip()

    if not re.match(r"^\s*(SELECT|WITH)\b", sql_text, re.IGNORECASE):
        # Kein SELECT/WITH-Anfang -> Claude hat keine Abfrage geliefert.
        # Wir geben den Originaltext (gekürzt) im Fehler mit, damit der
        # Aufrufer ihn dem Nutzer als Erklärung zeigen kann.
        auszug = antwort_text.strip()
        if len(auszug) > 200:
            auszug = auszug[:200] + " …"
        raise ValueError(
            f"Antwort enthält kein erkennbares SELECT/WITH: {auszug}"
        )

    return sql_text


def _format_zelle(wert: Any) -> str:
    """Wandelt einen Datenwert in eine Markdown-tabellenfähige Zelle.

    None wird zu ``NULL`` (klar erkennbar in der Tabelle), Pipe-Zeichen
    in Strings werden escaped, weil sie sonst die Tabellenstruktur
    zerschießen würden.
    """
    if wert is None:
        return "NULL"
    return str(wert).replace("|", r"\|")


def format_result_for_claude(
    rows: list[dict[str, Any]], columns: list[str]
) -> str:
    """Formatiert ein Query-Ergebnis als Markdown-Tabelle für Claude.

    Markdown-Tabellen versteht Claude zuverlässig und sie sind beim
    Debuggen direkt lesbar. Größere Ergebnismengen werden auf
    ``MAX_ZEILEN_FUER_CLAUDE`` begrenzt mit deutlichem Hinweis auf
    abgeschnittene Zeilen – sonst würde der zweite Claude-Aufruf
    unnötig viele Tokens verbrennen.

    Bei leerer Zeilenliste geben wir Kopfzeile plus den Marker
    ``(keine Zeilen)`` zurück. Damit weiß Claude, dass die Abfrage
    technisch erfolgreich war, aber kein Treffer kam – das ist eine
    inhaltlich andere Antwort als ein Fehler und muss
    unterscheidbar bleiben.

    Wirft ``ValueError`` bei leerer Spaltenliste – ohne Spalten
    wäre die Tabelle bedeutungslos.
    """
    if not columns:
        raise ValueError("columns darf nicht leer sein.")

    kopf = "| " + " | ".join(columns) + " |"
    trenner = "| " + " | ".join("---" for _ in columns) + " |"

    if not rows:
        return f"{kopf}\n{trenner}\n(keine Zeilen)"

    abgeschnitten = len(rows) > MAX_ZEILEN_FUER_CLAUDE
    sichtbare_zeilen = (
        rows[:MAX_ZEILEN_FUER_CLAUDE] if abgeschnitten else rows
    )

    daten_zeilen = [
        "| "
        + " | ".join(_format_zelle(zeile.get(spalte)) for spalte in columns)
        + " |"
        for zeile in sichtbare_zeilen
    ]

    ausgabe_teile = [kopf, trenner, *daten_zeilen]

    if abgeschnitten:
        rest = len(rows) - MAX_ZEILEN_FUER_CLAUDE
        ausgabe_teile.append(f"(weitere {rest} Zeilen abgeschnitten)")

    return "\n".join(ausgabe_teile)
