"""Browsertest für Suche, teilbare Links, Merkliste, Neu-Bereich, Druck, Gesetzeslinks und Richtwerte.

Aufruf: python tests/ergaenzungen_browser_test.py dist/ogh-wohnrecht.html [ausgabeordner]
Braucht Playwright für Python und Chrome bzw. Chromium (Pfad über die Umgebungsvariable CHROME_PFAD, siehe browser_hilfe.py).
"""
import json
import pathlib
import re
import sys

from browser_hilfe import ausgabeordner, chrome_optionen
from playwright.sync_api import sync_playwright

seite = pathlib.Path(sys.argv[1]).resolve()
aus = ausgabeordner(sys.argv[2] if len(sys.argv) > 2 else None, "ogh-test")
URL = seite.as_uri()
fehler = []
ergebnis = {}


def pruefe(name, bedingung, info=""):
    ergebnis[name] = bool(bedingung)
    print(("OK   " if bedingung else "FEHL ") + name + (f"  [{info}]" if info else ""))


def treffer(page):
    m = re.match(r"([\d.]+) von", page.inner_text("#count"))
    return int(m.group(1).replace(".", "")) if m else -1


def suche(page, text):
    page.fill("#q", text)
    page.wait_for_timeout(350)
    return treffer(page)


# Testdaten aus der Seite: eine Zurückweisung mit Geschäftszahl
html = seite.read_text(encoding="utf-8")
daten = json.loads(re.search(r'<script type="application/json" id="daten">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
zurueck = next((e for e in daten["eintraege"] if e.get("a") in ("Z", "A")), None)

with sync_playwright() as p:
    browser = p.chromium.launch(**chrome_optionen())
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="de-AT")
    page = ctx.new_page()
    page.on("pageerror", lambda e: fehler.append(str(e)))
    page.on("console", lambda m: m.type == "error" and fehler.append(m.text))
    page.goto(URL)
    page.wait_for_selector("article.item")

    # ---------- Suche ----------
    if zurueck:
        gz = zurueck["gz"]
        n = suche(page, gz)
        pruefe("Geschäftszahl findet auch eine ausgeblendete Zurückweisung", n >= 1 and gz in page.inner_text("#list"), f"{gz}: {n}")
        n2 = suche(page, gz.replace(" ", ""))
        pruefe("Geschäftszahl ohne Leerzeichen", n2 == n, f"{n2}")
    a, b, c = suche(page, "kündigung"), suche(page, "kuendigung"), suche(page, "Kundigung")
    pruefe("Umlaute: kündigung = kuendigung = Kundigung", a > 0 and a == b == c, f"{a}/{b}/{c}")
    p37, p37mrg, z37 = suche(page, "§ 37"), suche(page, "§ 37 MRG"), suche(page, "37")
    pruefe("Paragrafensuche: § 37 MRG enger als § 37, beide enger als „37“", 0 < p37mrg <= p37 < z37, f"{p37mrg}/{p37}/{z37}")
    pruefe("Paragrafensuche: MRG § 37 = § 37 MRG", suche(page, "MRG § 37") == p37mrg)

    # Treffer außerhalb der Filter
    page.select_option("#yr", page.locator("#yr option").nth(page.locator("#yr option").count() - 1).get_attribute("value"))
    suche(page, "Wertsicherung")
    pruefe("Hinweis auf Treffer außerhalb der Filter", page.is_visible(".verdeckt"), page.inner_text("#count"))
    page.click(".verdeckt button")
    page.wait_for_timeout(200)
    pruefe("„Alle Treffer zeigen“ hebt Jahr auf", page.input_value("#yr") == "" and treffer(page) > 0)

    # ---------- Teilbare Links ----------
    pruefe("Suche steht in der Adresse", "#ogh?q=Wertsicherung" in page.url, page.url[-60:])
    n = treffer(page)
    page2 = ctx.new_page()
    page2.on("pageerror", lambda e: fehler.append(str(e)))
    page2.goto(URL + "#ogh?q=Wertsicherung&th=M")
    page2.wait_for_selector("article.item")
    pruefe("Link öffnet Suche und Thema", page2.input_value("#q") == "Wertsicherung" and page2.get_attribute('#chips button[data-k="M"]', "aria-pressed") == "true"
           and 0 < treffer(page2) <= n, f"{treffer(page2)} <= {n}")
    page2.goto(URL + "#vpi?b=2020&von=2024-01&bis=2025-01&betrag=1.000&s=3")
    page2.wait_for_selector("#viewV:not([hidden])")
    erg = page2.inner_text("#vErgebnis")
    pruefe("Link öffnet Rechnung", "Jänner 2024" in erg and "Jänner 2025" in erg and "Betrag: 1.000,00" in erg, erg[:160].replace("\n", " | "))
    pruefe("Richtwerte und Kategoriebeträge", page2.is_visible("#rwTab") and "6,74" in page2.inner_text("#rwTab") and "4,51" in page2.inner_text("#katTab"))
    page2.goto(URL + "#wien?fet=s")
    page2.wait_for_selector("#viewW:not([hidden])")
    pruefe("Link öffnet Wien mit Filter", page2.input_value("#fet") == "s", page2.input_value("#fet"))
    page2.click("#tabE")
    pruefe("Wechsel zu OGH hinterlässt kein leeres „#“", not page2.url.endswith("#"), page2.url[-30:])
    page2.close()

    # ---------- Gesetzeslinks ----------
    suche(page, "")
    links = page.locator("a.norm").evaluate_all("els => els.map(e => e.href)")
    pruefe("Paragrafen verlinken auf das RIS", any("Gesetzesnummer=10002531&Paragraf=" in u for u in links), str(links[:2]))

    # ---------- Merkliste, verwaiste Notizen, Import ----------
    page.evaluate("""() => {
      const n = JSON.parse(localStorage.getItem('ogh-wohnrecht:notizen:v1') || '{}');
      n['9 Ob 99/99z'] = {n: 'alte Notiz', t: 1};
      localStorage.setItem('ogh-wohnrecht:notizen:v1', JSON.stringify(n));
    }""")
    page.reload()
    page.wait_for_selector("article.item")
    page.click('#chips button[data-k="*"]')
    pruefe("Notizen zu nicht mehr enthaltenen Einträgen sichtbar", page.is_visible(".verwaist") and "alte Notiz" in page.inner_text(".verwaist"))
    page.click(".verwaist button")
    pruefe("Verwaiste Notiz löschbar", not page.is_visible(".verwaist"))
    page.click('#chips button[data-k="*"]')
    page.click("#npBtn")
    page.fill("#npText", '{"x":1}')
    page.click("#npImport")
    pruefe("Import ohne Notizen meldet einen Fehler", "keine Notizen" in page.inner_text("#npStatus"), page.inner_text("#npStatus"))
    page.click("#npZu")

    # ---------- Neu seit dem letzten Besuch ----------
    page.evaluate("() => localStorage.setItem('ogh-wohnrecht:besuch', JSON.stringify({s: '2026-01-01'}))")
    page.reload()
    page.wait_for_selector("article.item")
    info = page.inner_text("#neuInfo") if page.is_visible("#neu") else ""
    pruefe("Neu: seit deinem letzten Besuch", "letzten Besuch" in info and page.locator(".neu-row .tag.neu").count() > 0, info)
    page.reload()
    page.wait_for_selector("article.item")
    info2 = page.inner_text("#neuInfo") if page.is_visible("#neu") else ""
    pruefe("Neu: Bezug bleibt nach dem Neuladen", info2 == info, info2)

    # ---------- Druck ----------
    suche(page, "Wertsicherung")
    n = treffer(page)
    page.emulate_media(media="print")
    page.evaluate("() => window.dispatchEvent(new Event('beforeprint'))")
    pruefe("Druck: alle Treffer geladen", page.locator("article.item").count() == n, f"{page.locator('article.item').count()} / {n}")
    pruefe("Druck: ohne Reiter, Filter und Knöpfe", not page.is_visible("#tabs") and not page.is_visible("#q") and not page.locator("article.item .acts").first.is_visible())
    page.pdf(path=str(aus / "druck.pdf"))
    page.emulate_media(media="screen")

    # ---------- Barrierefreiheit ----------
    pruefe("Trefferzahl wird angesagt", page.get_attribute("#count", "aria-live") == "polite")
    pruefe("Hauptbereich ausgezeichnet", page.locator("main").count() == 1)

    # ---------- Handy ----------
    hctx = browser.new_context(viewport={"width": 390, "height": 844}, locale="de-AT")
    h = hctx.new_page()
    h.on("pageerror", lambda e: fehler.append(str(e)))
    for ziel in ("", "#vpi", "#wien"):
        h.goto(URL + ziel)
        h.wait_for_timeout(400)
        breite = h.evaluate("document.documentElement.scrollWidth")
        pruefe(f"Handy {ziel or '#ogh'}: keine horizontale Scrollleiste", breite <= 390, str(breite))
    h.screenshot(path=str(aus / "handy_wien.png"))
    h.goto(URL + "#vpi")
    h.wait_for_timeout(300)
    h.screenshot(path=str(aus / "handy_vpi.png"), full_page=True)
    hctx.close()
    browser.close()

pruefe("Keine JavaScript-Fehler", not fehler, "; ".join(fehler[:3]))
print(f"\n{sum(ergebnis.values())}/{len(ergebnis)} Prüfungen bestanden. Bilder in {aus}")
sys.exit(0 if all(ergebnis.values()) else 1)
