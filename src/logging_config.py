"""Zentrales Logging-Setup für den Alpenbank-Assistenten.

Ersetzt ad-hoc ``print``-Aufrufe und das Leaken von Rohfehlern ins UI
(vgl. ``src/app.py``). Level ist über die Umgebungsvariable
``LOG_LEVEL`` steuerbar (Default: INFO), damit sich der Detailgrad ohne
Code-Änderung anpassen lässt (z. B. DEBUG für lokale Fehlersuche).
"""

from __future__ import annotations

import logging
import os

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def setup_logging() -> None:
    """Konfiguriert das Root-Logging einmalig.

    Idempotent: mehrfache Aufrufe (z. B. durch Streamlits Re-Runs)
    fügen keine doppelten Handler hinzu.
    """
    root = logging.getLogger()
    if root.handlers:
        return

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(level=level, format=_LOG_FORMAT)
