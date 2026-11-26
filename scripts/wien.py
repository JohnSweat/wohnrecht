#!/usr/bin/env python3
"""Rubrik „Wohnbauträger Wien“: Dokumente der Stadt Wien, gefunden über data.gv.at.

Quellen (Herausgeber Stadt Wien, veröffentlicht nach dem Informationsfreiheitsgesetz):
  - Förderzusagen der MA 50 (Haussanierung u. a.): PDF; Empfänger, Vertreter, Adresse,
    Betrag und Maßnahme werden aus dem Text gelesen
  - Auszüge aus Prüfberichten nach § 28 Abs 8 WGG: Link und Geschäftsjahr
  - Bescheinigungen nach § 7 Abs 6 Z 3 lit c BTVG: Link
  - weitere Dokumente, in denen ein Träger aus data/wien_traeger.json genannt wird

Schreibt data/wien.json und den Textspeicher data/cache/wien_texte/<id>.txt.
Bereits ausgelesene Förderzusagen werden nicht erneut geladen; ändert sich PARSER_VERSION,
werden sie aus dem Textspeicher neu ausgewertet.

Privatpersonen: Namen werden nicht gespeichert, die Adresse wird auf den Bezirk gekürzt.

Aufruf: python scripts/wien.py [--debug N] [--nur-auswerten]
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASIS = pathlib.Path(__file__).resolve().parent.parent
SUCHE_URL = "https://www.data.gv.at/api/hub/search/search"
DMS = "https://dms.wien.gv.at"
UA = "wohnrecht/1.0 (+https://github.com/JohnSweat/wohnrecht; nicht-kommerzielles Nachschlagewerk, Abruf einmal pro Woche)"
PAUSE = 1.0
PARSER_VERSION = 3

# ---------------------------------------------------------------------------
# Netz
# ---------------------------------------------------------------------------

def hole(url: str, accept: str = "*/*", versuche: int = 4) -> bytes:
    letzter = None
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as err:
            letzter = err
            if err.code in (429, 500, 502, 503, 504) and i < versuche - 1:
                time.sleep(5 * (i + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as err:
            letzter = err
            if i < versuche - 1:
                time.sleep(5 * (i + 1))
                continue
            raise
    raise RuntimeError(f"Abruf fehlgeschlagen: {letzter}")


def t(x) -> str:
    if not x:
        return ""
    if isinstance(x, dict):
        return x.get("de") or next((v for v in x.values() if isinstance(v, str)), "") or ""
    return str(x)


def suche(q: str, max_treffer: int = 3000) -> list[dict]:
    aus: list[dict] = []
    seite = 0
    while len(aus) < max_treffer:
        params = {"q": q, "filter": "dataset", "limit": 100, "page": seite}
        url = SUCHE_URL + "?" + urllib.parse.urlencode(params)
        daten = json.loads(hole(url, "application/json"))
        res = daten.get("result") or {}
        items = res.get("results") or []
        aus.extend(items)
        if len(items) < 100:
            break
        seite += 1
        time.sleep(PAUSE / 2)
    return aus


def stelle(d: dict) -> str:
    p = d.get("publisher") or {}
    return str(p.get("name") or p.get("title") or "") if isinstance(p, dict) else str(p)


def ist_wien(d: dict) -> bool:
    return "wien" in stelle(d).lower()


def kontakt(d: dict) -> str:
    return json.dumps(d.get("contact_point") or "", ensure_ascii=False)


def share_url(d: dict) -> str | None:
    for dist in d.get("distributions") or []:
        for feld in ("access_url", "download_url"):
            werte = dist.get(feld) or []
            if isinstance(werte, str):
                werte = [werte]
            for u in werte:
                if isinstance(u, str) and u.startswith(DMS + "/share/ifg/"):
                    return u
    return None


def dist_titel(d: dict) -> str:
    return " ".join(t(dist.get("title")) for dist in d.get("distributions") or [])


def datensatz(d: dict) -> dict:
    return {
        "id": d.get("id"),
        "titel": re.sub(r"\s+", " ", t(d.get("title"))).strip(),
        "beschreibung": re.sub(r"\s+", " ", t(d.get("description"))).strip()[:400],
        "datum": (d.get("issued") or d.get("modified") or "")[:10] or None,
        "link": f"https://www.data.gv.at/datasets/{urllib.parse.quote(str(d.get('id')))}?locale=de",
        "share": share_url(d),
        "dist": dist_titel(d),
    }


RE_PDF_LINK = re.compile(r'href="(/share/proxy/alfresco-noauth/api/internal/shared/node/[^"]+?/content/([^"?]+))\?c=force')


def pdf_links(share: str) -> list[tuple[str, str]]:
    seite = hole(share, "text/html").decode("utf-8", "replace")
    aus = []
    for pfad, name in RE_PDF_LINK.findall(seite):
        url = DMS + html.unescape(pfad)
        if (url, name) not in aus:
            aus.append((url, urllib.parse.unquote(name)))
    return aus


def pdf_text(daten: bytes) -> str:
    if shutil.which("pdftotext"):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "d.pdf"
            p.write_bytes(daten)
            r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(p), "-"], capture_output=True, timeout=180)
            if r.returncode == 0:
                return r.stdout.decode("utf-8", "replace")
    try:
        from pypdf import PdfReader  # nur falls pdftotext fehlt
        return "\n\f".join((s.extract_text() or "") for s in PdfReader(io.BytesIO(daten)).pages)
    except Exception as err:  # noqa: BLE001 - Text ist dann leer, wird als "prüfen" markiert
        print(f"    PDF nicht lesbar: {err}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# Auswertung einer Förderzusage
# ---------------------------------------------------------------------------
#
# Aufbau der Texte (pdftotext -layout), abgeleitet aus den veröffentlichten Zusagen 2014–2026:
#
#   MA50-HS | Muthgasse 62, 1190 Wien                  ← Absenderzeile (fehlt bei älteren Zusagen)
#   <Förderungswerber (FN …)>            Amt der Wiener Landesregierung   ← rechte Spalte: Absender
#   [vertreten durch:]
#   [<Vertreter (FN …)>]
#   <Straße Nr>
#   <PLZ Ort>
#   MA50–HS-481363-2026-10               Wien, 9. Juni 2026                ← Geschäftszahl, Datum
#   Wien 3, Bechardgasse 15                                                ← Objekt
#   I.   … ein einmaliger nichtrückzahlbarer Beitrag im Ausmaß von 123.130,00 EUR …
#   II.  Bedingungen …
#
# Förderungswerber sind meist Unternehmen (mit Firmenbuchnummer FN), Eigentümergemeinschaften
# (WEG) oder Miteigentümer (MEG), vertreten durch eine Hausverwaltung. Bei manchen Zusagen sind
# die ersten Seiten nur als Bild enthalten; dann fehlen Empfänger, Objekt und Betrag im Text.

MONATE = {"jänner": 1, "jaenner": 1, "januar": 1, "februar": 2, "feber": 2, "märz": 3, "maerz": 3, "april": 4,
          "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}
# z. B. MA50–HS-481363-2026-10, MA 50 – HS 233559-2020, MA50-NF-NF-671832-2024, MA50-NF-1698794-24, MA50-NF-215345/2025
RE_GZ = re.compile(r"MA\s*50\s*(?:[-–—]?\s*[A-Z]{2,4}\s*)*[-–—]?\s*(\d{3,8})\s*[-–—/]\s*((?:20)?\d\d)\b")
RE_GZ_TITEL = re.compile(r"\((\d{3,8})-(20\d\d)\)")
RE_DATUM_WORT = re.compile(r"Wien,?\s*(?:am\s*)?(\d{1,2})\.\s*(" + "|".join(MONATE) + r")\s*(20\d\d)", re.I)
RE_DATUM_ZAHL = re.compile(r"Wien,?\s*(?:am\s*)?(\d{1,2})\.\s*(\d{1,2})\.\s*(20\d\d)")
ZAHL = r"\d{1,3}(?:[.  ]\d{3})*,\d{2}"
RE_BETRAGSSTELLE = re.compile(
    r"(?:im\s+(?:Gesamt)?(?:Betrag|Ausmaß|Ausmass)|in\s+(?:der\s+)?Höhe)\s+von\s+(?:EUR\s*|€\s*)?(" + ZAHL + r")", re.I)
RE_FN = re.compile(r"\(?\s*\bFN\s*0*(\d{1,6})\s*([a-zA-Z])\b\s*\)?")
RE_PLZ = re.compile(r"^(?:[A-Z]{1,2}\s*-\s*)?\d{4,5}\s+[A-ZÄÖÜ]")
RE_HAUSNUMMER_ENDE = re.compile(r"\d+\s*[a-zA-Z]?(?:\s*[-–/]\s*[\w.]+)*\s*$")
RE_ABSENDERZEILE = re.compile(r"^MA\s*50\b.*\|")
RE_ZUSTELLUNG = re.compile(r"^(?:per|via)\s+(?:E-?Mail|Post|Bote)|^Zustellung|^Einschreiben|^RSb?\b|^Nachweislich", re.I)
RE_OBJEKT_ZEILE = re.compile(r"^(?:Bauvorhaben:\s*)?(?:Wien\s*(\d{1,2})\s*,\s*|(\d{1,2})(?:\.\s*,?|\s*,)\s*)(\S.*)$")
RE_OBJEKT_TEXT = re.compile(r"Objekt(?:es)?\s+(?:in\s+)?Wien\s*(\d{1,2})\s*,\s*([^\n]+)")
RE_EZ = re.compile(r"\bEZ\.?\s*(\d{1,6})")
RE_KG = re.compile(r"Katastralgemeinde\s+(?:\d{5}\s+)?([A-ZÄÖÜ][\wäöüß]+(?:[- ][A-ZÄÖÜ][\wäöüß]+)?)")
RECHTSFORM = re.compile(
    r"(GmbH|G\.?\s?m\.?\s?b\.?\s?H\.?|Ges\.?\s?m\.?\s?b\.?\s?H|\bmbH\b|\bAG\b|Aktiengesellschaft|Genossenschaft\b|Gen\.?\s?m\.?\s?b\.?\s?H"
    r"|reg\.\s*Gen|\bKG\b|\bOG\b|\bSE\b|\bVerein\b|\bVVaG\b|Versicherung\b|Stiftung\b|\bFonds\b|Gesellschaft\b|\bHolding\b"
    r"|\bRepublik\b|\bStadt Wien\b|\bWiener Wohnen\b|\bKirche\b|\bPfarre\b|\bOrden\b|\bKloster\b|Bauvereinigung\b)", re.I)
EINZELUNTERNEHMEN = re.compile(r"\be\.\s?U\.?(?=\s|$|,|\))")

# Maßnahmen: Kürzel der Stadt Wien (Dateiname der Veröffentlichung), Paragrafen-Überschriften der
# Sanierungs- und Dekarbonisierungsverordnung in Abschnitt I, zuletzt der Titel
KUERZEL = {
    "TES": "Thermische Sanierung", "HEAES": "Heizung und Haustechnik", "ERH": "Erhaltungsarbeiten",
    "SOS": "Sockelsanierung", "TOS": "Totalsanierung", "DG": "Dachgeschoßausbau", "EWK": "Wohnkomfort",
    "AUF": "Aufzug", "GBS": "Sicherheit und Barrierefreiheit", "BF": "Sicherheit und Barrierefreiheit",
}
PARAGRAF_MASSNAHMEN = [
    ("Thermische Sanierung", re.compile(r"\(thermisch\w*\s+Sanierung\s+der\s+Gebäudehülle", re.I)),
    ("Heizung und Haustechnik", re.compile(r"\(energetische\s+Sanierung\s+der\s+Gebäudetechnik", re.I)),
    ("Erhaltungsarbeiten", re.compile(r"\(Erhaltungsmaßnahmen", re.I)),
    ("Sicherheit und Barrierefreiheit", re.compile(r"\(Gebäudesicherheit|\(Barrierefreiheit", re.I)),
    ("Aufzug", re.compile(r"\(Aufzug", re.I)),
    ("Wohnkomfort", re.compile(r"\(Erhöhung\s+Wohnkomfort", re.I)),
    ("Sockelsanierung", re.compile(r"Förderungsleistungen\s+für\s+die\s+Sockelsanierung", re.I)),
    ("Totalsanierung", re.compile(r"Förderungsleistungen\s+für\s+die\s+Totalsanierung", re.I)),
    ("Dachgeschoßausbau", re.compile(r"Förderungsleistungen\s+für\s+Dachgescho", re.I)),
]
TITEL_MASSNAHMEN = [
    ("Neubau", re.compile(r"Errichtung\s+einer\s+Wohnhausanlage|Neubau", re.I)),
    ("Thermische Sanierung", re.compile(r"thermisch|Gebäudehülle", re.I)),
    ("Heizung und Haustechnik", re.compile(r"Heizung", re.I)),
    ("Sockelsanierung", re.compile(r"Sockelsanierung", re.I)),
    ("Totalsanierung", re.compile(r"Totalsanierung", re.I)),
    ("Dachgeschoßausbau", re.compile(r"Dachgescho", re.I)),
    ("Erhaltungsarbeiten", re.compile(r"Erhaltung", re.I)),
]


def betrag_zahl(s: str) -> float:
    return float(re.sub(r"[.  ]", "", s).replace(",", "."))


def sauber(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" ,;:-–")


def fn_norm(m: re.Match) -> str:
    return f"{int(m.group(1))}{m.group(2).lower()}"


def links(zeile: str) -> str:
    """Linke Spalte einer Layout-Zeile (rechts steht im Briefkopf der Absender)."""
    zeile = zeile.replace("\f", "")
    if not zeile.strip() or re.match(r"\s{25,}\S", zeile):
        return ""
    return re.split(r"\s{3,}", zeile.strip())[0].strip()


def briefkopf(text: str) -> tuple[list[str], int | None]:
    """Linke Spalte vom Anfang bis zur Geschäftszahl; Rückgabe (Zeilen, Index der GZ-Zeile)."""
    zeilen = text.splitlines()
    block: list[str] = []
    for i, z in enumerate(zeilen[:90]):
        if RE_GZ.search(z):
            return block, i
        l = links(z)
        if l:
            block.append(l)
    return [], None


def verbinde(zeilen: list[str]) -> str:
    """Namenszeilen zusammenfügen und Silbentrennung am Zeilenende auflösen."""
    s = ""
    for z in (z.strip() for z in zeilen):
        if not z:
            continue
        if not s:
            s = z
        elif s.endswith("-") and not s.endswith(" -"):
            if re.match(r"(?:und|u\.|&|bzw\.|oder)(?:\s|$)", z):
                s += " " + z          # "Immobilien-" + "und Vermögenstreuhand"
            elif z[:1].islower():
                s = s[:-1] + z        # "Woh-" + "nungsaktiengesellschaft"
            else:
                s += z                # "Gebäudeverwaltung-" + "Realitätenkanzlei"
        else:
            s += " " + z
    return re.sub(r"\s+", " ", s).strip()


def partei(zeilen: list[str]) -> dict | None:
    """Förderungswerber oder Vertreter aus den Zeilen des Briefkopfs."""
    zeilen = [z for z in zeilen if z.strip() and not RE_ZUSTELLUNG.search(z)]
    if not zeilen:
        return None
    alles = " ".join(zeilen)
    if re.search(r"Eigent(?:ü|ue)mergemeinschaft|\(WEG\)", alles):
        return {"art": "weg", "name": sauber(re.sub(r"\(\d{6,}\)", "", zeilen[0])), "fn": None}
    if re.search(r"Miteigent(?:ü|ue)mer|\(MEG\)", alles):
        return {"art": "meg", "name": None, "fn": None}
    ende = next((i + 1 for i, z in enumerate(zeilen) if RE_FN.search(z)), None)
    if ende is None:
        ende = len(zeilen)
        plz = next((i for i, z in enumerate(zeilen) if RE_PLZ.match(z)), None)
        if plz is not None:
            ende = plz
            while ende > 1 and plz - ende < 2 and RE_HAUSNUMMER_ENDE.search(zeilen[ende - 1]) \
                    and not RECHTSFORM.search(zeilen[ende - 1]):
                ende -= 1
    name = verbinde(zeilen[:ende])
    m = RE_FN.search(name)
    fn = fn_norm(m) if m else None
    name = sauber(RE_FN.sub(" ", name))
    if fn and not EINZELUNTERNEHMEN.search(name):
        return {"art": "unternehmen", "name": name, "fn": fn}
    if re.match(r"(?:Stadt Wien|Gemeinde Wien|Wiener Wohnen)\b", name):
        return {"art": "stadt", "name": "Wiener Wohnen" if name.startswith("Wiener Wohnen") else "Stadt Wien", "fn": None}
    if RECHTSFORM.search(name) and not EINZELUNTERNEHMEN.search(name):
        return {"art": "unternehmen", "name": name, "fn": None}
    return {"art": "privat", "name": None, "fn": None}


def zerlege_briefkopf(block: list[str]) -> tuple[dict | None, dict | None]:
    zeilen = [z for z in block if not RE_ABSENDERZEILE.search(z)]
    for i, z in enumerate(zeilen):
        m = re.search(r"(?:^|,\s*)vertreten\s+durch\s*:?\s*(.*)$", z, re.I)
        if m:
            vor = z[: m.start()].strip(" ,")
            empf = zeilen[:i] + ([vor] if vor else [])
            vertr = ([m.group(1)] if m.group(1).strip() else []) + zeilen[i + 1:]
            return partei(empf), partei(vertr)
    return partei(zeilen), None


def abschnitt_i(text: str) -> str:
    """Abschnitt I (Gegenstand und Höhe der Förderung)."""
    m1 = re.search(r"(?m)^\s*I\.\s*$", text) or re.search(r"Z\s?U\s?S\s?I\s?C\s?H\s?E\s?R\s?U\s?N\s?G", text)
    if not m1:
        return ""
    rest = text[m1.end():]
    m2 = re.search(r"(?m)^\s*II\.\s*$|^\s*III\.\s*$|Für die Zusicherung gelten folgende", rest)
    return rest[: m2.start() if m2 else 12000]


def lies_betraege(bereich: str) -> list[dict]:
    """Zugesicherte Beträge; Kautionen, Pfandrechte und Strafen werden nicht gezählt."""
    aus = []
    vorher_ende = 0
    for m in RE_BETRAGSSTELLE.finditer(bereich):
        fenster = bereich[max(vorher_ende, m.start() - 500): m.start()]
        vorher_ende = m.end()
        for trenner in ("•", "\n -", "\n- ", "\n– "):
            pos = fenster.rfind(trenner)
            if pos >= 0:
                fenster = fenster[pos:]
        klein = fenster.lower()
        if re.search(r"kaution|pfandrecht|konventionalstrafe|strafe|zinsen\s*$|gebühr", klein[-120:]):
            continue
        treffer = [(klein.rfind(w), art) for w, art in (
            ("darlehen", "Darlehen"), ("zuschuss", "Zuschuss"), ("beitrag", "Beitrag"), ("nichtrückzahlbar", "Beitrag"))]
        pos, art = max(treffer)
        if pos < 0:
            continue
        eintrag = {"art": art, "eur": betrag_zahl(m.group(1))}
        if eintrag not in aus:  # spätere Absätze (z. B. Tilgung) nennen denselben Betrag noch einmal
            aus.append(eintrag)
    return aus


def lies_massnahmen(ds: dict, bereich: str, neubau: bool) -> list[str]:
    aus: list[str] = []
    code = re.split(r"\s*\(", ds.get("dist") or "")[0].strip()
    teile = code.split("/") if code else []
    if teile and all(re.fullmatch(r"[A-Z]{2,6}(?:neu)?(?:_\w+)?", x) for x in teile):
        for x in teile:
            name = KUERZEL.get(re.sub(r"(neu|_\w+)$", "", x))
            if name and name not in aus:
                aus.append(name)
    if not aus:
        for name, regex in PARAGRAF_MASSNAHMEN:
            if regex.search(bereich) and name not in aus:
                aus.append(name)
    if not aus and neubau:
        aus.append("Neubau")
    if not aus:
        for name, regex in TITEL_MASSNAHMEN:
            if regex.search(ds.get("titel") or ""):
                aus.append(name)
                break
    return aus or ["Sonstige"]


def lies_datum(text: str) -> str | None:
    m = RE_DATUM_WORT.search(text)
    if m:
        monat = MONATE.get(m.group(2).lower())
        if monat:
            return f"{m.group(3)}-{monat:02d}-{int(m.group(1)):02d}"
    m = RE_DATUM_ZAHL.search(text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def lies_objekt(zeilen: list[str], gz_index: int | None, bereich: str) -> dict:
    if gz_index is not None:
        for z in zeilen[gz_index + 1: gz_index + 5]:
            l = links(z)
            if not l:
                continue
            m = RE_OBJEKT_ZEILE.match(l)
            if m:
                bezirk = int(m.group(1) or m.group(2))
                if 1 <= bezirk <= 23:
                    return {"bezirk": bezirk, "adresse": sauber(m.group(3))}
            break
    m = RE_OBJEKT_TEXT.search(re.sub(r"[ \t]+", " ", bereich))
    if m and 1 <= int(m.group(1)) <= 23:
        return {"bezirk": int(m.group(1)), "adresse": sauber(re.split(r"\s{2,}| auf der ", m.group(2))[0])}
    return {}


def lies_foerderzusage(text: str, ds: dict, traeger: list[dict]) -> dict:
    pruefen = []
    zeilen = text.splitlines()
    block, gz_index = briefkopf(text)
    empf, vertr = zerlege_briefkopf(block) if block else (None, None)
    bereich = abschnitt_i(text)

    m = RE_GZ.search(zeilen[gz_index]) if gz_index is not None else None
    m = m or RE_GZ_TITEL.search(ds.get("titel") or "") or RE_GZ_TITEL.search(ds.get("dist") or "")
    gz = f"{m.group(1)}-{m.group(2) if len(m.group(2)) == 4 else '20' + m.group(2)}" if m else None
    neubau = bool(gz_index is not None and re.search(r"MA\s*50\s*[-–]?\s*N[FB]", zeilen[gz_index])) \
        or bool(re.search(r"Errichtung\s+einer\s+Wohnhausanlage", bereich + (ds.get("titel") or "")))

    # Firmenbuchnummer des Förderungswerbers steht bei Neubauten erst im Abschnitt I
    if empf and empf["art"] == "unternehmen" and not empf["fn"]:
        m = re.search(r"\(\s*FN\s*0*(\d{1,6})\s*([a-zA-Z])\s*\)\s*,?\s*im\s+Folgenden", bereich)
        if m:
            empf["fn"] = fn_norm(m)

    objekt = lies_objekt(zeilen, gz_index, bereich)
    kopf_text = "\n".join(zeilen[(gz_index or 0):]) if gz_index is not None else bereich
    m = RE_EZ.search(bereich)
    ez = m.group(1) if m else None
    m = RE_KG.search(bereich)
    kg = m.group(1) if m else None
    betraege = lies_betraege(bereich)
    m = re.search(r"mit\s+insgesamt\s+(\d{1,4})\s+(?:geförderten\s+)?Wohnungen", bereich)
    wohnungen = int(m.group(1)) if m else None

    if not text.strip():
        pruefen.append("PDF ohne lesbaren Text")
    elif not block:
        pruefen.append("Erste Seiten nur als Bild")
    else:
        if not empf:
            pruefen.append("Empfänger nicht erkannt")
        if not objekt:
            pruefen.append("Adresse nicht erkannt")
    if text.strip() and not betraege:
        pruefen.append("Betrag nicht erkannt")

    art = empf["art"] if empf else "unbekannt"
    oeffentlich = art in ("unternehmen", "weg", "stadt")
    eintrag = {
        "id": ds["id"],
        "gz": gz,
        "datum": (lies_datum(kopf_text[:3000]) if gz_index is not None else None) or ds.get("datum"),
        "titel": ds.get("titel"),
        "link": ds.get("link"),
        "pdf": ds.get("share"),
        "empfaenger": empf["name"] if empf and oeffentlich else None,
        "empfaenger_fn": empf["fn"] if empf and art == "unternehmen" else None,
        "empfaenger_typ": art,
        "traeger": ordne_zu(empf, traeger) if empf and oeffentlich else None,
        "vertreter": vertr["name"] if vertr and vertr["art"] in ("unternehmen", "stadt") else ("Einzelperson" if vertr and vertr["art"] == "privat" else None),
        "vertreter_fn": vertr["fn"] if vertr and vertr["art"] == "unternehmen" else None,
        "vertreter_traeger": ordne_zu(vertr, traeger) if vertr and vertr["art"] in ("unternehmen", "stadt") else None,
        "bezirk": objekt.get("bezirk"),
        "adresse": objekt.get("adresse") if oeffentlich else None,
        "ez": ez if oeffentlich else None,
        "kg": kg,
        "massnahmen": lies_massnahmen(ds, bereich, neubau),
        "wohnungen": wohnungen,
        "betraege": betraege,
        "nicht_rueckzahlbar": round(sum(b["eur"] for b in betraege if b["art"] in ("Beitrag", "Zuschuss")), 2),
        "darlehen": round(sum(b["eur"] for b in betraege if b["art"] == "Darlehen"), 2),
        "pruefen": pruefen,
        "version": PARSER_VERSION,
    }
    return eintrag


# ---------------------------------------------------------------------------
# Zuordnung zu Trägern
# ---------------------------------------------------------------------------

def lade_traeger(pfad: pathlib.Path) -> list[dict]:
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    aus = []
    for tr in daten["traeger"]:
        tr = dict(tr)
        tr["_re"] = re.compile(tr["muster"], re.I)
        tr["fn"] = [f"{int(m.group(1))}{m.group(2).lower()}" for m in (re.match(r"0*(\d+)\s*([a-zA-Z])", x) for x in tr.get("fn") or []) if m]
        aus.append(tr)
    return aus


def ordne_zu(wer, traeger: list[dict]) -> str | None:
    """wer: Partei (dict mit name/fn) oder Text. Zuerst über die Firmenbuchnummer, dann über den Namen."""
    if not wer:
        return None
    name, fn = (wer.get("name"), wer.get("fn")) if isinstance(wer, dict) else (wer, None)
    if fn:
        for tr in traeger:
            if fn in tr["fn"]:
                return tr["key"]
    if name:
        for tr in traeger:
            if tr["_re"].search(name):
                return tr["key"]
    return None


# ---------------------------------------------------------------------------
# Überblick je Träger
# ---------------------------------------------------------------------------

# Eigener Name: Früher hieß diese Konstante ebenfalls RECHTSFORM und überschrieb beim Laden des Moduls die
# breite Fassung oben, die partei() braucht (OG, KG, Verein, Stiftung … galten dadurch als Privatperson).
RECHTSFORM_KERN = re.compile(
    r"(?:(?:reg(?:istrierte)?|eingetragene)\.?\s*)?\bgen(?:ossenschaft)?\.?\s*(?:mit\s+beschränkter\s+haftung|m\.?\s*b\.?\s*h\b\.?)"
    r"|ges(?:ellschaft)?\.?\s*(?:mit\s+beschränkter\s+haftung|m\.?\s*b\.?\s*h\b\.?)"
    r"|\bgmbh\b|\bm\.?\s*b\.?\s*h\b\.?|aktiengesellschaft|\bag\b", re.I)


def kern(name: str) -> str:
    """Vergleichsschlüssel für Firmennamen: ohne Rechtsform, "gemeinnützig", Satzzeichen.
    "MIGRA Gemeinnützige Wohnungsges.m.b.H." und "MIGRA gemeinnützige Wohnungsgesellschaft mbH"
    ergeben denselben Schlüssel."""
    s = RECHTSFORM_KERN.sub(" ", (name or "").lower())
    s = re.sub(r"gemeinnützig\w*", " ", s)
    s = re.sub(r"\bu\.\s", " und ", s.replace("&", " und "))
    return re.sub(r"[^a-z0-9äöüß]+", "", s)


def firmenname(titel: str) -> str:
    """Firmenname aus dem Titel eines Prüfberichts (§ 28 Abs 8 WGG) oder einer BTVG-Bescheinigung."""
    s = re.sub(r"\s*\(\d+-\d{4}\)\s*$", "", titel or "")
    s = re.split(r"\s+-\s+(?:Auszug|Bescheinigung)\b|\s+Bescheinigung\s+§", s)[0]
    return s.strip(" ,-")


def leerer_eintrag(key: str, name: str, typ: str, fn=None, info=None) -> dict:
    return {"key": key, "name": name, "typ": typ, "info": info, "fn": fn,
            "foerderungen": [], "als_vertreter": [], "summe_nicht_rueckzahlbar": 0.0, "summe_darlehen": 0.0,
            "pruefberichte": [], "btvg": [], "sonstige": []}


def baue_ueberblick(traeger: list[dict], foerderungen: list[dict], pruefberichte: list[dict],
                    bescheinigungen: list[dict], sonst_ds: list[dict]) -> tuple[list[dict], int, int]:
    """Ein Eintrag je Träger: zuerst die Liste aus data/wien_traeger.json, dann weitere Unternehmen
    aus den Förderzusagen (über die Firmenbuchnummer), zuletzt gemeinnützige Bauvereinigungen, die nur
    mit Prüfbericht oder BTVG-Bescheinigung vorkommen. Gibt (Überblick, Anzahl weitere, Anzahl nur
    aus Prüfberichten/BTVG) zurück."""
    def summen(ids: list[str]) -> tuple[float, float]:
        auswahl = [f for f in foerderungen if f["id"] in set(ids)]
        return (round(sum(f.get("nicht_rueckzahlbar") or 0 for f in auswahl), 2),
                round(sum(f.get("darlehen") or 0 for f in auswahl), 2))

    def dok(d: dict, felder=("titel", "datum", "link", "share")) -> dict:
        return {k: d.get(k) for k in felder}

    ueberblick = []
    for tr in traeger:
        k = tr["key"]
        e = leerer_eintrag(k, tr["name"], tr["typ"], tr["fn"][0] if tr["fn"] else None, tr.get("info"))
        e["foerderungen"] = [f["id"] for f in foerderungen if f.get("traeger") == k]
        e["als_vertreter"] = [f["id"] for f in foerderungen if f.get("vertreter_traeger") == k and f.get("traeger") != k]
        e["summe_nicht_rueckzahlbar"], e["summe_darlehen"] = summen(e["foerderungen"])
        e["pruefberichte"] = [dok(p, ("titel", "datum", "gj", "link", "share")) for p in pruefberichte if p.get("traeger") == k]
        e["btvg"] = [dok(b) for b in bescheinigungen if b.get("traeger") == k]
        e["sonstige"] = [dok(s) for s in sonst_ds if s.get("traeger") == k]
        ueberblick.append(e)

    # Weitere Unternehmen (z. B. Hausverwaltungen): automatisch über die Firmenbuchnummer
    weitere: dict[str, dict] = {}
    for f in foerderungen:
        for rolle, name, fn, tr in (("foerderungen", f.get("empfaenger"), f.get("empfaenger_fn"), f.get("traeger")),
                                    ("als_vertreter", f.get("vertreter"), f.get("vertreter_fn"), f.get("vertreter_traeger"))):
            if not fn or tr or not name:
                continue
            w = weitere.setdefault(fn, {"namen": {}, "foerderungen": [], "als_vertreter": []})
            w["namen"][name] = w["namen"].get(name, 0) + 1
            if f["id"] not in w[rolle]:
                w[rolle].append(f["id"])
    nach_kern: dict[str, dict] = {}
    for fn, w in sorted(weitere.items()):
        name = max(w["namen"].items(), key=lambda x: (x[1], -len(x[0])))[0]
        e = leerer_eintrag("fn-" + fn, name, "gemeinnützig" if re.search(r"gemeinn", name, re.I) else "weitere", fn)
        e["foerderungen"], e["als_vertreter"] = w["foerderungen"], w["als_vertreter"]
        e["summe_nicht_rueckzahlbar"], e["summe_darlehen"] = summen(w["foerderungen"])
        ueberblick.append(e)
        for n in w["namen"]:
            nach_kern.setdefault(kern(n), e)

    # Prüfberichte und BTVG-Bescheinigungen ohne Träger aus der Liste: zum Unternehmen gleichen Namens,
    # sonst als eigener Eintrag. Wer nach § 28 Abs 8 WGG prüfen lässt, ist eine gemeinnützige Bauvereinigung.
    nur_dokumente = 0
    for art, liste in (("pruefberichte", pruefberichte), ("btvg", bescheinigungen)):
        for d in liste:
            name = firmenname(d.get("titel"))
            if d.get("traeger") or not kern(name):
                continue
            e = nach_kern.get(kern(name))
            if e is None:
                slug = kern(name).translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
                e = leerer_eintrag("wgg-" + slug[:40], name, "gemeinnützig")
                ueberblick.append(e)
                nach_kern[kern(name)] = e
                nur_dokumente += 1
            e["typ"] = "gemeinnützig"
            e[art].append(dok(d, ("titel", "datum", "gj", "link", "share")) if art == "pruefberichte" else dok(d))
            d["traeger"] = e["key"]

    for e in ueberblick:
        e["pruefberichte"].sort(key=lambda p: (p.get("gj") or 0, p.get("datum") or ""), reverse=True)
        e["btvg"].sort(key=lambda b: b.get("datum") or "", reverse=True)
    return ueberblick, len(weitere), nur_dokumente


# ---------------------------------------------------------------------------
# Wiener Wohnen: Gemeindebauten und Dokumente
# ---------------------------------------------------------------------------

GEMEINDEBAUTEN_URL = "https://www.wwpipe.at/web-services/rest/ogd/GemeindebautenWien.xml"

# Infoblätter und Berichte von Wiener Wohnen auf data.gv.at; Ausschreibungen und Rahmenverträge nicht
WW_INFOBLATT = re.compile(r"Stadt Wien\s*[-–]\s*Wiener Wohnen\s*\(\d", re.I)
WW_AUSWAHL = re.compile(r"^(?:Geschäftsbericht \d{4}|Zahlen, Daten, Fakten|Liste_WHA|Vergaberichtlinien Wohnungsvergabe)", re.I)


def ist_ww_dokument(titel: str, beschreibung: str = "") -> bool:
    if WW_INFOBLATT.search(titel or ""):
        return True
    return bool(WW_AUSWAHL.search(titel or "") and re.search(r"Wiener Wohnen|Gemeindebau|Wohnungsvergabe", f"{titel} {beschreibung}", re.I))


def lies_gemeindebauten(daten: bytes) -> dict:
    """Datensatz „Gemeindebauten“ von Wiener Wohnen (XML) auf das Nötige verkleinern:
    Name, Wohnungen, Bauzeit(en) und alle Adressen (Haupt- und Nebenadressen).
    Anzahl und Wohnungen zählen alle Einträge des Datensatzes, zum Zuordnen dienen nur die mit Adresse."""
    wurzel = ET.fromstring(daten)

    def txt(el, pfad: str) -> str:
        x = el.find(pfad)
        return (x.text or "").strip() if x is not None else ""

    bauten, alle, wohnungen_alle = [], 0, 0
    for b in wurzel.findall("building"):
        alle += 1
        wohnungen = txt(b, "numberOfFlats")
        wohnungen_alle += int(wohnungen) if wohnungen.isdigit() else 0
        adressen = []
        for a in b.findall("addresses/address"):
            plz, strasse, nr = txt(a, "zipcode"), txt(a, "street"), txt(a, "streetnumber")
            if plz and strasse:
                adressen.append([plz, strasse, nr])
        zeiten = []
        for j in b.findall("yearOfConstructions/yearOfConstruction"):
            von, bis = txt(j, "yearFrom"), txt(j, "yearTo")
            if von.isdigit():
                zeiten.append([int(von), int(bis) if bis.isdigit() else int(von)])
        if adressen:
            bauten.append({"id": txt(b, "id"), "name": txt(b, "buildingName"),
                           "wohnungen": int(wohnungen) if wohnungen.isdigit() else None,
                           "bauzeit": sorted(zeiten), "adressen": adressen})
    if not bauten:
        raise ValueError("keine Gemeindebauten im Datensatz")
    return {"stand": txt(wurzel, "metadata/metadata_modified") or None,
            "quelle": "Stadt Wien – Wiener Wohnen, Datensatz „Gemeindebauten“, CC BY 3.0 AT",
            "anzahl": alle, "wohnungen": wohnungen_alle, "bauten": bauten}


def strassen_schluessel(s: str) -> str:
    s = (s or "").lower().replace("ß", "ss")
    s = re.sub(r"stra?sse\b|str\.", "str", s)
    return re.sub(r"[^a-z0-9äöü]+", "", s)


def nummer_bereich(s: str) -> tuple[int, int] | None:
    m = re.match(r"\s*(\d+)\s*[a-z]?(?:\s*[-–/]\s*(\d+))?", s or "", re.I)
    return (int(m.group(1)), int(m.group(2) or m.group(1))) if m else None


def gemeindebau_index(bauten: list[dict]) -> dict:
    index: dict[tuple[str, str], list] = {}
    for i, b in enumerate(bauten):
        for plz, strasse, nr in b["adressen"]:
            index.setdefault((str(plz), strassen_schluessel(strasse)), []).append((re.sub(r"\s+", "", nr.lower()), nummer_bereich(nr), i))
    return index


def finde_gemeindebau(index: dict, bauten: list[dict], bezirk, adresse: str) -> list[dict]:
    """Gemeindebauten zu einer Adresse im Bezirk: zuerst genau gleiche Hausnummer, sonst
    überlappende Nummernbereiche (z. B. 17-18 zu 17). Ohne Hausnummer nur, wenn die Straße
    zu genau einem Gemeindebau gehört."""
    if not bezirk or not adresse:
        return []
    m = re.match(r"^(.*?)\s+(\d.*)$", adresse.strip())
    strasse, nummer = (m.group(1), m.group(2)) if m else (adresse.strip(), "")
    kand = index.get((str(1000 + 10 * int(bezirk)), strassen_schluessel(strasse)), [])
    roh = re.sub(r"\s+", "", nummer.lower())
    treffer = [i for r, _, i in kand if nummer and r == roh][:1]
    if not treffer:
        n = nummer_bereich(nummer)
        if n:
            treffer = [i for _, b, i in kand if b and b[0] <= n[1] and n[0] <= b[1]]
        elif len({i for *_, i in kand}) == 1:
            treffer = [kand[0][2]]
    ergebnis = []
    for i in dict.fromkeys(treffer):
        b = bauten[i]
        ergebnis.append({"name": b["name"], "wohnungen": b["wohnungen"], "bauzeit": b["bauzeit"]})
    return ergebnis[:3]


GJ = re.compile(r"GJ[_\s-]?(20\d\d)", re.I)


# ---------------------------------------------------------------------------
# Ablauf
# ---------------------------------------------------------------------------

def lade_json(pfad: pathlib.Path, standard):
    if not pfad.exists():
        return standard
    return json.loads(pfad.read_text(encoding="utf-8"))


def schreibe_json(pfad: pathlib.Path, daten) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(pfad)


def debug_ausgabe(e: dict, text: str) -> None:
    """Ausgelesene Felder ins Protokoll (ohne Rohtext)."""
    felder = ("gz", "datum", "empfaenger_typ", "empfaenger", "empfaenger_fn", "vertreter", "vertreter_fn",
              "bezirk", "adresse", "massnahmen", "betraege", "pruefen")
    print(f"  --- {e['id']} ({e.get('titel')})")
    print("     " + json.dumps({k: e.get(k) for k in felder}, ensure_ascii=False))


def zu_viele_fehler(fehlgeschlagen: int, versuche: int) -> bool:
    """Gilt als Fehler des Laufs: mindestens 5 Ausfälle und mindestens die Hälfte der Versuche."""
    return fehlgeschlagen >= 5 and fehlgeschlagen * 2 >= versuche


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rubrik Wohnbauträger Wien aktualisieren.")
    ap.add_argument("--debug", type=int, default=0, help="für N Förderzusagen Strukturhinweise ausgeben")
    ap.add_argument("--nur-auswerten", action="store_true", help="nichts laden, nur den Textspeicher neu auswerten")
    ap.add_argument("--max-neu", type=int, default=500, help="höchstens so viele neue PDFs je Lauf laden")
    ap.add_argument("--basis", default=str(BASIS), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    basis = pathlib.Path(args.basis)
    traeger = lade_traeger(basis / "data" / "wien_traeger.json")
    pfad = basis / "data" / "wien.json"
    texte = basis / "data" / "cache" / "wien_texte"
    texte.mkdir(parents=True, exist_ok=True)
    alt = lade_json(pfad, {})
    stand = dt.datetime.now(dt.timezone.utc).date().isoformat()
    fehler = []

    if args.nur_auswerten:
        zusagen_ds = alt.get("_datensaetze", {}).get("foerderzusagen", [])
        wgg_ds = alt.get("_datensaetze", {}).get("wgg", [])
        btvg_ds = alt.get("_datensaetze", {}).get("btvg", [])
        sonst_ds = alt.get("_datensaetze", {}).get("sonstige", [])
    else:
        try:
            roh = suche('"Förderzusage"')
            zusagen_ds = [datensatz(d) for d in roh if ist_wien(d) and re.search(r"Magistratsabteilung\s*50|MA\s*50", kontakt(d))]
            roh = suche("WGG")
            wgg_ds = [datensatz(d) for d in roh if ist_wien(d) and re.search(r"28\s*Abs\.?\s*8", t(d.get("title")) + " " + t(d.get("description")))]
            roh = suche("BTVG")
            btvg_ds = [datensatz(d) for d in roh if ist_wien(d) and "BTVG" in t(d.get("title"))]
            bekannt = {d["id"] for d in zusagen_ds + wgg_ds + btvg_ds}
            sonst_ds = []
            for tr in traeger:
                suchwort = re.sub(r"\s*\(.*?\)", "", tr["name"]).strip()
                for d in suche(f'"{suchwort}"', max_treffer=300):
                    if not ist_wien(d) or d.get("id") in bekannt:
                        continue
                    s = t(d.get("title")) + " " + t(d.get("description"))
                    if tr["_re"].search(s):
                        ds = datensatz(d)
                        ds["traeger"] = tr["key"]
                        sonst_ds.append(ds)
                        bekannt.add(d["id"])
                time.sleep(PAUSE / 2)
            # Wiener Wohnen: Infoblätter, Geschäftsbericht, Zahlen und Fakten (keine Vergaben)
            ww = 0
            for d in suche('"Wiener Wohnen"', max_treffer=1000):
                if ist_wien(d) and d.get("id") not in bekannt and ist_ww_dokument(t(d.get("title")), t(d.get("description"))):
                    ds = datensatz(d)
                    ds["traeger"] = "wiener-wohnen"
                    sonst_ds.append(ds)
                    bekannt.add(d["id"])
                    ww += 1
            print(f"data.gv.at: {len(zusagen_ds)} Förderzusagen MA 50, {len(wgg_ds)} WGG-Auszüge, {len(btvg_ds)} BTVG-Bescheinigungen, "
                  f"{len(sonst_ds)} weitere Dokumente (davon {ww} von Wiener Wohnen)", flush=True)
        except (urllib.error.URLError, OSError, ValueError) as err:
            print(f"FEHLER: Suche auf data.gv.at: {err}", file=sys.stderr)
            return 1
        if not zusagen_ds and alt.get("foerderungen"):
            # Schutz gegen eine leere Suchantwort: sonst wären alle bisherigen Förderzusagen weg
            print("FEHLER: data.gv.at liefert keine Förderzusagen mehr – nichts gespeichert, Suche prüfen.", file=sys.stderr)
            return 1

    # Förderzusagen: neue laden, alle (neu) auswerten
    alte_fz = {e["id"]: e for e in alt.get("foerderungen", [])}
    foerderungen = []
    geladen = pdf_fehler = 0
    debug_rest = args.debug
    for ds in sorted(zusagen_ds, key=lambda x: x.get("datum") or "", reverse=True):
        textdatei = texte / f"{ds['id']}.txt"
        vorher = alte_fz.get(ds["id"])
        if vorher and vorher.get("version") == PARSER_VERSION and not debug_rest and not args.nur_auswerten:
            foerderungen.append(vorher)
            continue
        text = textdatei.read_text(encoding="utf-8") if textdatei.exists() else None
        if text is None and not args.nur_auswerten:
            if geladen >= args.max_neu or not ds.get("share"):
                if vorher:
                    foerderungen.append(vorher)
                continue
            try:
                links = [u for u, name in pdf_links(ds["share"]) if name.lower().endswith(".pdf")]
                if not links:
                    raise ValueError("kein PDF in der Freigabe")
                text = pdf_text(hole(links[0], "application/pdf"))
                textdatei.write_text(text, encoding="utf-8")
                geladen += 1
                time.sleep(PAUSE)
            except (urllib.error.URLError, OSError, ValueError) as err:
                print(f"  {ds['id']}: {err}", file=sys.stderr)
                pdf_fehler += 1
                if vorher:
                    foerderungen.append(vorher)
                continue
        if text is None:
            continue
        e = lies_foerderzusage(text, ds, traeger)
        foerderungen.append(e)
        if debug_rest > 0:
            debug_ausgabe(e, text)
            debug_rest -= 1
    print(f"Förderzusagen: {len(foerderungen)} ausgewertet, {geladen} PDFs neu geladen"
          + (f", {pdf_fehler} nicht ladbar" if pdf_fehler else ""), flush=True)
    # Einzelne kaputte Freigaben kommen vor; scheitert aber mindestens die Hälfte (und mehr als eine Handvoll), stimmt etwas nicht
    if zu_viele_fehler(pdf_fehler, geladen + pdf_fehler):
        fehler.append(f"Förderzusagen: {pdf_fehler} von {geladen + pdf_fehler} PDFs nicht ladbar")

    # Fehlt die Firmenbuchnummer (z. B. Zweigniederlassung), über den Namen aus anderen Zusagen ergänzen
    def schluessel(name: str) -> str:
        return re.sub(r"[^a-z0-9äöüß]+", "", name.lower())[:36]
    fn_nach_name = {}
    for f in foerderungen:
        for name, fn in ((f.get("empfaenger"), f.get("empfaenger_fn")), (f.get("vertreter"), f.get("vertreter_fn"))):
            if name and fn:
                fn_nach_name.setdefault(schluessel(name), fn)
    for f in foerderungen:
        if f.get("empfaenger_typ") == "unternehmen" and f.get("empfaenger") and not f.get("empfaenger_fn"):
            f["empfaenger_fn"] = fn_nach_name.get(schluessel(f["empfaenger"]))
            f["traeger"] = f.get("traeger") or ordne_zu({"name": f["empfaenger"], "fn": f["empfaenger_fn"]}, traeger)
        if f.get("vertreter") and not f.get("vertreter_fn") and f["vertreter"] not in ("Wiener Wohnen", "Einzelperson"):
            f["vertreter_fn"] = fn_nach_name.get(schluessel(f["vertreter"]))
            f["vertreter_traeger"] = f.get("vertreter_traeger") or ordne_zu({"name": f["vertreter"], "fn": f["vertreter_fn"]}, traeger)

    # Gemeindebauten (Wiener Wohnen, monatlich aktualisiert): Förderzusagen der Stadt Wien über die Adresse zuordnen.
    # Der verkleinerte Datensatz liegt in data/cache; fällt der Abruf aus, gilt der letzte Stand.
    gb_pfad = basis / "data" / "cache" / "gemeindebauten.json"
    if not args.nur_auswerten:
        try:
            schreibe_json(gb_pfad, lies_gemeindebauten(hole(GEMEINDEBAUTEN_URL, "application/xml")))
        except (urllib.error.URLError, OSError, ValueError, ET.ParseError) as err:
            print(f"Hinweis: Gemeindebauten nicht geladen ({err}); letzter Stand bleibt.", file=sys.stderr)
            if not gb_pfad.exists():
                fehler.append(f"Gemeindebauten nicht geladen und kein früherer Stand vorhanden ({err})")
    gb = lade_json(gb_pfad, None)
    gb_info = None
    if gb and gb.get("bauten"):
        index = gemeindebau_index(gb["bauten"])
        zugeordnet = 0
        for f in foerderungen:
            f.pop("gemeindebau", None)
            if f.get("empfaenger_typ") == "stadt" and f.get("adresse"):
                treffer = finde_gemeindebau(index, gb["bauten"], f.get("bezirk"), f["adresse"])
                if treffer:
                    f["gemeindebau"] = treffer
                    zugeordnet += 1
        stadt = sum(1 for f in foerderungen if f.get("empfaenger_typ") == "stadt")
        gb_info = {k: gb.get(k) for k in ("stand", "quelle", "anzahl", "wohnungen")} | {"zugeordnet": zugeordnet, "stadt": stadt}
        print(f"Gemeindebauten: {gb['anzahl']} (Stand {gb.get('stand')}); {zugeordnet} von {stadt} Förderzusagen der Stadt Wien zugeordnet", flush=True)

    # Prüfberichte: Geschäftsjahr steht im Dateinamen (z. B. PB_W50_GJ_2024_Auszug.PDF)
    alte_wgg = {d["id"]: d for d in alt.get("pruefberichte", [])}
    pruefberichte = []
    wgg_versuche = wgg_fehler = 0
    for ds in wgg_ds:
        e = alte_wgg.get(ds["id"]) or dict(ds)
        e["traeger"] = ordne_zu(ds["titel"], traeger)
        if "gj" not in e and ds.get("share") and not args.nur_auswerten:
            wgg_versuche += 1
            try:
                namen = [name for _, name in pdf_links(ds["share"])]
                m = next((GJ.search(n) for n in namen if GJ.search(n)), None)
                e["gj"] = int(m.group(1)) if m else None
                time.sleep(PAUSE / 2)
            except (urllib.error.URLError, OSError) as err:
                print(f"  WGG {ds['id']}: {err}", file=sys.stderr)
                wgg_fehler += 1
        pruefberichte.append(e)
    if zu_viele_fehler(wgg_fehler, wgg_versuche):
        fehler.append(f"WGG-Prüfberichte: {wgg_fehler} von {wgg_versuche} Freigaben nicht lesbar")
    bescheinigungen = []
    for ds in btvg_ds:
        e = dict(ds)
        e["traeger"] = ordne_zu(ds["titel"], traeger)
        bescheinigungen.append(e)

    ueberblick, n_weitere, n_wgg_neu = baue_ueberblick(traeger, foerderungen, pruefberichte, bescheinigungen, sonst_ds)

    nicht_erkannt = sum(1 for f in foerderungen if f.get("pruefen"))
    print(f"Träger aus der Liste mit Dokumenten: {sum(1 for u in ueberblick if u['key'] in {tr['key'] for tr in traeger} and (u['foerderungen'] or u['als_vertreter'] or u['pruefberichte'] or u['btvg'] or u['sonstige']))}; "
          f"weitere Unternehmen: {n_weitere}; gemeinnützige Bauvereinigungen nur aus Prüfberichten/BTVG: {n_wgg_neu}; "
          f"Förderzusagen mit 'prüfen': {nicht_erkannt}", flush=True)

    schreibe_json(pfad, {
        "stand": stand,
        "quelle": "data.gv.at (Stadt Wien, Veröffentlichungen nach dem Informationsfreiheitsgesetz)",
        "parser_version": PARSER_VERSION,
        "traeger": ueberblick,
        "foerderungen": sorted(foerderungen, key=lambda f: (f.get("datum") or "", f["id"]), reverse=True),
        "pruefberichte": pruefberichte,
        "gemeindebauten": gb_info,
        "_datensaetze": {"foerderzusagen": zusagen_ds, "wgg": wgg_ds, "btvg": btvg_ds, "sonstige": sonst_ds},
    })
    for f in fehler:
        print("FEHLER:", f, file=sys.stderr)
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
