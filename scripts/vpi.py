#!/usr/bin/env python3
"""Verbraucherpreisindex (VPI) von Statistik Austria für den Indexrechner.

Lädt für alle VPI-Basen (VPI 2025 bis VPI I/II 1958) und den HVPI 2025 die Monatswerte des Gesamtindex
aus den Open-Data-Dateien von Statistik Austria und schreibt data/vpi.json. Vorläufige Werte sind in der
Zeitliste mit „(vorl.)“ gekennzeichnet und werden mitgeschrieben.

Quelle: Statistik Austria, data.statistik.gv.at, Lizenz CC BY 4.0.
Aufruf: python scripts/vpi.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

BASIS = pathlib.Path(__file__).resolve().parent.parent
QUELLE = "https://data.statistik.gv.at/data/"
UA = "wohnrecht/1.0 (+https://github.com/JohnSweat/wohnrecht; nicht-kommerzielles Nachschlagewerk, Abruf einmal pro Woche)"

# Schlüssel, Anzeigename, Dateistamm (ohne .csv)[, freiwillig]; neueste Basis zuerst.
# Freiwillige Reihen: Fällt der Abruf aus, gilt der bisherige Stand, der Lauf scheitert deshalb aber nicht.
BASEN = [
    ("2025", "VPI 2025", "OGD_vpi25c18_VPI_2025COICOP18_1"),
    ("2020", "VPI 2020", "OGD_vpi20c18_VPI_2020COICOP18_1"),
    ("2015", "VPI 2015", "OGD_vpi15c18_VPI_2015COICOP18_1"),
    ("2010", "VPI 2010", "OGD_vpi10c18_VPI_2010COICOP18_1"),
    ("2005", "VPI 2005", "OGD_vpi05c18_VPI_2005COICOP18_1"),
    ("2000", "VPI 2000", "OGD_vpi00_VPI_2000_1"),
    ("1996", "VPI 1996", "OGD_vpi96_VPI_1996_1"),
    ("1986", "VPI 1986", "OGD_vpi86_VPI_1986_1"),
    ("1976", "VPI 1976", "OGD_vpi76_VPI_1976_1"),
    ("1966", "VPI 1966", "OGD_vpi66_VPI_1966_1"),
    ("1958i", "VPI I 1958", "OGD_vpi58_VPI_1958_i_1"),
    ("1958ii", "VPI II 1958", "OGD_vpi58ii_VPI_1958_ii_1"),
    # Harmonisierter VPI (gleiches Dateiformat; Gesamtindex „HVPI-0“); Wertsicherungen können auch an ihm hängen
    ("hvpi2025", "HVPI 2025", "OGD_hvpi25_HVD_HVPI_2025_1", True),
]


def hole(url: str, versuche: int = 4) -> bytes:
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers={"Accept": "text/csv,*/*", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as err:
            if i == versuche - 1 or (isinstance(err, urllib.error.HTTPError) and err.code not in (429, 500, 502, 503, 504)):
                raise
            time.sleep(5 * (i + 1))
    raise RuntimeError("Abruf fehlgeschlagen")


def monat(code: str) -> str | None:
    """VPIZR-202610 -> 2026-10"""
    c = code.strip()
    if not c.startswith("VPIZR-") or len(c) != 12 or not c[6:].isdigit():
        return None
    return f"{c[6:10]}-{c[10:12]}"


def lies_reihe(daten: bytes) -> dict[str, float]:
    """Gesamtindex (Klassifikationscode endet auf „-0“) je Monat aus der Hauptdatei."""
    zeilen = daten.decode("utf-8-sig", "replace").splitlines()
    kopf = [k.strip() for k in zeilen[0].split(";")]
    try:
        i_zeit, i_wert = kopf.index("C-VPIZR-0"), kopf.index("F-VPIMZBM")
    except ValueError:
        raise ValueError(f"unerwarteter Dateikopf: {zeilen[0][:120]}")
    i_klasse = next(i for i, k in enumerate(kopf) if k.startswith("C-") and i != i_zeit)
    werte = {}
    for z in zeilen[1:]:
        f = z.split(";")
        if len(f) <= max(i_zeit, i_wert, i_klasse) or not f[i_klasse].strip().endswith("-0"):
            continue
        m, w = monat(f[i_zeit]), f[i_wert].strip().replace(",", ".")
        if m and w:
            werte[m] = round(float(w), 5)
    return werte


def lies_vorlaeufig(daten: bytes) -> set[str]:
    """Monate, die in der Zeitliste als vorläufig („(vorl.)“) gekennzeichnet sind."""
    vorl = set()
    for z in daten.decode("utf-8-sig", "replace").splitlines()[1:]:
        f = z.split(";")
        if len(f) > 1 and "vorl" in f[1].lower() and monat(f[0]):
            vorl.add(monat(f[0]))
    return vorl


def folge(von: str, bis: str) -> list[str]:
    j, m = int(von[:4]), int(von[5:])
    aus = []
    while f"{j:04d}-{m:02d}" <= bis:
        aus.append(f"{j:04d}-{m:02d}")
        j, m = (j + 1, 1) if m == 12 else (j, m + 1)
    return aus


def als_reihe(key: str, name: str, werte: dict[str, float]) -> dict:
    """Lückenlose Monatsfolge ab dem ersten Wert; fehlende Monate als null."""
    von, bis = min(werte), max(werte)
    return {"key": key, "name": name, "von": von, "bis": bis, "werte": [werte.get(m) for m in folge(von, bis)]}


def plausibel(werte: dict[str, float], heute: dt.date) -> str | None:
    if len(werte) < 6:
        return f"nur {len(werte)} Monatswerte"
    if any(w is None or w <= 0 for w in werte.values()):
        return "Werte ≤ 0"
    letzter = dt.date(int(max(werte)[:4]), int(max(werte)[5:]), 1)
    if (heute - letzter).days > 150:
        return f"letzter Wert {max(werte)} ist zu alt"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VPI-Reihen von Statistik Austria laden.")
    ap.add_argument("--basis", default=str(BASIS), help=argparse.SUPPRESS)
    ap.add_argument("--quelle", default=QUELLE, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    pfad = pathlib.Path(args.basis) / "data" / "vpi.json"
    alt = json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else {}
    alte_reihen = {r["key"]: r for r in alt.get("reihen", [])}
    heute = dt.datetime.now(dt.timezone.utc).date()
    reihen, vorlaeufig, fehler = [], set(alt.get("vorlaeufig", [])), []
    neu_geladen = False
    for key, name, stamm, *frei in BASEN:
        try:
            werte = lies_reihe(hole(args.quelle + stamm + ".csv"))
            grund = plausibel(werte, heute)
            if grund:
                raise ValueError(grund)
            vorl = lies_vorlaeufig(hole(args.quelle + stamm + "_C-VPIZR-0.csv"))
            if not neu_geladen:
                vorlaeufig, neu_geladen = set(), True
            vorlaeufig |= {m for m in vorl if m in werte}
            reihen.append(als_reihe(key, name, werte))
            print(f"{name}: {len(werte)} Monate, {min(werte)} bis {max(werte)}, zuletzt {werte[max(werte)]}"
                  + (f" (vorläufig: {', '.join(sorted(vorl))})" if vorl else ""), flush=True)
        except (urllib.error.URLError, OSError, ValueError, StopIteration) as err:
            if frei and frei[0]:
                print(f"Hinweis: {name} nicht geladen ({err})", file=sys.stderr)
            else:
                fehler.append(f"{name}: {err}")
            if key in alte_reihen:
                reihen.append(alte_reihen[key])
                print(f"{name}: Abruf fehlgeschlagen, bisheriger Stand bleibt", file=sys.stderr)
        time.sleep(0.5)

    if not reihen:
        print("FEHLER: keine VPI-Reihe geladen – nichts gespeichert.", file=sys.stderr)
        return 1
    daten = {
        "stand": heute.isoformat() if neu_geladen else alt.get("stand"),
        "quelle": "Statistik Austria, Verbraucherpreisindex (Gesamtindex), data.statistik.gv.at, Lizenz CC BY 4.0",
        "vorlaeufig": sorted(vorlaeufig),
        "reihen": reihen,
    }
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(pfad)
    for f in fehler:
        print("FEHLER:", f, file=sys.stderr)
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
