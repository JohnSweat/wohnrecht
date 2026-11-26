"""Gemeinsame Hilfen für die Browsertests (Windows, macOS und Linux).

Browser: Umgebungsvariable CHROME_PFAD (oder CHROME), sonst ein vorhandenes Chrome bzw. Chromium an
bekannten Stellen, sonst der Standardbrowser von Playwright.
"""
import os
import pathlib
import tempfile

BEKANNTE_BROWSER = ["/usr/bin/google-chrome", "/opt/pw-browsers/chromium"]


def chrome_optionen() -> dict:
    """Argumente für chromium.launch(): headless, mit executable_path nur, wenn ein Pfad bekannt ist."""
    pfad = os.environ.get("CHROME_PFAD") or os.environ.get("CHROME")
    if not pfad:
        pfad = next((p for p in BEKANNTE_BROWSER if pathlib.Path(p).exists()), None)
    return {"headless": True, **({"executable_path": pfad} if pfad else {})}


def ausgabeordner(argument: str | None, name: str) -> pathlib.Path:
    """Ausgabeordner aus dem Aufruf, sonst ein Ordner im Temp-Verzeichnis des Systems."""
    aus = pathlib.Path(argument) if argument else pathlib.Path(tempfile.gettempdir()) / name
    aus.mkdir(parents=True, exist_ok=True)
    return aus
