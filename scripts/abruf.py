#!/usr/bin/env python3
"""Holt OGH-Entscheidungen zum Wohnrecht aus dem RIS und neue Hervorhebungen aus dem OGH-Feed.

Schreibt:
  data/ris.json       OGH-Entscheidungen (eine je Entscheidung, wird fortgeschrieben)
  data/ogh_feed.json  Entscheidungen, die der OGH auf ogh.gv.at vorstellt (wird fortgeschrieben)
  neu.md              Liste neuer Entscheidungen für die Benachrichtigung (nur wenn es welche gibt)

Datenquelle: Rechtsinformationssystem des Bundes (RIS), Open-Government-Data-Schnittstelle v2.6,
Lizenz CC BY 4.0. Kein KI-Aufruf, nur Standardbibliothek.

Vorgehen: Die Normen (z. B. „MRG §30“) sind im RIS nur bei den Rechtssätzen erfasst; eine Abfrage
nach Entscheidungstexten mit Norm liefert keine Treffer. Abgefragt werden daher alle Rechtssätze
(JJR_…) zu den Normen; jeder Rechtssatz nennt die Kette der Entscheidungen, die ihn anwenden,
mit Geschäftszahl, Datum, Entscheidungsart und Link zum Entscheidungstext (JJT_…). Daraus entsteht
die Liste der Entscheidungen. Jeder Lauf lädt den ganzen Bestand (wenige hundert Anfragen).

Die Entscheidungsart steht in den Ketten nur selten. Sie kommt aus den Entscheidungstexten
(Zivilrecht, OGH): jeder Lauf gleicht die im letzten Monat neu veröffentlichten Texte ab, einmalig
lädt --nachladen alle Texte ab --ab Jahr für Jahr (rund 550 Anfragen). Dabei kommen auch das
Veröffentlichungsdatum im RIS und fehlende Links dazu. Werte bleiben von Lauf zu Lauf erhalten.

Rechtssätze: Der Text eines Rechtssatzes (der vom OGH formulierte Rechtsgrundsatz) steht nur im
Dokument selbst. Jeder Lauf lädt die Texte, die noch fehlen (einmalig rund 3.600, danach wenige),
in data/cache/rechtssaetze.json. Die Beisätze (T1, T2 …) und die Anmerkungen je Entscheidung
(„Auch“, „Vgl“, „Beis wie T1“ …) kommen ohne Zusatzabruf aus den Ketten.

Aufruf:
  python scripts/abruf.py              wöchentlicher Lauf; neue Entscheidungen landen in neu.md
  python scripts/abruf.py --voll       Bestand neu aufbauen, ohne Benachrichtigung
  python scripts/abruf.py --nachladen  zusätzlich alle Entscheidungstexte ab --ab abgleichen
  --ab JJJJ-MM-TT                      nur Entscheidungen ab diesem Datum (Standard 2005-01-01)
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASIS = pathlib.Path(__file__).resolve().parent.parent
RIS_URL = "https://data.bka.gv.at/ris/api/v2.6/Judikatur"
FEED_URL = "https://www.ogh.gv.at/feed/"
SEITE_URL = "https://johnsweat.github.io/wohnrecht/"
UA = "wohnrecht/1.0 (+https://github.com/JohnSweat/wohnrecht; nicht-kommerzielles Nachschlagewerk, Abruf einmal pro Woche)"
PAUSE = 0.5          # Sekunden zwischen Anfragen
MAX_SEITEN = 200     # Sicherung gegen Endlosschleifen
MIN_ENTSCHEIDUNGEN = 500  # weniger gilt als Fehler der Abfrage, dann wird nichts überschrieben
MAX_SEITEN_TEXTE = 100    # je Zeitraum; ein Jahr Zivilrecht des OGH sind etwa 25 Seiten
RS_PAUSE = 0.3            # Sekunden zwischen Abrufen von Rechtssatz-Texten
RS_MAX_NEU = 4000         # höchstens so viele Rechtssatz-Texte je Lauf
RS_MINUTEN = 55           # Zeitbudget je Lauf; der Rest folgt im nächsten Lauf
FEED_KATEGORIE = "Urteile und Beschlüsse des OGH"

# Gesetze, deren Entscheidungen zum Wohnrecht zählen (Schreibweise wie in den RIS-Normen).
# Nur Mietrechtsgesetz und Wohnungsgemeinnützigkeitsgesetz (bis November 2026 auch WEG, ABGB-Bestandrecht u. a.)
GESETZE = ["MRG", "WGG"]
NORMEN = list(GESETZE)


class RisFehler(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Hilfen für die verschachtelten RIS-Antworten (aus XML erzeugtes JSON)
# ---------------------------------------------------------------------------

def finde(obj, schluessel: str):
    """Erster Wert zu einem Schlüssel (ohne Groß-/Kleinschreibung), Breitensuche durch dict/list."""
    ziel = schluessel.lower()
    stapel = [obj]
    while stapel:
        x = stapel.pop(0)
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k).lower() == ziel:
                    return v
            stapel.extend(x.values())
        elif isinstance(x, list):
            stapel.extend(x)
    return None


def als_liste(v) -> list[str]:
    """Normalisiert {"item": ...}, Listen, Strings und {"#text": ...} zu einer Liste von Strings."""
    if v is None:
        return []
    if isinstance(v, dict):
        for k in ("item", "#text", "value"):
            if k in v:
                return als_liste(v[k])
        return []
    if isinstance(v, list):
        aus = []
        for x in v:
            aus.extend(als_liste(x))
        return aus
    s = str(v).strip()
    return [s] if s else []


def als_text(v) -> str | None:
    teile = als_liste(v)
    return "; ".join(teile) if teile else None


def datum(v) -> str | None:
    s = als_text(v)
    if not s:
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def treffer_gesamt(antwort) -> int | None:
    hits = finde(antwort, "Hits")
    if isinstance(hits, dict):
        hits = hits.get("#text", hits.get("value"))
    try:
        return int(str(hits).strip())
    except (TypeError, ValueError):
        return None


def dokumente(antwort) -> list:
    refs = finde(antwort, "OgdDocumentReference")
    if refs is None:
        return []
    return refs if isinstance(refs, list) else [refs]


def fehlermeldung(antwort) -> str | None:
    fehler = finde(antwort, "Error")
    if fehler:
        return json.dumps(fehler, ensure_ascii=False)[:400]
    return None


def wert(d, schluessel: str):
    """Wert eines direkten Schlüssels (ohne Groß-/Kleinschreibung), ohne Tiefensuche."""
    if not isinstance(d, dict):
        return None
    ziel = schluessel.lower()
    for k, v in d.items():
        if str(k).lower() == ziel:
            return v
    return None


def als_items(v) -> list[dict]:
    """{"item": [...]}, {"item": {...}}, Liste oder einzelnes dict -> Liste von dicts."""
    if isinstance(v, dict):
        return als_items(v["item"]) if "item" in v else [v]
    if isinstance(v, list):
        return [x for y in v for x in als_items(y)]
    return []


def dok_nummer(url: str | None) -> str | None:
    m = re.search(r"Dokumentnummer=([A-Za-z0-9_]+)", url or "")
    return m.group(1) if m else None


def gz_norm(gz: str) -> str:
    return re.sub(r"\s+", "", gz or "").lower()


def gz_liste(v) -> list[str]:
    """Geschäftszahlen als Liste; Rechtssätze führen alle Zahlen ihrer Kette in einem Feld („A; B; C“)."""
    return [g.strip() for x in als_liste(v) for g in x.split(";") if g.strip()]


def gz_jahr(gz: str) -> int | None:
    """Jahr aus der Geschäftszahl (5Ob200/25k -> 2025); das Entscheidungsjahr kann später liegen."""
    m = re.search(r"/(\d{2})\s*[A-Za-z]?\s*$", gz or "")
    if not m:
        return None
    jj = int(m.group(1))
    return 2000 + jj if jj <= dt.date.today().year % 100 else 1900 + jj


def lese_dokument(ref) -> dict:
    meta = finde(ref, "Metadaten") or ref
    tech = finde(meta, "Technisch") or {}
    allg = finde(meta, "Allgemein") or {}
    dok_id = als_text(finde(tech, "ID")) if tech else None
    url = als_text(finde(allg, "DokumentUrl")) if allg else None
    url = url or als_text(finde(meta, "DokumentUrl"))
    if not dok_id and url:
        m = re.search(r"Dokumentnummer=([A-Z0-9_]+)", url)
        if m:
            dok_id = m.group(1)
    return {
        "id": dok_id,
        "gz": gz_liste(finde(meta, "Geschaeftszahl")),
        "datum": datum(finde(meta, "Entscheidungsdatum")),
        "veroeffentlicht": datum(finde(allg, "Veroeffentlicht")) if allg else None,
        "normen": als_liste(finde(meta, "Normen")),
        "schlagworte": als_text(finde(meta, "Schlagworte")),
        "art": als_text(finde(meta, "Entscheidungsart")),
        "rs": als_liste(finde(meta, "Rechtssatznummern")),
        "url": url if url and url.startswith("https://") else None,
    }


def inhalt_urls(ref) -> dict[str, str]:
    """Links zum Inhalt eines Dokuments je Format (xml, html, rtf, pdf)."""
    aus = {}
    for it in als_items(finde(ref, "ContentUrl")):
        typ = (als_text(wert(it, "DataType")) or "").lower()
        url = als_text(wert(it, "Url"))
        if typ and url and url.startswith("https://"):
            aus[typ] = url
    return aus


def lese_rechtssatz(ref) -> dict:
    """Ein Rechtssatz (JJR_) mit der Kette der Entscheidungen, die ihn anwenden."""
    rs = lese_dokument(ref)
    meta = finde(ref, "Metadaten") or ref
    kette = []
    for it in als_items(finde(meta, "Entscheidungstexte")):
        url = als_text(wert(it, "DokumentUrl"))
        kette.append({
            "id": dok_nummer(url),
            "gz": gz_liste(wert(it, "Geschaeftszahl")),
            "datum": datum(wert(it, "Entscheidungsdatum")),
            "art": als_text(wert(it, "Entscheidungsart")),
            "gericht": als_text(wert(it, "Gericht")),
            "url": url if url and url.startswith("https://") else None,
            "anm": als_text(wert(it, "Anmerkung")),
        })
    rs["kette"] = kette
    rs["xml"] = inhalt_urls(ref).get("xml")
    return rs


BEISATZ = re.compile(r"\b(Beisatz|nur)\s*:\s*(.+?)\s*\(T(\d+)\)", re.S)


def t_texte(anmerkung: str | None) -> dict[str, str]:
    """Beisätze aus der Anmerkung eines Kettenglieds: „Beisatz: … (T3)“ und „nur: … (T3)“ -> {"T3": "…"}."""
    return {"T" + m.group(3): re.sub(r"\s+", " ", m.group(2)).strip() for m in BEISATZ.finditer(anmerkung or "")}


def rechtssatz_text(daten: bytes) -> str | None:
    """Text des Rechtssatzes aus dem RIS-Dokument (XML): Absätze mit ct="rechtssatz"."""
    teile = []
    for el in ET.fromstring(daten).iter():
        if el.tag.rsplit("}", 1)[-1] == "absatz" and el.get("ct") == "rechtssatz":
            t = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
            if t:
                teile.append(t)
    return " ".join(teile) or None


# ---------------------------------------------------------------------------
# Abruf
# ---------------------------------------------------------------------------

def hole(url: str, accept: str, versuche: int = 4) -> bytes:
    letzter = None
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
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


def ris_seite(params: dict) -> dict:
    url = RIS_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    roh = hole(url, "application/json")
    try:
        return json.loads(roh)
    except json.JSONDecodeError as err:
        raise RisFehler(f"RIS lieferte kein JSON ({err}); Anfang: {roh[:200]!r}") from err


def frage_norm(norm: str) -> tuple[list[dict], int | None]:
    """Alle Rechtssätze des OGH zu einer Norm, mit Entscheidungskette."""
    basis = {
        "Applikation": "Justiz",
        "Gericht": "OGH",
        "Norm": norm,
        # Nur Rechtssätze. Der Schalter braucht die Vorsilbe „Dokumenttyp“, sonst ignoriert das RIS
        # ihn. Entscheidungstexte haben keine Normen und liefern mit Norm keine Treffer.
        "DokumenttypSucheInRechtssaetzen": "true",
        "DokumenteProSeite": "OneHundred",
    }
    gefunden: list[dict] = []
    gesamt = None
    for seite in range(1, MAX_SEITEN + 1):
        antwort = ris_seite(dict(basis, Seitennummer=str(seite)))
        f = fehlermeldung(antwort)
        if f:
            raise RisFehler(f"RIS meldet einen Fehler für Norm {norm!r}: {f}")
        if gesamt is None:
            gesamt = treffer_gesamt(antwort)
        refs = dokumente(antwort)
        if not refs:
            break
        gefunden.extend(lese_rechtssatz(r) for r in refs)
        if gesamt is not None and len(gefunden) >= gesamt:
            break
        time.sleep(PAUSE)
    return gefunden, gesamt


def lade_json(pfad: pathlib.Path, standard):
    if not pfad.exists():
        return standard
    with pfad.open(encoding="utf-8") as f:
        return json.load(f)


def schreibe_json(pfad: pathlib.Path, daten) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")
    tmp.replace(pfad)


def abruf_ris(ab: str, alt: dict) -> tuple[dict, list[str], dict, dict]:
    """Fragt alle Normen ab und baut daraus die Entscheidungen.
    Rückgabe: Einträge je ID, neue IDs, Statistik, Angaben je Rechtssatznummer (Dokument, Link, Beisätze).

    ID einer Entscheidung ist die Dokumentnummer des Entscheidungstexts (JJT_…), ohne Link
    „GZ:<Geschäftszahl>“. Normen und Rechtssatznummern werden über alle Rechtssätze gesammelt,
    Schlagworte nur von Rechtssätzen, die in dieser Entscheidung erstmals formuliert wurden.
    """
    heute = dt.datetime.now(dt.timezone.utc).date().isoformat()
    erstlauf = not alt
    entsch: dict[str, dict] = {}
    nach_gz: dict[str, str] = {}
    rs_info: dict[str, dict] = {}
    st = {"normen": {}, "rechtssaetze": 0, "fremd": 0, "kette": 0, "ohne_kette": 0, "andere_gerichte": 0,
          "vor_ab": 0, "ohne_link": 0, "ohne_datum": 0}

    def uebernimm(k: dict, rs: dict, stamm: bool) -> None:
        gz = [g for g in k["gz"] if g]
        if not gz:
            return
        if k["gericht"] and k["gericht"].strip().upper() != "OGH":
            st["andere_gerichte"] += 1
            return
        if k["datum"] and k["datum"] < ab:
            st["vor_ab"] += 1
            return
        if not k["datum"]:
            st["ohne_datum"] += 1
        schluessel = gz_norm(gz[0])
        kid = nach_gz.get(schluessel)
        if kid is None:
            kid = k["id"] if (k["id"] or "").startswith("JJT_") else "GZ:" + schluessel
            entsch[kid] = {"id": kid, "gz": gz, "datum": k["datum"], "art": k["art"], "url": k["url"],
                           "normen": [], "rs": [], "schlagworte": None}
            nach_gz[schluessel] = kid
        e = entsch[kid]
        # Link nachtragen und auf die Dokumentnummer umschlüsseln, wenn sie erst jetzt bekannt ist
        if kid.startswith("GZ:") and (k["id"] or "").startswith("JJT_"):
            entsch.pop(kid)
            kid = k["id"]
            e["id"] = kid
            entsch[kid] = e
            nach_gz[schluessel] = kid
        for feld in ("datum", "art", "url"):
            e[feld] = e[feld] or k[feld]
        for n in rs["normen"]:
            if n not in e["normen"]:
                e["normen"].append(n)
        for r in rs["rs"]:
            if r not in e["rs"]:
                e["rs"].append(r)
        if stamm and rs.get("schlagworte") and not e["schlagworte"]:
            e["schlagworte"] = rs["schlagworte"]
        # Wie die Entscheidung zum Rechtssatz steht („Auch“, „Vgl“, „Beis wie T1“ …); Stammentscheidung extra
        nr = rs["rs"][0] if rs["rs"] else None
        if nr:
            if k.get("anm"):
                e.setdefault("rsa", {})[nr] = k["anm"]
            if stamm and nr not in e.setdefault("rss", []):
                e["rss"].append(nr)

    for norm in NORMEN:
        docs, gesamt = frage_norm(norm)
        st["normen"][norm] = {"treffer": gesamt, "geladen": len(docs)}
        print(f"  {norm:<14} Rechtssätze {gesamt!s:>6}  geladen {len(docs):>6}", flush=True)
        for rs in docs:
            if not (rs.get("id") or "").startswith("JJR_"):
                st["fremd"] += 1
                continue
            st["rechtssaetze"] += 1
            if rs["rs"]:
                info = rs_info.setdefault(rs["rs"][0], {"id": rs["id"], "xml": rs.get("xml"), "t": {}})
                for k in rs["kette"]:
                    info["t"].update(t_texte(k.get("anm")))
            # Stammentscheidung: die erste Geschäftszahl (dort wurde der Rechtssatz formuliert)
            stamm = gz_norm(rs["gz"][0]) if rs["gz"] else None
            for k in rs["kette"]:
                st["kette"] += 1
                if not k["url"]:
                    st["ohne_link"] += 1
                uebernimm(k, rs, stamm in {gz_norm(g) for g in k["gz"]})
            if not rs["kette"]:
                # ohne Kette nur die Geschäftszahlen; ein Datum gibt es nur, wenn es genau eine ist
                st["ohne_kette"] += 1
                for i, g in enumerate(rs["gz"]):
                    jahr = gz_jahr(g)
                    if jahr is not None and jahr < int(ab[:4]):
                        st["vor_ab"] += 1
                        continue
                    uebernimm({"id": None, "gz": [g], "datum": rs["datum"] if len(rs["gz"]) == 1 else None,
                               "art": None, "gericht": None, "url": None}, rs, i == 0)
        time.sleep(PAUSE)

    neue: list[str] = []
    for kid, e in entsch.items():
        vorher = alt.get(kid)
        if vorher is None:  # Entscheidung war vielleicht ohne Link bekannt
            vorher = next((alt[i] for i in ("GZ:" + gz_norm(e["gz"][0]),) if i in alt), None)
        if vorher:
            e["neu_ab"] = vorher.get("neu_ab")
            for feld in ("art", "veroeffentlicht", "url"):  # aus Entscheidungstexten ergänzt
                e[feld] = e.get(feld) or vorher.get(feld)
        else:
            e["neu_ab"] = e.get("datum") if erstlauf else heute
            if not erstlauf:
                neue.append(kid)
    st["entscheidungen"] = len(entsch)
    return entsch, sorted(neue), st, rs_info


def rechtssatz_reihenfolge(entsch: dict) -> list[str]:
    """Rechtssatznummern der Entscheidungen, die neuesten Entscheidungen zuerst."""
    folge: dict[str, None] = {}
    for e in sorted(entsch.values(), key=lambda x: x.get("datum") or "", reverse=True):
        for nr in e.get("rs") or []:
            folge.setdefault(nr, None)
    return list(folge)


def lade_rechtssatztexte(cache: dict, links: dict[str, str], folge: list[str], max_neu: int,
                         minuten: float = RS_MINUTEN) -> dict:
    """Lädt fehlende Rechtssatz-Texte (langsam, mit Pause). Nach fünf Fehlern in Folge oder wenn das
    Zeitbudget aufgebraucht ist, endet der Schritt; der nächste Lauf macht dort weiter."""
    heute = dt.datetime.now(dt.timezone.utc).date().isoformat()
    st = {"geladen": 0, "fehler": 0, "ohne_text": 0, "ohne_link": 0, "abgebrochen": False, "zeit_um": False}
    in_folge = 0
    ende = time.monotonic() + minuten * 60
    for nr in folge:
        if st["geladen"] >= max_neu:
            break
        if time.monotonic() > ende:
            st["zeit_um"] = True
            break
        c = cache.setdefault(nr, {})
        if c.get("text"):
            continue
        if not links.get(nr):
            st["ohne_link"] += 1
            continue
        try:
            text = rechtssatz_text(hole(links[nr], "application/xml"))
            in_folge = 0
        except (urllib.error.URLError, OSError, ET.ParseError) as err:
            st["fehler"] += 1
            in_folge += 1
            print(f"  Rechtssatz {nr}: {err}", file=sys.stderr, flush=True)
            if in_folge >= 5:
                st["abgebrochen"] = True
                break
            continue
        if text:
            c["text"] = text
            c["geladen"] = heute
            st["geladen"] += 1
        else:
            st["ohne_text"] += 1
        time.sleep(RS_PAUSE)
    return st


def frage_texte(zeit: dict):
    """Entscheidungstexte des OGH (Zivilrecht) in einem Zeitraum, Seite für Seite."""
    basis = {"Applikation": "Justiz", "Gericht": "OGH", "Rechtsgebiet": "Zivilrecht",
             "DokumenttypSucheInEntscheidungstexten": "true", "DokumenteProSeite": "OneHundred"}
    gesamt, n = None, 0
    for seite in range(1, MAX_SEITEN_TEXTE + 1):
        antwort = ris_seite(dict(basis, Seitennummer=str(seite), **zeit))
        f = fehlermeldung(antwort)
        if f:
            raise RisFehler(f"RIS meldet einen Fehler bei Entscheidungstexten {zeit}: {f}")
        if gesamt is None:
            gesamt = treffer_gesamt(antwort)
        refs = dokumente(antwort)
        if not refs:
            break
        for r in refs:
            n += 1
            yield lese_dokument(r)
        if gesamt is not None and n >= gesamt:
            break
        time.sleep(PAUSE)


def ergaenze_aus_texten(entsch: dict, zeitraeume: list[dict]) -> dict:
    """Entscheidungsart, Veröffentlichungsdatum und fehlende Links aus den Entscheidungstexten."""
    nach_gz = {gz_norm(e["gz"][0]): k for k, e in entsch.items() if e.get("gz")}
    st = {"texte": 0, "zugeordnet": 0, "art": 0, "link": 0}
    for zeit in zeitraeume:
        for d in frage_texte(zeit):
            st["texte"] += 1
            k = d["id"] if d.get("id") in entsch else next((nach_gz[g] for g in map(gz_norm, d["gz"]) if g in nach_gz), None)
            if k is None:
                continue
            e = entsch[k]
            st["zugeordnet"] += 1
            if d.get("art") and e.get("art") != d["art"]:
                e["art"] = d["art"]
                st["art"] += 1
            if d.get("veroeffentlicht"):
                e["veroeffentlicht"] = d["veroeffentlicht"]
            if d.get("url") and not e.get("url"):
                e["url"] = d["url"]
                st["link"] += 1
        time.sleep(PAUSE)
    return st


# ---------------------------------------------------------------------------
# OGH-Feed (ogh.gv.at, WordPress-RSS)
# ---------------------------------------------------------------------------

NS = {"content": "http://purl.org/rss/1.0/modules/content/"}


def reiner_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def kuerze(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: n - 1].rsplit(" ", 1)[0] + " …"


def bereinige_gz(g: str) -> str:
    # In den Links des Feeds steht die GZ URL-kodiert, Leerzeichen teils als "+" (2+Ob+98/26i)
    return re.sub(r"\s+", " ", g.replace("\u00a0", " ").replace("+", " ")).strip()


# Der OGH stellt unter "Urteile und Beschlüsse" auch seine Verhandlungsspiegel ein (Termine der mündlichen
# Verhandlungen). Das sind keine Entscheidungen.
def ist_entscheidung(e: dict) -> bool:
    return not (e.get("titel") or "").lower().startswith("verhandlungsspiegel")


# In die Benachrichtigung kommt ein Feed-Beitrag nur mit Bezug zu MRG oder WGG, so wie auf der Seite:
# seine Entscheidung ist unter den RIS-Treffern zu MRG/WGG, oder Titel bzw. Kurztext nennen eines der Gesetze.
BEZUG_TEXT = re.compile(r"\b(?:MRG|WGG|Mietrechtsgesetz\w*|Wohnungsgemeinnützigkeitsgesetz\w*)\b")


def gz_schluessel(g: str) -> str:
    return re.sub(r"\s+", "", g or "").lower()


def mit_bezug(feed: list[dict], eintraege: dict) -> list[dict]:
    gzs = {gz_schluessel(g) for e in eintraege.values() for g in (e.get("gz") or [])}
    jjt = set()
    for e in eintraege.values():
        m = re.search(r"JJT_[0-9A-Z_]+", e.get("url") or "")
        if m:
            jjt.add(m.group(0))
    return [f for f in feed
            if {gz_schluessel(g) for g in f.get("gz") or []} & gzs
            or set(f.get("dokumente") or []) & jjt
            or BEZUG_TEXT.search(f"{f.get('titel') or ''} {f.get('kurz') or ''}")]


def lese_feed(xml_bytes: bytes) -> list[dict]:
    wurzel = ET.fromstring(xml_bytes)
    aus = []
    for item in wurzel.iter("item"):
        kategorien = [(c.text or "").strip() for c in item.findall("category")]
        if FEED_KATEGORIE not in kategorien:
            continue
        if not ist_entscheidung({"titel": reiner_text(item.findtext("title") or "")}):
            continue
        inhalt = item.findtext("content:encoded", default="", namespaces=NS) or ""
        beschreibung = item.findtext("description", default="") or ""
        roh = inhalt + " " + beschreibung
        doks = sorted(set(re.findall(r"Dokumentnummer=(JJT_[0-9A-Z_]+)", roh)))
        gzs = []
        for g in re.findall(r"[?&](?:amp;)?GZ=([^&\"'<>\s]+)", roh):
            gz = bereinige_gz(urllib.parse.unquote(g))
            if gz and gz not in gzs:
                gzs.append(gz)
        try:
            tag = email.utils.parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            tag = None
        aus.append({
            "titel": reiner_text(item.findtext("title") or ""),
            "link": (item.findtext("link") or "").strip(),
            "datum": tag,
            "dokumente": doks,
            "gz": gzs,
            "kurz": kuerze(reiner_text(beschreibung), 300),
        })
    return aus


def abruf_feed(alt: list[dict]) -> tuple[list[dict], list[dict]]:
    neu = lese_feed(hole(FEED_URL, "application/rss+xml, application/xml;q=0.9"))
    alt = [dict(e, gz=[bereinige_gz(g) for g in e.get("gz") or []]) for e in alt if ist_entscheidung(e)]
    bekannt = {e["link"] for e in alt}
    zugang = [e for e in neu if e["link"] not in bekannt]
    return alt + zugang, zugang


# ---------------------------------------------------------------------------
# Benachrichtigung
# ---------------------------------------------------------------------------

def gz_text(e: dict) -> str:
    return e["gz"][0] if e.get("gz") else e.get("id", "?")


def baue_neu_md(neue: list[dict], feed_neu: list[dict], stand: str) -> str | None:
    sach = [e for e in neue if not (e.get("art") or "").lower().startswith("zurückweisung")]
    zur = [e for e in neue if (e.get("art") or "").lower().startswith("zurückweisung")]
    if not sach and not zur and not feed_neu:
        return None
    zeilen = [f"**Stand {stand}.** Neu seit dem letzten Lauf: {len(sach)} Sachentscheidungen, {len(zur)} Zurückweisungen."]
    if feed_neu:
        zeilen += ["", "### Vom OGH auf ogh.gv.at vorgestellt"]
        for f in feed_neu:
            zeilen.append(f"- [{f['titel']}]({f['link']}) · {', '.join(f['gz']) or ''}")
    if sach:
        zeilen += ["", "### Sachentscheidungen"]
        for e in sorted(sach, key=lambda x: x.get("datum") or "", reverse=True)[:60]:
            normen = ", ".join(e.get("normen", [])[:3])
            link = f"[{gz_text(e)}]({e['url']})" if e.get("url") else gz_text(e)
            zeilen.append(f"- {link} · {e.get('datum') or ''} · {normen}")
        if len(sach) > 60:
            zeilen.append(f"- … und {len(sach) - 60} weitere")
    if zur:
        zeilen += ["", f"### Zurückweisungen ({len(zur)})", ", ".join(gz_text(e) for e in zur[:40])]
    zeilen += ["", f"Zur Seite: {SEITE_URL}"]
    return "\n".join(zeilen) + "\n"


def diagnose() -> int:
    """Nur Strukturangaben ins Protokoll (Feldnamen und Zahlen, keine Inhalte)."""
    from collections import Counter
    basis = {"Applikation": "Justiz", "Gericht": "OGH", "DokumenteProSeite": "OneHundred", "Seitennummer": "1"}
    # 1) Welche Felder haben die Kettenglieder der Rechtssätze?
    antwort = ris_seite(dict(basis, Norm="MRG", DokumenttypSucheInRechtssaetzen="true"))
    felder, typen, glieder = Counter(), Counter(), 0
    for ref in dokumente(antwort):
        for it in als_items(finde(finde(ref, "Metadaten") or ref, "Entscheidungstexte")):
            glieder += 1
            for k, v in it.items():
                if als_text(v):
                    felder[k] += 1
            typen[als_text(wert(it, "Dokumenttyp")) or "-"] += 1
    print(f"Kettenglieder (MRG, Seite 1): {glieder}; befüllte Felder {dict(felder)}; Dokumenttyp {dict(typen)}", flush=True)
    # 2) Welche Felder haben Entscheidungstexte des OGH?
    for zeit in ({"ImRisSeit": "EinemMonat"}, {"EntscheidungsdatumVon": "2005-01-01"}, {"EntscheidungsdatumVon": "2005-01-01", "Rechtsgebiet": "Zivilrecht"}):
        antwort = ris_seite(dict(basis, DokumenttypSucheInEntscheidungstexten="true", **zeit))
        f = Counter()
        docs = [lese_dokument(r) for r in dokumente(antwort)]
        for d in docs:
            for k in ("gz", "datum", "veroeffentlicht", "normen", "schlagworte", "art", "rs", "url"):
                if d.get(k):
                    f[k] += 1
        praefix = Counter((d.get("id") or "-")[:4] for d in docs)
        print(f"Entscheidungstexte OGH {zeit}: Treffer {treffer_gesamt(antwort)}, Fehler {fehlermeldung(antwort)}, "
              f"Seite 1: {len(docs)} Dokumente {dict(praefix)}, befüllt {dict(f)}", flush=True)
        time.sleep(PAUSE)
    # 3) Rechtssätze: Anmerkungen in der Kette, Links zum Inhalt und Aufbau des Inhalts (öffentliche Daten, CC BY 4.0)
    antwort = ris_seite(dict(basis, Norm="MRG §30", DokumenttypSucheInRechtssaetzen="true"))
    refs = dokumente(antwort)
    anm, beispiele = Counter(), []
    for ref in refs:
        for it in als_items(finde(finde(ref, "Metadaten") or ref, "Entscheidungstexte")):
            a = als_text(wert(it, "Anmerkung"))
            if a:
                anm[re.split(r"[:;]", a)[0].strip()[:30]] += 1
                if len(beispiele) < 20:
                    beispiele.append(a[:200])
    print(f"Anmerkungen in Ketten (MRG §30, Seite 1): {dict(anm.most_common(30))}", flush=True)
    for b in beispiele:
        print("  Anmerkung:", b, flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RIS- und OGH-Feed-Abruf für die Wohnrecht-Seite.")
    ap.add_argument("--voll", action="store_true", help="Bestand neu aufbauen, ohne Benachrichtigung")
    ap.add_argument("--ab", default="2005-01-01", help="nur Entscheidungen ab diesem Datum")
    ap.add_argument("--ohne-feed", action="store_true")
    ap.add_argument("--diagnose", action="store_true", help="nur Feldstatistik ins Protokoll, nichts speichern")
    ap.add_argument("--nachladen", action="store_true", help="alle Entscheidungstexte ab --ab abgleichen (einmalig)")
    ap.add_argument("--rs-max", type=int, default=RS_MAX_NEU, help="höchstens so viele Rechtssatz-Texte laden")
    ap.add_argument("--rs-minuten", type=float, default=RS_MINUTEN, help="Zeitbudget für Rechtssatz-Texte")
    ap.add_argument("--basis", default=str(BASIS), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.diagnose:
        return diagnose()
    basis = pathlib.Path(args.basis)
    pfad_ris = basis / "data" / "ris.json"
    pfad_feed = basis / "data" / "ogh_feed.json"
    stand = dt.datetime.now(dt.timezone.utc).date().isoformat()

    alt_datei = lade_json(pfad_ris, {})
    alt = {e["id"]: e for e in alt_datei.get("eintraege", [])} if isinstance(alt_datei, dict) else {}
    # Früherer Bestand aus Rechtssätzen (JJR_) passt nicht zum neuen Aufbau: verwerfen
    verworfen = sum(1 for i in alt if not (i.startswith("JJT_") or i.startswith("GZ:")))
    if verworfen or args.voll:
        print(f"Bestand wird neu aufgebaut ({len(alt)} bisherige Einträge, davon {verworfen} Rechtssätze)", flush=True)
        alt = {}
    print(f"RIS-Abruf, bisher {len(alt)} Entscheidungen", flush=True)

    fehler = []
    neue_ids: list[str] = []
    try:
        eintraege, neue_ids, st, rs_info = abruf_ris(args.ab, alt)
        gesamt = len(eintraege)
        if args.nachladen:
            bis = int(stand[:4])
            zeitraeume = [{"EntscheidungsdatumVon": f"{j}-01-01", "EntscheidungsdatumBis": f"{j}-12-31"}
                          for j in range(int(args.ab[:4]), bis + 1)]
        else:
            zeitraeume = [{"ImRisSeit": "EinemMonat"}]
        try:
            te = ergaenze_aus_texten(eintraege, zeitraeume)
            print(f"Entscheidungstexte ({'ab ' + args.ab if args.nachladen else 'neu seit einem Monat'}): {te['texte']} gelesen, "
                  f"{te['zugeordnet']} zugeordnet, Entscheidungsart {te['art']} neu, Links {te['link']} neu", flush=True)
        except (RisFehler, urllib.error.URLError, OSError) as err:
            fehler.append(f"RIS-Entscheidungstexte: {err}")
        print(f"RIS: {st['rechtssaetze']} Rechtssätze, {st['kette']} Kettenglieder -> {gesamt} Entscheidungen ab {args.ab}, davon neu {len(neue_ids)}", flush=True)
        mit = lambda feld: sum(1 for e in eintraege.values() if e.get(feld))  # noqa: E731
        print(f"Befüllt: Link {mit('url')}, Datum {mit('datum')}, Entscheidungsart {mit('art')}, Normen {mit('normen')}, Schlagworte {mit('schlagworte')}"
              f" | Rechtssätze ohne Kette {st['ohne_kette']}, andere Gerichte {st['andere_gerichte']}, vor {args.ab}: {st['vor_ab']},"
              f" ohne Link {st['ohne_link']}, ohne Datum {st['ohne_datum']}, keine Rechtssätze {st['fremd']}", flush=True)
        arten: dict[str, int] = {}
        for e in eintraege.values():
            arten[e.get("art") or "ohne Angabe"] = arten.get(e.get("art") or "ohne Angabe", 0) + 1
        print("Entscheidungsarten:", json.dumps(arten, ensure_ascii=False), flush=True)
        if st["fremd"]:
            fehler.append(f"{st['fremd']} Dokumente sind keine Rechtssätze – Abfrage prüfen.")
        if gesamt < MIN_ENTSCHEIDUNGEN:
            fehler.append(f"Unplausibel wenige Entscheidungen ({gesamt}) – nichts gespeichert, Abfrage prüfen.")
        elif alt and gesamt < 0.8 * len(alt) and alt_datei.get("normen") == NORMEN:
            # Schutz gegen eine kaputte Abfrage; gilt nicht, wenn sich die abgefragten Normen geändert haben
            fehler.append(f"Deutlich weniger Entscheidungen als bisher ({gesamt} statt {len(alt)}) – nichts gespeichert.")
        else:
            schreibe_json(pfad_ris, {
                "stand": stand,
                "quelle": "Rechtsinformationssystem des Bundes (RIS), CC BY 4.0",
                "aufbau": "Entscheidungen aus den Ketten der Rechtssätze",
                "normen": NORMEN,
                "eintraege": sorted(eintraege.values(), key=lambda e: e["id"]),
            })
            # Rechtssätze: Dokumentnummer und Beisätze aus diesem Lauf, fehlende Texte nachladen
            pfad_rs = basis / "data" / "cache" / "rechtssaetze.json"
            alt_rs = lade_json(pfad_rs, {})
            folge = rechtssatz_reihenfolge(eintraege)
            rs_cache = {}
            for nr in folge:
                c = dict(alt_rs.get(nr) or {})
                info = rs_info.get(nr)
                if info:
                    c["id"] = info["id"]
                    if info["t"]:
                        c["t"] = info["t"]
                    else:
                        c.pop("t", None)
                rs_cache[nr] = c
            rst = lade_rechtssatztexte(rs_cache, {nr: i["xml"] for nr, i in rs_info.items() if i.get("xml")}, folge,
                                       args.rs_max, args.rs_minuten)
            schreibe_json(pfad_rs, rs_cache)
            mit_text = sum(1 for c in rs_cache.values() if c.get("text"))
            print(f"Rechtssätze: {len(rs_cache)} zu den Entscheidungen, mit Text {mit_text}; neu geladen {rst['geladen']}, "
                  f"Fehler {rst['fehler']}, ohne Text {rst['ohne_text']}, ohne Link {rst['ohne_link']}"
                  + (" – abgebrochen nach fünf Fehlern in Folge, der nächste Lauf macht weiter" if rst["abgebrochen"] else "")
                  + (" – Zeitbudget aufgebraucht, der nächste Lauf macht weiter" if rst["zeit_um"] else ""), flush=True)
    except (RisFehler, urllib.error.URLError, OSError) as err:
        fehler.append(f"RIS: {err}")
        eintraege, neue_ids = alt, []

    feed_neu: list[dict] = []
    if not args.ohne_feed:
        try:
            feed_alt = lade_json(pfad_feed, [])
            feed, feed_neu = abruf_feed(feed_alt)
            schreibe_json(pfad_feed, feed)
            print(f"OGH-Feed: {len(feed)} Entscheidungen, davon neu {len(feed_neu)}", flush=True)
        except (urllib.error.URLError, OSError, ET.ParseError) as err:
            fehler.append(f"OGH-Feed: {err}")

    neu_md = baue_neu_md([eintraege[i] for i in neue_ids if i in eintraege],
                         mit_bezug(feed_neu, eintraege) if alt else [], stand)
    ziel = basis / "neu.md"
    if neu_md and alt and not fehler:
        ziel.write_text(neu_md, encoding="utf-8")
        print("neu.md geschrieben", flush=True)
    elif ziel.exists():
        ziel.unlink()

    for f in fehler:
        print("FEHLER:", f, file=sys.stderr)
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
