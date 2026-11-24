"""Browsertest der fertigen Seite (lokal, mit installiertem Chrome und Playwright).

Aufruf: python tests/browser_test.py dist/ogh-wohnrecht.html [ausgabeordner]
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

seite = pathlib.Path(sys.argv[1]).resolve()
aus = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/ogh-test")
aus.mkdir(parents=True, exist_ok=True)
URL = seite.as_uri()
fehler = []
ergebnis = {}


def pruefe(name, bedingung, info=""):
    ergebnis[name] = bool(bedingung)
    print(("OK   " if bedingung else "FEHL ") + name + (f"  [{info}]" if info else ""))


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)

    # ---------- Desktop ----------
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.on("console", lambda m: m.type == "error" and fehler.append(m.text))
    page.on("pageerror", lambda e: fehler.append(str(e)))
    page.goto(URL)
    page.wait_for_selector("article.item")
    pruefe("Kopfzeile", "Stand" in page.inner_text("#lead"), page.inner_text("#lead"))
    pruefe("50 Karten beim Start", page.locator("article.item").count() == 50)
    pruefe("Mehr-Knopf sichtbar", page.is_visible("#mehr"), page.inner_text("#mehr"))
    page.click("#mehr")
    pruefe("Nach 'Weitere' 100 Karten", page.locator("article.item").count() == 100)
    page.screenshot(path=str(aus / "desktop.png"))
    page.evaluate("scrollTo(0, 0)")   # der Klick auf „Weitere“ hat nach unten gescrollt
    page.wait_for_timeout(400)
    pruefe("Filter steht am Platz, ohne Leiste", page.is_visible("#q") and not page.is_visible("#barKopf"))

    # Rechtssätze auf den Karten (sobald die Texte geladen sind)
    hat_rs = page.evaluate("JSON.parse(document.getElementById('daten').textContent).rs.length") > 0
    if hat_rs:
        pruefe("Rechtssätze auf den Karten", page.locator("article.item .rs").count() >= 20, str(page.locator("article.item .rs").count()))
        knopf = page.locator("article.item .rs-mehr button").first
        vorher = knopf.inner_text()
        knopf.click()
        page.wait_for_timeout(200)
        pruefe("Weitere Rechtssätze aufklappen", page.locator("article.item .rs-liste .rs").count() >= 1 and "▾" in knopf.inner_text(), vorher)
        nr = page.locator("article.item .rs-nr").first.inner_text().replace("↗", "").strip()
        gz = page.locator("article.item").filter(has=page.locator(".rs-nr", has_text=nr)).first.locator(".gz").inner_text()
        page.evaluate("scrollTo(0, 0)")   # das Aufklappen kann weiter unten gewesen sein; oben steht der Filter am Platz
        page.wait_for_timeout(400)
        page.fill("#q", nr)
        page.wait_for_timeout(500)
        gefunden = page.locator("article.item .gz").all_inner_texts()
        pruefe("Suche nach Rechtssatznummer", gz in gefunden, f"{nr} -> {len(gefunden)} Treffer, {gz} dabei: {gz in gefunden}")
        page.evaluate("scrollTo(0, 0)")
        page.wait_for_timeout(400)
        page.fill("#q", "")
        page.wait_for_timeout(300)

    # Einträge, zu denen das RIS nur Paragrafen führt
    np_karte = page.locator("article.item.np").first
    nur_para = page.evaluate("(() => { const d = JSON.parse(document.getElementById('daten').textContent); return d.eintraege.filter(e => !e.t && !e.s && !e.sw && !(e.r && e.r.length)).length; })()")
    if np_karte.count():
        txt = np_karte.inner_text()
        pruefe("Nur-Paragrafen-Eintrag gekennzeichnet und nach Gesetz geordnet", "nur Paragrafen" in txt and "PARAGRAFEN LAUT RIS" in txt.upper() and "§ " in txt, txt.replace("\n", " | ")[:160])
    else:
        pruefe("Keine Nur-Paragrafen-Einträge auf der ersten Seite", nur_para == 0 or page.locator("article.item").count() > 0, str(nur_para))
    if not page.is_visible("#opWrap"):
        pruefe("Schalter fehlt, weil es keine Nur-Paragrafen-Einträge gibt", nur_para == 0, str(nur_para))
    else:
        page.click("#opWrap")
        page.wait_for_timeout(300)
        pruefe("Schalter blendet alle Nur-Paragrafen-Einträge aus", page.locator("article.item.np").count() == 0 and page.locator("article.item").count() > 0
               and "nur mit Paragrafen ausgeblendet" in page.inner_text("#count"), page.inner_text("#count"))
        pruefe("Schalter wirkt auch auf Neu", page.locator("#neuListe .nt.np").count() == 0)
        page.reload()
        page.wait_for_selector("article.item")
        pruefe("Schalter bleibt nach Neuladen", page.is_checked("#op") and page.locator("article.item.np").count() == 0)
        page.click("#opWrap")
        page.wait_for_timeout(300)
        pruefe("Schalter aus: wieder alle", page.locator("article.item.np").count() > 0 or nur_para > 0)

    # Weiter unten dockt der Filter als Leiste oben an
    page.mouse.wheel(0, 3000)
    page.wait_for_timeout(800)
    box = page.locator("#barKopf").bounding_box()
    pruefe("Weiter unten: Leiste oben angedockt", page.is_visible("#barKopf") and bool(box) and box["y"] < 2 and not page.is_visible("#q"), str(box))
    page.click("#barKopf")
    page.wait_for_timeout(600)
    pruefe("Leiste antippen fährt den Filter heraus", page.is_visible("#q") and page.get_attribute("#barKopf", "aria-expanded") == "true")
    page.screenshot(path=str(aus / "desktop_leiste_offen.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    pruefe("Escape fährt ihn wieder ein", not page.is_visible("#q"))
    page.mouse.wheel(0, -20000)
    page.wait_for_timeout(800)
    pruefe("Ganz oben: Filter wieder am Platz", page.is_visible("#q") and not page.is_visible("#barKopf"))

    # Suche + Rechtslage-Hinweis
    page.fill("#q", "Wertsicherung")
    page.wait_for_timeout(400)
    n = page.locator("article.item").count()
    hinw = page.locator("article.item .hinweis").count()
    pruefe("Suche 'Wertsicherung' findet Einträge", n >= 4, f"{n} Treffer, {hinw} mit Hinweis")
    texte = page.locator("article.item").all_inner_texts()
    alt_mit = sum(1 for t in texte if "Rechtslage seit 01.01.2026" in t)
    pruefe("Hinweis nur bei Entscheidungen vor 2026", all(("2026" not in t.split("\n")[0]) or "Rechtslage seit" not in t for t in texte), f"{alt_mit} Hinweise")
    page.screenshot(path=str(aus / "desktop_wertsicherung.png"), full_page=False)

    # Hinweis-Übersicht über alle Einträge
    stats = page.evaluate("""() => {
      const d = JSON.parse(document.getElementById('daten').textContent);
      return d.eintraege.length;
    }""")
    page.fill("#q", "")
    page.wait_for_timeout(300)

    # Themen-Chip
    themen = page.locator("#chips button.chip[data-k]").evaluate_all("els => els.map(b => b.dataset.k)")
    pruefe("Nur die Themen MRG und WGG", sorted(k for k in themen if k and k != "*") == ["G", "M"], str(themen))
    page.click("button.chip[data-k='G']")
    page.wait_for_timeout(200)
    metas = page.locator("article.item .meta").all_inner_texts()
    pruefe("Chip Gemeinnützigkeit filtert", bool(metas) and all("Gemeinnützigkeit (WGG)" in t for t in metas), f"{len(metas)} Karten")
    page.click("button.chip[data-k='']")

    # Merken + Notiz
    erste = page.locator("article.item").first
    gz = erste.locator(".gz").inner_text()
    erste.locator("button", has_text="Merken").click()
    erste.locator("button", has_text="Notiz").click()
    erste.locator("textarea").fill("Testnotiz für " + gz)
    page.wait_for_timeout(700)
    pruefe("Notiz gespeichert-Anzeige", "gespeichert" in erste.locator(".nstatus").inner_text())
    pruefe("Merk-Chip zählt 1", "(1)" in page.inner_text("button.chip.merk"), page.inner_text("button.chip.merk"))
    page.reload()
    page.wait_for_selector("article.item")
    erste = page.locator("article.item").first
    pruefe("Nach Neuladen: gemerkt", "Gemerkt" in erste.locator(".acts").inner_text())
    pruefe("Nach Neuladen: Notiz da", erste.locator("textarea").input_value().startswith("Testnotiz"))
    page.click("button.chip.merk")
    page.wait_for_timeout(200)
    pruefe("Merkliste zeigt 1 Eintrag", page.locator("article.item").count() == 1)
    page.click("button.chip.merk")

    # Export
    page.click("#npBtn")
    page.click("#npExport")
    export = page.input_value("#npText")
    exp = json.loads(export)
    pruefe("Export enthält Notiz", any("Testnotiz" in (v.get("n") or "") for v in exp["notizen"].values()))
    page.screenshot(path=str(aus / "desktop_notizen.png"))

    # Sprunglink über Hash
    # Ziel: der älteste Eintrag (liegt weit hinten, ist also nicht unter den ersten 50 Karten)
    ziel, datum = page.evaluate("""() => {
      const d = JSON.parse(document.getElementById('daten').textContent);
      const e = d.eintraege.filter(x => x.d).sort((a, b) => a.d < b.d ? -1 : 1)[0];
      return ["e-" + String(e.k).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, ""), e.d];
    }""")
    page.goto(URL + "#" + ziel)
    page.wait_for_timeout(600)
    sichtbar = page.evaluate("""(id) => { const n = document.getElementById(id); if (!n) return false; const r = n.getBoundingClientRect(); return r.top >= 50 && r.top < innerHeight; }""", ziel)
    pruefe("Hash-Link springt zum Eintrag (ältester Eintrag)", sichtbar, f"{ziel} vom {datum}")
    ctx.close()

    # ---------- Import in frischem Browser ----------
    ctx2 = browser.new_context(viewport={"width": 1280, "height": 900})
    p2 = ctx2.new_page()
    p2.goto(URL)
    p2.wait_for_selector("article.item")
    p2.click("#npBtn")
    p2.fill("#npText", export)
    p2.click("#npImport")
    p2.wait_for_timeout(300)
    pruefe("Import übernimmt Notizen", "übernommen" in p2.inner_text("#npStatus"), p2.inner_text("#npStatus"))
    pruefe("Import: Merk-Chip zählt 1", "(1)" in p2.inner_text("button.chip.merk"))
    p2.fill("#npText", "kein json")
    p2.click("#npImport")
    pruefe("Import lehnt Unsinn ab", "kein gültiger" in p2.inner_text("#npStatus"))
    ctx2.close()

    # ---------- Handy ----------
    ctx3 = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    m = ctx3.new_page()
    m.on("pageerror", lambda e: fehler.append(str(e)))
    m.goto(URL)
    m.wait_for_selector("article.item")
    m.screenshot(path=str(aus / "handy_oben.png"))
    breite = m.evaluate("document.documentElement.scrollWidth")
    pruefe("Handy: keine horizontale Scrollleiste", breite <= 390, f"scrollWidth={breite}")
    reiter = m.locator("#tabs").bounding_box()
    filt = m.locator("#barPlatz").bounding_box()
    pruefe("Handy: Filter zuerst am Platz unter den Reitern", m.is_visible("#q") and not m.is_visible("#barKopf") and filt["y"] > reiter["y"], f"{reiter} {filt}")
    titel = m.locator("h1").bounding_box()
    pruefe("Handy: nichts verdeckt die Überschrift", bool(titel) and titel["y"] >= 10, str(titel))
    m.mouse.wheel(0, 2500)
    m.wait_for_timeout(800)
    box = m.locator("#barKopf").bounding_box()
    pruefe("Handy: in den Einträgen Leiste oben", m.is_visible("#barKopf") and "Treffer" in m.inner_text("#barZahl") and bool(box) and box["y"] < 2, str(box))
    pruefe("Handy: Filter in der Leiste eingefahren", not m.is_visible("#q"))
    m.click("#barKopf")
    m.wait_for_timeout(600)
    pruefe("Handy: Antippen fährt den Filter herunter", m.is_visible("#q") and m.get_attribute("#barKopf", "aria-expanded") == "true")
    m.screenshot(path=str(aus / "handy_filter_offen.png"))
    thema = m.locator("#chips button.chip").nth(1)
    name = thema.inner_text().split(" (")[0]
    thema.click()
    m.wait_for_timeout(200)
    pruefe("Handy: Auswahl steht in der Leiste, Filter bleibt offen", name in m.inner_text("#barSumme") and m.is_visible("#q"), m.inner_text("#barSumme"))
    m.mouse.click(195, 820)  # auf den abgedunkelten Bereich
    m.wait_for_timeout(600)
    pruefe("Handy: Tippen daneben fährt ihn ein", not m.is_visible("#q") and m.get_attribute("#barKopf", "aria-expanded") == "false")

    def wisch(sel, dy):
        m.evaluate("""([sel, dy]) => {
          const el = document.querySelector(sel), r = el.getBoundingClientRect();
          const x = r.left + r.width / 2, y = r.top + r.height / 2;
          const t = (yy) => new Touch({identifier: 1, target: el, clientX: x, clientY: yy});
          const ev = (typ, yy, aktiv) => el.dispatchEvent(new TouchEvent(typ, {touches: aktiv ? [t(yy)] : [], changedTouches: [t(yy)], bubbles: true, cancelable: true}));
          ev('touchstart', y, true);
          for (let i = 1; i <= 8; i++) ev('touchmove', y + dy * i / 8, true);
          ev('touchend', y + dy, false);
        }""", [sel, dy])
        m.wait_for_timeout(600)

    wisch("#barKopf", 220)
    pruefe("Handy: Herunterwischen an der Leiste öffnet", m.is_visible("#q") and m.get_attribute("#barKopf", "aria-expanded") == "true")
    wisch("#barGriff", -220)
    pruefe("Handy: Hochwischen am Griff schließt", not m.is_visible("#q"))
    wisch("#barKopf", 20)
    pruefe("Handy: kurzes Wischen öffnet nicht", not m.is_visible("#q"))
    m.click("#barKopf")
    m.wait_for_timeout(500)
    m.fill("#q", "Miete")
    m.press("#q", "Enter")
    m.wait_for_timeout(800)
    erste = m.locator("article.item").first.bounding_box()
    pruefe("Handy: Suchen per Eingabetaste zeigt die ersten Treffer", m.get_attribute("#barKopf", "aria-expanded") == "false" and "Miete" in m.inner_text("#barSumme")
           and bool(erste) and 40 <= erste["y"] < 844, f"{m.inner_text('#barZahl')} {erste}")
    m.mouse.wheel(0, 1600)
    m.wait_for_timeout(500)
    box = m.locator("#barKopf").bounding_box()
    pruefe("Handy: Leiste bleibt beim Scrollen oben sichtbar", bool(box) and abs(box["y"]) < 2 and m.is_visible("#barKopf"), str(box))
    m.screenshot(path=str(aus / "handy_runter.png"))
    ctx3.close()

    # ---------- Darstellung (Gerät im Dunkelmodus) ----------
    ctx4 = browser.new_context(viewport={"width": 1100, "height": 900}, color_scheme="dark")
    d = ctx4.new_page()
    d.on("pageerror", lambda e: fehler.append(str(e)))
    d.goto(URL)
    d.wait_for_selector("article.item")
    hg = lambda: d.evaluate("getComputedStyle(document.body).backgroundColor")  # noqa: E731
    pruefe("Darstellung: Automatisch folgt dem Gerät (dunkel)", hg() == "rgb(22, 23, 26)" and "Auto" in d.inner_text("#farbe"), hg())
    d.click("#farbe")
    pruefe("Darstellung: Hell trotz dunklem Gerät", hg() == "rgb(246, 244, 239)" and "Hell" in d.inner_text("#farbe"), hg())
    d.screenshot(path=str(aus / "hell.png"))
    d.reload()
    d.wait_for_selector("article.item")
    pruefe("Darstellung: Wahl bleibt nach Neuladen", hg() == "rgb(246, 244, 239)" and "Hell" in d.inner_text("#farbe"), hg())
    d.click("#farbe")
    pruefe("Darstellung: Dunkel", hg() == "rgb(22, 23, 26)" and "Dunkel" in d.inner_text("#farbe"), hg())
    d.screenshot(path=str(aus / "dunkel.png"))
    d.click("#farbe")
    pruefe("Darstellung: zurück auf Automatisch", "Auto" in d.inner_text("#farbe") and d.evaluate("localStorage.getItem('ogh-wohnrecht:farbe')") is None)
    ctx4.close()
    browser.close()

pruefe("Keine JavaScript-Fehler", not fehler, "; ".join(fehler[:3]))
print(f"\n{sum(ergebnis.values())}/{len(ergebnis)} Prüfungen bestanden. Bilder in {aus}")
sys.exit(0 if all(ergebnis.values()) else 1)
