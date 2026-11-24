#!/usr/bin/env python3
"""Baut die eigenständige HTML-Seite aus den Daten in data/.

Liest:
  data/ogh_auswahl.json  Auswahl des OGH von ogh.gv.at (Grundbestand, von Hand geprüft)
  data/ogh_feed.json     neue Hervorhebungen aus dem OGH-Feed (optional, von abruf.py)
  data/ris.json          Entscheidungen aus dem RIS (optional, von abruf.py)
Schreibt:
  dist/ogh-wohnrecht.html  eine Datei, offline lauffähig, Daten eingebettet
  docs/index.html          dieselbe Seite für GitHub Pages

Aufruf: python scripts/seite_bauen.py [--stand JJJJ-MM-TT]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import shutil
import sys

BASIS = pathlib.Path(__file__).resolve().parent.parent
PLATZHALTER = "/*DATEN*/"
NEU_TAGE = 42

GZ_MUSTER = re.compile(r"^(\d+)([A-Za-z]+)(\d+)/(\d+)([A-Za-z])$")

# Reihenfolge = Vorrang, wenn eine Entscheidung mehrere Gesetze nennt.
# Gezeigt werden nur Entscheidungen zum MRG und zum WGG: Thema WGG vor MRG
THEMA_REGELN = [
    ("G", re.compile(r"^WGG\b")),
    ("M", re.compile(r"^MRG\b")),
]
MRG_WGG = re.compile(r"^(?:MRG|WGG)\b")
# Für Einträge ohne Normen (Auswahl von ogh.gv.at, die im RIS-Bestand fehlen): Erwähnung im Text
MRG_WGG_TEXT = re.compile(r"\b(?:MRG|WGG|Mietrechtsgesetz\w*|Wohnungsgemeinnützigkeitsgesetz\w*)\b")
WGG_TEXT = re.compile(r"\b(?:WGG|Wohnungsgemeinnützigkeitsgesetz\w*|gemeinnützige\w* Bauvereinigung\w*)\b", re.I)

ART = {
    "ordentliche erledigung (sachentscheidung)": "S",
    "zurückweisung mangels erheblicher rechtsfrage": "Z",
    "zurückweisung aus anderen gründen": "A",
    "verstärkter senat": "V",
}


def lade(pfad: pathlib.Path, standard):
    if not pfad.exists():
        return standard
    with pfad.open(encoding="utf-8") as f:
        return json.load(f)


def gz_schluessel(gz: str) -> str:
    return re.sub(r"\s+", "", (gz or "").replace("\u00a0", " "))


def gz_anzeige(gz: str) -> str:
    k = gz_schluessel(gz)
    m = GZ_MUSTER.match(k)
    if not m:
        return re.sub(r"\s+", " ", (gz or "").replace("\u00a0", " ")).strip()
    return f"{m.group(1)} {m.group(2)} {m.group(3)}/{m.group(4)}{m.group(5)}"


def thema_aus_normen(normen: list[str]) -> str:
    for code, muster in THEMA_REGELN:
        if any(muster.search(n.strip()) for n in normen):
            return code
    return "M"


def zu_mrg_wgg(e: dict) -> bool:
    """Gehört der Eintrag zum MRG oder WGG? Nach den Normen; ohne Normen nach dem Text."""
    if e.get("n"):
        return any(MRG_WGG.search(n.strip()) for n in e["n"])
    return bool(MRG_WGG_TEXT.search(" ".join(filter(None, (e.get("t"), e.get("s"))))))


def art_code(text: str | None) -> str | None:
    if not text:
        return None
    s = text.strip().lower()
    if s in ART:
        return ART[s]
    if "mangels erheblicher" in s:
        return "Z"
    if s.startswith("zurückweisung"):
        return "A"
    if "sachentscheidung" in s:
        return "S"
    if "verstärkt" in s:
        return "V"
    return None


def eindeutig(schluessel: str, belegt: dict, datum: str | None) -> str:
    """Hängt bei doppelten Geschäftszahlen das Datum an, damit Notizen und Links eindeutig bleiben."""
    if schluessel not in belegt:
        return schluessel
    kandidat = f"{schluessel}~{datum or 'x'}"
    n = 2
    while kandidat in belegt:
        kandidat = f"{schluessel}~{datum or 'x'}-{n}"
        n += 1
    return kandidat


# Normen, die auf der Seite gezeigt und gefiltert werden (die Rechtssätze nennen oft auch ZPO u. a.)
WOHNRECHT_NORM = re.compile(
    r"^(?:MRG|WEG(?:\s*2002)?|WGG|MaklerG|BTVG|HeizKG|RichtWG|MieWeG|LPG|KlGG|HbG)\b"
    r"|^ABGB\s*§\s*(?:109\d|11[01]\d|112[01]|364[a-c]?)\b")


def wohnrecht_normen(normen: list[str]) -> list[str]:
    return [n for n in normen if WOHNRECHT_NORM.search(n.strip())][:12]


# So liefert das RIS die Links zu Entscheidungstexten; die Seite setzt sie aus der Dokumentnummer wieder zusammen
RIS_DOK = re.compile(r"https://ogd\.ris\.bka\.gv\.at/Dokument\.wxe\?Abfrage=Justiz&Dokumentnummer=(JJT_[A-Z0-9_]+)")


def baue_eintraege(auswahl: list[dict], feed: list[dict], ris: list[dict]) -> list[dict]:
    eintraege: dict[str, dict] = {}
    nach_dok: dict[str, str] = {}

    # 1) RIS: vollständiger Bestand
    for r in ris:
        gzs = [g for g in (r.get("gz") or []) if g]
        if not gzs:
            continue
        k = gz_schluessel(gzs[0])
        if k in eintraege:
            vorher = eintraege[k]
            # gleiche Geschäftszahl, weiteres Dokument: Normen und Rechtssätze ergänzen, Link behalten
            for n in wohnrecht_normen(r.get("normen") or []):
                if n not in vorher["n"] and len(vorher["n"]) < 12:
                    vorher["n"].append(n)
            if r.get("rs"):
                x = vorher.setdefault("_rs", {"rs": [], "rsa": {}, "rss": []})
                x["rs"] += [nr for nr in r["rs"] if nr not in x["rs"]]
                x["rsa"].update(r.get("rsa") or {})
                x["rss"] += [nr for nr in r.get("rss") or [] if nr not in x["rss"]]
            if r.get("id"):
                nach_dok[r["id"]] = k
            continue
        normen = wohnrecht_normen(r.get("normen") or [])
        e = {
            "k": k,
            "gz": gz_anzeige(gzs[0]),
            "d": r.get("datum"),
            "th": thema_aus_normen(normen),
            "n": normen,
            "nd": r.get("veroeffentlicht") or r.get("neu_ab") or r.get("datum"),
        }
        if len(gzs) > 1:
            e["gzw"] = [gz_anzeige(g) for g in gzs[1:]]
        if r.get("veroeffentlicht"):
            e["v"] = r["veroeffentlicht"]
        if r.get("schlagworte"):
            e["sw"] = r["schlagworte"]
        a = art_code(r.get("art"))
        if a:
            e["a"] = a
        if r.get("url"):
            # Link zum Entscheidungstext: nur die Dokumentnummer, die Seite setzt den Link zusammen
            m = RIS_DOK.fullmatch(r["url"])
            e["u"] = m.group(1) if m else r["url"]
        if r.get("rs"):
            e["_rs"] = {"rs": r["rs"], "rsa": r.get("rsa") or {}, "rss": r.get("rss") or []}
        eintraege[k] = e
        if r.get("id"):
            nach_dok[r["id"]] = k

    # 2) Auswahl des OGH (Grundbestand): Titel, Kurztext und geprüftes Thema
    doppelt = {}
    for a in auswahl:
        doppelt[a["k"]] = doppelt.get(a["k"], 0) + 1
    for a in auswahl:
        k = a["k"]
        if k in eintraege and eintraege[k].get("o") is None and doppelt[k] == 1:
            e = eintraege[k]
            e["t"] = a.get("t")
            if a.get("s"):
                e["s"] = a["s"]
            e["th"] = a.get("th", e["th"])
            e["o"] = 1
            if a.get("p"):
                e["p"] = 1
            if not e.get("d"):
                e["d"] = a.get("d")
            continue
        neu = dict(a)
        neu["o"] = 1
        if doppelt[k] > 1:
            neu["p"] = 1
        neu["k"] = eindeutig(k, eintraege, a.get("d"))
        eintraege[neu["k"]] = neu

    # 3) Feed: neue Hervorhebungen des OGH, nur für Entscheidungen, die im Wohnrechts-Bestand sind
    for f in feed:
        k = None
        for dok in f.get("dokumente") or []:
            if dok in nach_dok:
                k = nach_dok[dok]
                break
        if k is None:
            for g in f.get("gz") or []:
                if gz_schluessel(g) in eintraege:
                    k = gz_schluessel(g)
                    break
        if k is None:
            continue
        e = eintraege[k]
        e["o"] = 1
        if not e.get("t") and f.get("titel"):
            e["t"] = f["titel"]
        if not e.get("s") and f.get("kurz"):
            e["s"] = f["kurz"]
        if f.get("link", "").startswith("https://"):
            e["ou"] = f["link"]

    # Nur MRG und WGG; das Thema richtet sich danach
    liste = [e for e in eintraege.values() if zu_mrg_wgg(e)]
    for e in liste:
        if e.get("n"):
            e["th"] = thema_aus_normen(e["n"])
        else:
            e["th"] = "G" if WGG_TEXT.search(" ".join(filter(None, (e.get("t"), e.get("s"))))) else "M"
    for e in liste:
        if not e.get("n"):
            e.pop("n", None)
        if e.get("nd") and e["nd"] == (e.get("v") or e.get("d")):
            e.pop("nd")   # ergibt sich auf der Seite aus Veröffentlichung bzw. Datum
    liste.sort(key=lambda e: ((e.get("d") or ""), e["k"]), reverse=True)
    return liste


# ---------------------------------------------------------------------------
# Rechtssätze: Text einmal je Rechtssatz, je Entscheidung nur Verweis, Beziehung und Beisätze
# ---------------------------------------------------------------------------

RS_TEXT_MAX = 280
BEISATZ_MAX = 120
BEISATZ_TEXT = re.compile(r"\b(Beisatz|nur)\s*:\s*(.+?)\s*(?:\(T(\d+)\)|$)", re.S)
BEISATZ_VERWEIS = re.compile(r"\b(Beis(?:atz)?|nur)\s+wie\s+T(\d+)|\bnur\s+T(\d+)", re.I)
# Reihenfolge auf der Karte: erstmals hier, bestätigt, ähnlich, vergleichbar, nur teilweise, vgl. aber, abweichend
RANG = {"s": 0, "a": 1, "": 2, "ae": 3, "v": 4, "n": 5, "va": 6, "g": 7}


def kuerze_text(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rsplit(" ", 1)[0].rstrip(",;:") + " …"


def beziehung(anm: str | None, stamm: bool) -> tuple[str, list[int], list[int], list[str]]:
    """Aus der Anmerkung der Kette: Beziehung (Kürzel), Beisätze und „nur“-Teile als T-Nummern
    sowie Beisätze ohne T-Nummer als Text."""
    a = anm or ""
    ohne = BEISATZ_TEXT.sub(" ", a).lower()
    if stamm:
        rel = "s"
    elif re.search(r"\b(gegenteilig|abweichend|ablehnend)\b", ohne):
        rel = "g"
    elif re.search(r"\bvgl\.?\s+aber\b", ohne):
        rel = "va"
    elif re.search(r"\bvgl\b", ohne):
        rel = "v"
    elif "ähnlich" in ohne:
        rel = "ae"
    elif re.search(r"\bauch\b", ohne):
        rel = "a"
    else:
        rel = ""
    beis, nur, frei = [], [], []
    for m in BEISATZ_TEXT.finditer(a):
        if m.group(3):
            (nur if m.group(1) == "nur" else beis).append(int(m.group(3)))
        else:
            frei.append(("Nur: " if m.group(1) == "nur" else "") + kuerze_text(m.group(2), BEISATZ_MAX))
    for m in BEISATZ_VERWEIS.finditer(a):
        if m.group(2):
            (nur if m.group(1).lower() == "nur" else beis).append(int(m.group(2)))
        elif m.group(3):
            nur.append(int(m.group(3)))
    if nur and rel not in ("s", "g", "va"):
        rel = rel or "n"
    eindeutig = lambda xs: list(dict.fromkeys(xs))  # noqa: E731
    return rel, eindeutig(beis), eindeutig(nur), frei


def verbinde_rechtssaetze(eintraege: list[dict], cache: dict) -> list[dict]:
    """Ersetzt die Rechtssatz-Angaben der Einträge durch Verweise ("r") auf eine Tabelle, die jeden
    Text nur einmal enthält: [{"n": Nummer, "j": Dokumentnummer, "t": Text, "b": {T-Nummer: Beisatz}}]."""
    tabelle: list[dict] = []
    index: dict[str, int] = {}
    for e in eintraege:
        x = e.pop("_rs", None)
        if not x:
            continue
        refs = []
        for nr in x["rs"]:
            c = cache.get(nr) or {}
            if not c.get("text"):
                continue
            if nr not in index:
                index[nr] = len(tabelle)
                tabelle.append({"n": nr, "j": c.get("id"), "t": kuerze_text(c["text"], RS_TEXT_MAX), "b": {}})
            i = index[nr]
            rel, beis, nur, frei = beziehung(x["rsa"].get(nr), nr in x["rss"])
            t_texte = c.get("t") or {}
            for tnr in beis + nur:
                if f"T{tnr}" in t_texte:
                    tabelle[i]["b"][str(tnr)] = kuerze_text(t_texte[f"T{tnr}"], BEISATZ_MAX)
            beis = [t for t in beis if str(t) in tabelle[i]["b"]]
            nur = [t for t in nur if str(t) in tabelle[i]["b"]]
            ref = [i, rel, beis + frei, nur]
            while ref and ref[-1] in ([], ""):
                ref.pop()
            refs.append(ref)
        refs.sort(key=lambda r: RANG.get(r[1] if len(r) > 1 else "", 2))
        if refs:
            e["r"] = refs
    for t in tabelle:
        if not t["b"]:
            del t["b"]
        if not t["j"]:
            del t["j"]
    return tabelle


def normen_tabelle(eintraege: list[dict]) -> list[str]:
    """Jede Norm nur einmal: die Einträge verweisen mit Nummern auf die Tabelle (spart rund 270 KB)."""
    tabelle: list[str] = []
    index: dict[str, int] = {}
    for e in eintraege:
        if e.get("n"):
            e["n"] = [index.setdefault(n, len(index)) for n in e["n"]]
    tabelle = [None] * len(index)
    for n, i in index.items():
        tabelle[i] = n
    return tabelle


def kompakt_wien(w: dict | None) -> dict | None:
    """Rubrik „Wohnbauträger Wien“: nur die Felder, die die Seite braucht."""
    if not w or not w.get("traeger"):
        return None

    def dok(x):
        return {k: v for k, v in {"t": kurztitel(x.get("titel")), "d": x.get("datum"), "gj": x.get("gj"), "u": x.get("link"), "s": x.get("share")}.items() if v}

    et_code = {"unternehmen": "j", "weg": "w", "meg": "m", "stadt": "s", "privat": "p"}
    foerd = []
    for f in w.get("foerderungen", []):
        e = {
            "id": f["id"], "gz": f.get("gz"), "d": f.get("datum"),
            "emp": f.get("empfaenger"), "efn": f.get("empfaenger_fn"),
            "et": et_code.get(f.get("empfaenger_typ"), "u"),
            "tr": f.get("traeger"), "ver": f.get("vertreter"), "vfn": f.get("vertreter_fn"), "vtr": f.get("vertreter_traeger"),
            "bez": f.get("bezirk"), "adr": f.get("adresse"), "kg": f.get("kg"), "m": f.get("massnahmen") or [],
            "wo": f.get("wohnungen"),
            "nr": f.get("nicht_rueckzahlbar") or 0, "dl": f.get("darlehen") or 0,
            "u": f.get("link"), "s": f.get("pdf"), "pr": f.get("pruefen") or [],
            "gb": [{"n": g.get("name"), "wo": g.get("wohnungen"), "bz": g.get("bauzeit") or []} for g in f.get("gemeindebau") or []],
        }
        foerd.append({k: v for k, v in e.items() if v not in (None, [], "")} | {"nr": e["nr"], "dl": e["dl"], "et": e["et"]})
    traeger = []
    for t in w["traeger"]:
        traeger.append({k: v for k, v in {
            "k": t["key"], "n": t["name"], "typ": t["typ"], "info": t.get("info"), "fn": t.get("fn"),
            "f": t.get("foerderungen", []), "v": t.get("als_vertreter", []),
            "snr": t.get("summe_nicht_rueckzahlbar", 0), "sdl": t.get("summe_darlehen", 0),
            "wgg": [dok(x) for x in t.get("pruefberichte", [])],
            "btvg": [dok(x) for x in t.get("btvg", [])],
            "sonst": [dok(x) for x in sorted(t.get("sonstige", []), key=lambda x: x.get("datum") or "", reverse=True)],
        }.items() if v is not None})
    gb = w.get("gemeindebauten") or None
    return {"stand": w.get("stand"), "traeger": traeger, "foerd": foerd,
            "gbs": {k: gb.get(k) for k in ("stand", "anzahl", "wohnungen", "zugeordnet", "stadt")} if gb else None}


def kurztitel(titel: str | None) -> str | None:
    """Titel ohne Absender „Stadt Wien – Wiener Wohnen“ und ohne IFG-Aktenzahl in Klammern."""
    if not titel:
        return titel
    t = re.sub(r"\s*\(\d+-\d{4}\)\s*$", "", titel)
    t = re.sub(r",?\s*Stadt Wien\s*[-–]\s*Wiener Wohnen\s*$", "", t)
    return t.strip() or titel


def kompakt_dokumente(d: dict | None) -> list[dict]:
    """Von Hand gepflegte Hintergrunddokumente (data/dokumente.json)."""
    aus = []
    for x in (d or {}).get("dokumente", []):
        e = {"o": x.get("ort"), "t": x.get("titel"), "d": x.get("datum"), "u": x.get("datensatz"), "s": x.get("datei"), "a": x.get("art")}
        if e["o"] and e["t"] and (e["u"] or e["s"]):
            aus.append({k: v for k, v in e.items() if v})
    return aus


def kompakt_vpi(v: dict | None) -> dict | None:
    """Indexrechner: Monatswerte je VPI-Basis (lückenlos ab „von“)."""
    if not v or not v.get("reihen"):
        return None
    return {"stand": v.get("stand"), "vorl": v.get("vorlaeufig", []),
            "r": [{"k": r["key"], "n": r["name"], "von": r["von"], "w": r["werte"]} for r in v["reihen"] if r.get("werte")]}


def baue_seite(vorlage: str, daten: dict) -> str:
    if vorlage.count(PLATZHALTER) != 1:
        raise SystemExit("Vorlage: Platzhalter fehlt oder kommt mehrfach vor.")
    roh = json.dumps(daten, ensure_ascii=False, separators=(",", ":"))
    # Schutz: Text in einem <script>-Block darf "</" nicht enthalten.
    roh = roh.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return vorlage.replace(PLATZHALTER, roh)


# Fassung für GitHub Pages: Manifest und Symbol, damit sich die Seite am Handy auf den Startbildschirm legen lässt.
# Die Einzeldatei in dist/ bleibt ohne diese Verweise (sie hätte die Dateien daneben nicht).
WEB_DATEIEN = ("manifest.webmanifest", "icon-192.png", "icon-512.png")
WEB_KOPF = ('<link rel="manifest" href="manifest.webmanifest">\n'
            '<link rel="icon" href="icon-192.png">\n'
            '<link rel="apple-touch-icon" href="icon-192.png">\n')


def fuer_web(html: str) -> str:
    return html.replace("</head>", WEB_KOPF + "</head>", 1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Baut dist/ogh-wohnrecht.html aus data/.")
    ap.add_argument("--stand", help="Datenstand JJJJ-MM-TT (Standard: heute, UTC)")
    ap.add_argument("--basis", default=str(BASIS), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    basis = pathlib.Path(args.basis)
    auswahl = lade(basis / "data" / "ogh_auswahl.json", [])
    feed = lade(basis / "data" / "ogh_feed.json", [])
    ris_datei = lade(basis / "data" / "ris.json", {})
    ris = ris_datei.get("eintraege", []) if isinstance(ris_datei, dict) else []

    eintraege = baue_eintraege(auswahl, feed, ris)
    stand = args.stand or dt.datetime.now(dt.timezone.utc).date().isoformat()
    quellen = (["ris"] if ris else []) + ["ogh"]
    rechtssaetze = verbinde_rechtssaetze(eintraege, lade(basis / "data" / "cache" / "rechtssaetze.json", {}))
    normen = normen_tabelle(eintraege)
    daten = {"stand": stand, "quellen": quellen, "neuTage": NEU_TAGE, "eintraege": eintraege, "rs": rechtssaetze, "normen": normen,
             "wien": kompakt_wien(lade(basis / "data" / "wien.json", None)),
             "vpi": kompakt_vpi(lade(basis / "data" / "vpi.json", None)),
             "dok": kompakt_dokumente(lade(basis / "data" / "dokumente.json", None))}

    vorlage = (basis / "vorlage" / "seite.html").read_text(encoding="utf-8")
    html = baue_seite(vorlage, daten)
    ziel = basis / "dist" / "ogh-wohnrecht.html"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(html, encoding="utf-8")
    # Dieselbe Seite für GitHub Pages (Quelle: Zweig main, Ordner /docs); .nojekyll: Datei unverändert ausliefern
    docs = basis / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "index.html").write_text(fuer_web(html), encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    for name in WEB_DATEIEN:
        shutil.copyfile(basis / "vorlage" / name, docs / name)
    print(f"{ziel.relative_to(basis)} und docs/index.html: {len(eintraege)} Entscheidungen, {len(html) // 1024} KB, Stand {stand}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
