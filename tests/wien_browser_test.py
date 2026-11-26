"""Ende-zu-Ende-Test der Rubrik „Wohnbauträger Wien“ und des Indexrechners ohne Netz.

Baut in einem Temp-Ordner Beispieldaten (vier Förderzusagen als Text, Prüfberichte, eine
BTVG-Bescheinigung, Gemeindebauten, ein Dokument von Wiener Wohnen, VPI-Reihen), wertet sie
mit wien.py aus, baut die Seite und prüft sie im Browser.

Aufruf: python tests/wien_browser_test.py [ausgabeordner]
"""
import json
import pathlib
import shutil
import sys
import tempfile

HIER = pathlib.Path(__file__).resolve().parent
REPO = HIER.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(HIER))

import seite_bauen  # noqa: E402
import wien  # noqa: E402
from test_skripte import FOERDERZUSAGE_BILD, FOERDERZUSAGE_PRIVAT, FOERDERZUSAGE_STADT, FOERDERZUSAGE_VERTRETEN, FOERDERZUSAGE_WEG  # noqa: E402
from browser_hilfe import ausgabeordner, chrome_optionen  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

aus = ausgabeordner(sys.argv[1] if len(sys.argv) > 1 else None, "ogh-wien-test")
ergebnis = {}


def pruefe(name, ok, info=""):
    ergebnis[name] = bool(ok)
    print(("OK   " if ok else "FEHL ") + name + (f"  [{info}]" if info else ""))


with tempfile.TemporaryDirectory() as tmp:
    basis = pathlib.Path(tmp)
    (basis / "data" / "cache" / "wien_texte").mkdir(parents=True)
    shutil.copytree(REPO / "vorlage", basis / "vorlage")   # Vorlage mit Manifest und Symbolen (seite_bauen kopiert sie nach docs/)
    shutil.copy(REPO / "data" / "ogh_auswahl.json", basis / "data" / "ogh_auswahl.json")
    shutil.copy(REPO / "data" / "wien_traeger.json", basis / "data" / "wien_traeger.json")
    shutil.copy(REPO / "data" / "dokumente.json", basis / "data" / "dokumente.json")

    # Gemeindebauten, verkleinert wie wien.py sie im Zwischenspeicher ablegt (Förderzusage der Stadt: Wien 10, Beispielhof 1)
    gb_xml = """<buildings><metadata><metadata_modified>2026-11-02</metadata_modified></metadata>
    <building><addresses><address><street>Beispielhof</street><streetnumber>1-3</streetnumber><zipcode>1100</zipcode></address></addresses>
    <buildingName>Beispielhof-Anlage</buildingName><id>1</id><numberOfFlats>120</numberOfFlats>
    <yearOfConstructions><yearOfConstruction><yearFrom>1928</yearFrom><yearTo>1930</yearTo></yearOfConstruction></yearOfConstructions></building>
    <building><addresses><address><street>Andere Gasse</street><streetnumber>2</streetnumber><zipcode>1020</zipcode></address></addresses>
    <buildingName>Andere Gasse 2</buildingName><id>2</id><numberOfFlats>30</numberOfFlats></building></buildings>"""
    (basis / "data" / "cache" / "gemeindebauten.json").write_text(json.dumps(wien.lies_gemeindebauten(gb_xml.encode("utf-8"))), encoding="utf-8")

    # VPI-Reihen: VPI 2020 ab Jänner 2020 (+0,3 % je Monat), VPI 1986 ab Jänner 1986; Oktober 2026 vorläufig
    def reihe(key, name, von_jahr, start, schritt):
        werte, monate = [], []
        j, m = von_jahr, 1
        while (j, m) <= (2026, 10):
            werte.append(round(start * schritt ** len(werte), 1))
            monate.append(f"{j:04d}-{m:02d}")
            j, m = (j + 1, 1) if m == 12 else (j, m + 1)
        return {"key": key, "name": name, "von": monate[0], "bis": monate[-1], "werte": werte}, dict(zip(monate, werte))
    r2020, w2020 = reihe("2020", "VPI 2020", 2020, 100.0, 1.003)
    r1986, w1986 = reihe("1986", "VPI 1986", 1986, 60.0, 1.002)
    (basis / "data" / "vpi.json").write_text(json.dumps({"stand": "2026-11-18", "vorlaeufig": ["2026-10"], "reihen": [r2020, r1986]}), encoding="utf-8")

    def ds(i, titel, dist, datum):
        return {"id": f"fz-{i}", "titel": titel, "beschreibung": "", "datum": datum,
                "link": f"https://www.data.gv.at/datasets/fz-{i}?locale=de", "share": f"https://dms.wien.gv.at/share/ifg/test{i}", "dist": dist}

    zusagen = [
        ds(1, "Förderzusage (1373304-2025)", "TES (1373304-2025)", "2026-08-05"),
        ds(2, "Förderzusage (481363-2026)", "ERH (481363-2026)", "2026-08-05"),
        ds(3, "Förderzusage (555555-2026)", "", "2026-02-10"),
        ds(4, "Förderzusage für Sockelsanierung (282608-2026)", "SOS (282608-2026)", "2026-05-20"),
        ds(5, "Förderzusage für Sockelsanierung (1234040-2025)", "SOS (1234040-2025)", "2026-01-15"),   # erste Seiten nur als Bild -> „prüfen“
    ]
    for d, text in zip(zusagen, [FOERDERZUSAGE_WEG, FOERDERZUSAGE_VERTRETEN, FOERDERZUSAGE_PRIVAT, FOERDERZUSAGE_STADT, FOERDERZUSAGE_BILD]):
        (basis / "data" / "cache" / "wien_texte" / f"{d['id']}.txt").write_text(text, encoding="utf-8")
    wgg = [{"id": "wgg-1", "titel": "MIGRA Gemeinnützige Wohnungsges.m.b.H. - Auszug gemäß § 28 Abs 8. WGG (120859-2026)", "datum": "2026-03-05",
            "link": "https://www.data.gv.at/datasets/wgg-1?locale=de", "share": "https://dms.wien.gv.at/share/ifg/wgg1", "dist": "", "gj": 2024}]
    btvg = [{"id": "btvg-1", "titel": "\"Heimbau\" Gemeinnützige Bau-, Wohnungs- u. Siedlungsgenossenschaft - Bescheinigung § 7 Abs 6 Z 3 lit c BTVG (1207564-2026)",
             "datum": "2026-11-12", "link": "https://www.data.gv.at/datasets/btvg-1?locale=de", "share": "https://dms.wien.gv.at/share/ifg/b1", "dist": ""}]
    wgg.append({"id": "wgg-2", "titel": "Gemeinnützige Bau- und Wohnungsgenossenschaft „Merkur“ registrierte Genossenschaft m.b.H. - Auszug gemäß § 28 Abs 8. WGG (746195-2026)",
                "datum": "2026-06-01", "link": "https://www.data.gv.at/datasets/wgg-2?locale=de", "share": "https://dms.wien.gv.at/share/ifg/wgg2", "dist": "", "gj": 2025})
    sonst = [{"id": "ww-1", "titel": "Hausordnung Stadt Wien - Wiener Wohnen (1169385-2025)", "datum": "2025-12-09", "traeger": "wiener-wohnen",
              "link": "https://www.data.gv.at/datasets/ww-1?locale=de", "share": "https://dms.wien.gv.at/share/ifg/ww1", "dist": ""}]
    (basis / "data" / "wien.json").write_text(json.dumps({"pruefberichte": wgg, "_datensaetze": {"foerderzusagen": zusagen, "wgg": wgg, "btvg": btvg, "sonstige": sonst}}), encoding="utf-8")

    pruefe("wien.py wertet aus", wien.main(["--nur-auswerten", "--basis", str(basis)]) == 0)
    daten = json.loads((basis / "data" / "wien.json").read_text(encoding="utf-8"))
    pruefe("5 Förderzusagen ausgewertet, eine mit „prüfen“", len(daten["foerderungen"]) == 5 and sum(1 for f in daten["foerderungen"] if f.get("pruefen")) == 1)
    stadt = [f for f in daten["foerderungen"] if f.get("empfaenger_typ") == "stadt"]
    pruefe("Gemeindebau zugeordnet", stadt and stadt[0].get("gemeindebau") == [{"name": "Beispielhof-Anlage", "wohnungen": 120, "bauzeit": [[1928, 1930]]}], str(stadt[0].get("gemeindebau") if stadt else None))
    pruefe("Prüfbericht ohne Listeneintrag wird eigener gemeinnütziger Träger",
           any(u["key"].startswith("wgg-") and u["typ"] == "gemeinnützig" and len(u["pruefberichte"]) == 1 for u in daten["traeger"]))
    pruefe("Kein Privatname in den Daten", "Mustermann" not in json.dumps(daten["foerderungen"], ensure_ascii=False))
    seite_bauen.main(["--basis", str(basis), "--stand", "2026-11-17"])
    seite = basis / "dist" / "ogh-wohnrecht.html"
    shutil.copy(seite, aus / "seite.html")
    pruefe("Kein Privatname in der Seite", "Mustermann" not in seite.read_text(encoding="utf-8"))

    fehler = []
    with sync_playwright() as p:
        b = p.chromium.launch(**chrome_optionen())
        for name, vp in (("desktop", {"width": 1280, "height": 900}), ("handy", {"width": 390, "height": 844})):
            ctx = b.new_context(viewport=vp, device_scale_factor=2 if name == "handy" else 1)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: fehler.append(str(e)))
            pg.goto(seite.as_uri() + "#wien")
            if name == "desktop":
                oben = pg.locator("#wbarPlatz").bounding_box()["y"] < pg.locator("#wTraeger").bounding_box()["y"]
                pruefe("desktop: Filter oben in der Rubrik am Platz, keine Leiste", not pg.is_visible("#wbarKopf") and pg.is_visible("#wq") and pg.is_visible("#fbez") and oben)
            pg.wait_for_selector("#viewW:not([hidden])")
            pruefe(f"{name}: #wien öffnet die Rubrik", pg.is_visible("#wTraeger") and not pg.is_visible("#list"))
            karten = pg.locator("#wTraeger article.tr")
            namen = karten.locator(".tr-name").all_inner_texts()
            pruefe(f"{name}: Träger mit Dokumenten", set(["Stadt Wien – Wiener Wohnen", "Österreichisches Siedlungswerk (ÖSW)", "MIGRA", "Heimbau"]).issubset(set(namen)), ", ".join(namen[:6]))
            pruefe(f"{name}: Sortierung nach Fördersumme", namen and namen[0] == "Stadt Wien – Wiener Wohnen", namen[0] if namen else "")
            pruefe(f"{name}: genannte Träger ohne Dokumente sichtbar", "WIGEBA (Gemeindebau Neu)" in namen and "Schönere Zukunft" in namen)
            pruefe(f"{name}: Hausverwaltungen nicht in der Standardansicht", "Muster Hausverwaltung GmbH" not in namen)
            pruefe(f"{name}: 5 Förderzusagen in der Liste", pg.locator("#wFoerd .fz").count() == 5)
            pruefe(f"{name}: Schalter „prüfen“ mit Anzahl", pg.is_visible("#fPrWrap") and "(1)" in pg.inner_text("#fPrText"), pg.inner_text("#fPrText"))
            pg.click("#fPrWrap")
            pg.wait_for_timeout(200)
            pruefe(f"{name}: Schalter blendet die Zusage mit „prüfen“ aus", pg.locator("#wFoerd .fz").count() == 4 and "1 mit „prüfen“ ausgeblendet" in pg.inner_text("#fCount")
                   and not any("prüfen" in t for t in pg.locator("#wFoerd .fz .meta").all_inner_texts()), pg.inner_text("#fCount"))
            pg.click("#fPrWrap")
            pg.wait_for_timeout(200)
            if name == "desktop":
                pg.screenshot(path=str(aus / "wien_desktop.png"), full_page=True)
                karten.first.locator("button", has_text="Details").click()
                txt = karten.first.inner_text()
                pruefe("Details zeigen Förderzusage", "57.888" in txt and "1.212.205" in txt and "vertreten durch Wiener Wohnen" in txt, txt.replace("\n", " ")[:160])
                pruefe("Wiener Wohnen: Kennzahlen Gemeindebauten", "2 Gemeindebauten mit 150 Wohnungen" in txt and "1 von 1 Förderzusagen der Stadt Wien einem Gemeindebau zugeordnet" in txt, txt.replace("\n", " ")[:200])
                pruefe("Förderzusage zeigt Gemeindebau", "Gemeindebau: Beispielhof-Anlage · 120 Wohnungen · erbaut 1928–1930" in txt)
                pruefe("Dokument von Wiener Wohnen mit kurzem Titel", "Hausordnung" in txt and "Hausordnung Stadt Wien" not in txt and "1169385" not in txt)
                namen_alle = karten.locator(".tr-name").all_inner_texts()
                pruefe("Bauvereinigung nur mit Prüfbericht in der Standardansicht", any("Merkur" in n for n in namen_alle), ", ".join(namen_alle[:12]))
                pruefe("Hintergrund-Dokumente der Stadt Wien", pg.is_visible("#wDokTitel") and pg.locator("#wDok .zeile").count() >= 4 and "Berichtsstandard" in pg.inner_text("#wDok"))
                pg.select_option("#fet", "p")
                pruefe("Filter Privatpersonen: 1", pg.locator("#wFoerd .fz").count() == 1)
                txt = pg.locator("#wFoerd .fz").first.inner_text()
                pruefe("Privatperson ohne Straße", "Privatperson" in txt and "Pfeilgasse" not in txt, txt.replace("\n", " ")[:120])
                pg.select_option("#fet", "w")
                txt = pg.locator("#wFoerd .fz").first.inner_text()
                pruefe("Eigentümergemeinschaft mit Hausverwaltung", "WEG MUSTERG 5-7" in txt and "Muster Hausverwaltung GmbH" in txt, txt.replace("\n", " ")[:140])
                pg.select_option("#fet", "")
                pg.select_option("#wtyp", "vertreter")
                namen_w = pg.locator("#wTraeger article.tr .tr-name").all_inner_texts()
                pruefe("Hausverwaltungen über den Filter", "Muster Hausverwaltung GmbH" in namen_w and "immo 360 grad gmbh - Zweig.nl. - Technik" in namen_w, ", ".join(namen_w))
                pg.select_option("#wtyp", "alle")
                pruefe("Alle Einträge", pg.locator("#wTraeger article.tr").count() >= 30)
                pg.click("#tabE")
                pg.wait_for_timeout(200)
                pruefe("Zurück zu Entscheidungen", pg.is_visible("#list") and not pg.is_visible("#wTraeger"))
            else:
                pg.screenshot(path=str(aus / "wien_handy.png"))
                breite = pg.evaluate("document.documentElement.scrollWidth")
                pruefe("Handy: keine horizontale Scrollleiste", breite <= 390, str(breite))
                pruefe("Handy Wien: Filter zuerst am Platz in der Rubrik", pg.is_visible("#wq") and pg.is_visible("#fet") and not pg.is_visible("#wbarKopf"))
                pg.mouse.wheel(0, 2500)
                pg.wait_for_timeout(800)
                box = pg.locator("#wbarKopf").bounding_box()
                pruefe("Handy Wien: weiter unten als Leiste oben", pg.is_visible("#wbarKopf") and bool(box) and box["y"] < 2, str(box))
                pruefe("Handy Wien: Leiste zeigt die Zahlen", "Träger" in pg.inner_text("#wbarZahl") and "5 Zusagen" in pg.inner_text("#wbarZahl"), pg.inner_text("#wbarZahl"))
                pruefe("Handy Wien: Filter zunächst eingefahren", not pg.is_visible("#wq") and not pg.is_visible("#fbez"))
                pg.click("#wbarKopf")
                pg.wait_for_timeout(600)
                pruefe("Handy Wien: Antippen zeigt beide Filterbereiche", pg.is_visible("#wq") and pg.is_visible("#fbez") and pg.is_visible("#fet"))
                pg.screenshot(path=str(aus / "wien_handy_filter.png"))
                pg.select_option("#fet", "w")
                pg.wait_for_timeout(200)
                pruefe("Handy Wien: Auswahl steht in der Leiste", "Eigentümergemeinschaften" in pg.inner_text("#wbarSumme") and "1 Zusage" in pg.inner_text("#wbarZahl"),
                       pg.inner_text("#wbarSumme") + " | " + pg.inner_text("#wbarZahl"))
                pg.click("#wbarZu")
                pg.wait_for_timeout(800)
                titel = pg.locator("#wFoerdTitel").bounding_box()
                # sichtbar unter der Leiste; ganz nach oben geht nur, wenn darunter genug Inhalt ist
                pruefe("Handy Wien: Fertig springt zu den Förderzusagen", not pg.is_visible("#fbez") and bool(titel) and 50 <= titel["y"] <= 844 - 40 and pg.evaluate("window.scrollY") > 1000,
                       f"{titel}, scrollY={pg.evaluate('window.scrollY')}")
                pruefe("Handy Wien: gefilterte Liste sichtbar", pg.locator("#wFoerd .fz").count() == 1 and "WEG MUSTERG" in pg.locator("#wFoerd .fz").first.inner_text())
                pg.screenshot(path=str(aus / "wien_handy_nach_filter.png"))
                pg.mouse.wheel(0, -20000)
                pg.wait_for_timeout(500)
                pg.click("#tabE")
                pg.wait_for_timeout(300)
                pruefe("Handy: Reiterwechsel zeigt den Filter der Entscheidungen am Platz", pg.is_visible("#q") and not pg.is_visible("#wq") and not pg.is_visible("#wbarKopf"))
            ctx.close()

        # ---------- Indexrechner ----------
        monate = ["Jänner", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
        def de(x, n=2):
            return f"{x:,.{n}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        for name, vp in (("desktop", {"width": 1280, "height": 900}), ("handy", {"width": 390, "height": 844})):
            ctx = b.new_context(viewport=vp, device_scale_factor=2 if name == "handy" else 1, locale="de-AT")
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: fehler.append(str(e)))
            pg.goto(seite.as_uri() + "#vpi")
            pg.wait_for_selector("#viewV:not([hidden])")
            erg = pg.inner_text("#vErgebnis")
            p_soll = (w2020["2026-10"] / w2020["2025-10"] - 1) * 100
            pruefe(f"{name} VPI: Standard VPI 2020, Oktober 2025 zu Oktober 2026", pg.input_value("#vBasis") == "2020" and "VPI 2020 (ab 01/2020)" in pg.locator("#vBasis option").all_inner_texts() and "Oktober 2025" in erg and "Oktober 2026" in erg
                   and f"+{de(p_soll)} %" in erg, erg.replace("\n", " | ")[:200])
            pruefe(f"{name} VPI: vorläufiger Wert gekennzeichnet", "vorläufig" in erg and "Vorläufiger Wert" in erg)
            pruefe(f"{name} VPI: keine Filterleiste", not pg.is_visible("#barKopf") and not pg.is_visible("#wbarKopf") and not pg.is_visible("#q"))
            if name == "desktop":
                pg.fill("#vBetrag", "1000")
                erg = pg.inner_text("#vErgebnis")
                pruefe("VPI: Betrag × Faktor", "Betrag:" in erg and de(1000 * w2020["2026-10"] / w2020["2025-10"]).split(",")[1] in erg.split("=")[-1], erg.split("\n")[-2:])
                pg.fill("#vSchwelle", "2")
                erg = pg.inner_text("#vErgebnis")
                a, m, gef = w2020["2025-10"], "2025-10", None
                for k in sorted(w2020):
                    if k > "2025-10" and abs(w2020[k] / a - 1) * 100 > 2:
                        gef = k
                        break
                soll = f"{monate[int(gef[5:]) - 1]} {gef[:4]}: "
                pruefe("VPI: Schwelle, erste Anpassung im richtigen Monat", "überschritten" in erg and "Anpassung" in erg and soll in erg, erg.replace("\n", " | ")[-200:])
                pg.fill("#vBetrag", "1.000")
                erg = pg.inner_text("#vErgebnis")
                pruefe("VPI: „1.000“ gilt als tausend", "Betrag: 1.000,00 ×" in erg, erg.replace("\n", " | ")[:200])
                pruefe("VPI: Rechnung steht in der Adresse", "#vpi?" in pg.url and "betrag=1.000" in pg.url and "s=2" in pg.url, pg.url[-80:])
                pg.select_option("#vBasis", "1986")
                erg = pg.inner_text("#vErgebnis")
                p86 = (w1986["2026-10"] / w1986["2025-10"] - 1) * 100
                pruefe("VPI: Wechsel auf VPI 1986 rechnet neu", "VPI 1986" in erg and f"+{de(p86)} %" in erg, erg.replace("\n", " | ")[:160])
                pg.select_option("#vVonJ", "1990")
                pg.select_option("#vVonM", "01")
                erg = pg.inner_text("#vErgebnis")
                pruefe("VPI: weit zurück im VPI 1986", "Jänner 1990" in erg)
                pruefe("VPI: Tabelle mit 13 Monaten", pg.locator("#vTabelle tbody tr").count() == 13)
                links = pg.locator("#vDok a").evaluate_all("els => els.map(e => e.href)")
                pruefe("VPI: Links zu Statistik Austria, MieWeG und Stellungnahme",
                       any("statistik.at/Indexrechner" in u for u in links) and any("Gesetzesnummer=20013068" in u for u in links) and any("dms.wien.gv.at" in u for u in links), str(links))
                pg.screenshot(path=str(aus / "vpi_desktop.png"), full_page=True)
                pg.click("#tabW")
                pg.wait_for_timeout(200)
                pruefe("VPI: zurück zur Rubrik Wien", pg.is_visible("#wTraeger") and not pg.is_visible("#vErgebnis"))
            else:
                breite = pg.evaluate("document.documentElement.scrollWidth")
                pruefe("Handy VPI: keine horizontale Scrollleiste", breite <= 390, str(breite))
                reiter = [t.strip() for t in pg.locator("#tabs .tab").all_inner_texts()]
                pruefe("Handy: kurze Reiternamen", reiter == ["OGH", "Wien", "Index"], str(reiter))
                pg.screenshot(path=str(aus / "vpi_handy.png"), full_page=True)
                pg.click("#tabE")
                pg.wait_for_timeout(300)
                pruefe("Handy: von VPI zu Entscheidungen mit Filter am Platz", pg.is_visible("#q") and not pg.is_visible("#barKopf"))
            ctx.close()
        b.close()
    pruefe("Keine JavaScript-Fehler", not fehler, "; ".join(fehler[:3]))

print(f"\n{sum(ergebnis.values())}/{len(ergebnis)} Prüfungen bestanden. Bilder in {aus}")
sys.exit(0 if all(ergebnis.values()) else 1)
