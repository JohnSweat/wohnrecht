"""Tests für die Abruf- und Auswerteskripte (ohne Netz).

Aufruf: python -m unittest discover -s tests -p "test_*.py"

Hinweis: Die RIS- und Feed-Beispiele bilden das erwartete Format nach (aus Dokumentation und
Open-Source-Clients). Ob die echte Schnittstelle genau so antwortet, zeigt erst der erste Lauf.
"""
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest

HIER = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent / "scripts"))

import abruf  # noqa: E402
import seite_bauen  # noqa: E402
import vpi  # noqa: E402
import wien  # noqa: E402

RIS_SEITE = {
    "OgdSearchResult": {
        "OgdDocumentResults": {
            "Hits": {"@pageNumber": "1", "@pageSize": "100", "#text": "2"},
            "OgdDocumentReference": [
                {"Data": {"Metadaten": {
                    "Technisch": {"ID": "JJT_20261001_OGH0002_0050OB00107_26K0000_000", "Applikation": "Justiz", "Organ": "OGH"},
                    "Allgemein": {"Veroeffentlicht": "2026-10-20", "Geaendert": "2026-10-21",
                                  "DokumentUrl": "https://www.ris.bka.gv.at/Dokument.wxe?Abfrage=Justiz&Dokumentnummer=JJT_20261001_OGH0002_0050OB00107_26K0000_000"},
                    "Judikatur": {"Dokumenttyp": "Text", "Geschaeftszahl": {"item": "5Ob107/26k"},
                                  "Normen": {"item": ["WEG 2002 §5 Abs2", "WEG 2002 §2 Abs2"]},
                                  "Entscheidungsdatum": "2026-10-01", "Schlagworte": "Abstellplatz; Bedarfsobjekt",
                                  "Justiz": {"Gericht": "OGH", "Entscheidungsart": "Ordentliche Erledigung (Sachentscheidung)",
                                             "Rechtssatznummern": {"item": "RS0123456"}}}}}},
                {"Data": {"Metadaten": {
                    "Technisch": {"ID": "JJT_20260915_OGH0002_0050OB00099_26X0000_000"},
                    "Allgemein": {"Veroeffentlicht": "2026-10-10"},
                    "Judikatur": {"Geschaeftszahl": {"item": ["5Ob99/26x", "5Ob100/26y"]},
                                  "Normen": {"item": "MRG §30 Abs2 Z1"}, "Entscheidungsdatum": "2026-09-15",
                                  "Justiz": {"Entscheidungsart": "Zurückweisung mangels erheblicher Rechtsfrage"}}}}},
            ],
        }
    }
}

def _kette(*glieder):
    return {"item": [
        {"Geschaeftszahl": {"item": g[0]}, "Dokumenttyp": "Text", "Gericht": g[4], "Entscheidungsart": g[2],
         "Entscheidungsdatum": g[1], "DokumentUrl": (f"https://www.ris.bka.gv.at/Dokument.wxe?Abfrage=Justiz&Dokumentnummer={g[3]}" if g[3] else None),
         "Anmerkung": g[5] if len(g) > 5 else None}
        for g in glieder]}


RIS_RS_SEITE = {
    "OgdSearchResult": {
        "OgdDocumentResults": {
            "Hits": {"#text": "4"},
            "OgdDocumentReference": [
                # Rechtssatz, erstmals 2019 formuliert, 2026 erneut angewendet
                {"Data": {"Metadaten": {
                    "Technisch": {"ID": "JJR_20190101_OGH0002_0050OB00001_19A0000_001"},
                    "Allgemein": {"Veroeffentlicht": "2019-02-01"},
                    "Judikatur": {"Dokumenttyp": "Rechtssatz", "Geschaeftszahl": {"item": "5Ob1/19a; 5Ob50/26b; 1R1/26a; 5Ob9/99z"},
                                  "Normen": {"item": ["MRG §30 Abs2 Z1"]}, "Entscheidungsdatum": "2019-01-01",
                                  "Schlagworte": "Kündigung; Eigenbedarf",
                                  "Justiz": {"Rechtssatznummern": {"item": "RS0100001"},
                                             "Entscheidungstexte": _kette(
                                                 ("5Ob1/19a", "2019-01-01", "Ordentliche Erledigung (Sachentscheidung)", "JJT_20190101_OGH0002_0050OB00001_19A0000_000", "OGH"),
                                                 ("5Ob50/26b", "2026-10-01", "Zurückweisung mangels erheblicher Rechtsfrage", "JJT_20261001_OGH0002_0050OB00050_26B0000_000", "OGH",
                                                  "Auch; Beis wie T1; Beisatz: Hier: Eigenbedarf für Enkel; (siehe auch § 30). (T2)"),
                                                 ("1R1/26a", "2026-05-01", "Sonstige", None, "OLG Wien"),
                                                 ("5Ob9/99z", "1999-01-01", "Ordentliche Erledigung (Sachentscheidung)", "JJT_19990101_OGH0002_0050OB00009_99Z0000_000", "OGH",
                                                  "Beisatz: Der Bedarf muss dringend sein. (T1)"))}}},
                          "Dokumentliste": {"ContentReference": {"Urls": {"ContentUrl": [
                              {"DataType": "Xml", "Url": "https://ogd.ris.bka.gv.at/Dokumente/Justiz/JJR_20190101_OGH0002_0050OB00001_19A0000_001/JJR_20190101_OGH0002_0050OB00001_19A0000_001.xml"},
                              {"DataType": "Html", "Url": "https://ogd.ris.bka.gv.at/Dokumente/Justiz/JJR_20190101_OGH0002_0050OB00001_19A0000_001/JJR_20190101_OGH0002_0050OB00001_19A0000_001.html"}]}}}}},
                # zweiter Rechtssatz zur selben Entscheidung 5Ob50/26b, andere Norm
                {"Data": {"Metadaten": {
                    "Technisch": {"ID": "JJR_20261001_OGH0002_0050OB00050_26B0000_001"},
                    "Judikatur": {"Geschaeftszahl": {"item": "5Ob50/26b"}, "Normen": {"item": "MRG §30 Abs2 Z8"},
                                  "Entscheidungsdatum": "2026-10-01", "Schlagworte": "Kündigung; Eigenbedarf; Enkel",
                                  "Justiz": {"Rechtssatznummern": {"item": "RS0200002"},
                                             "Entscheidungstexte": _kette(
                                                 ("5Ob50/26b", "2026-10-01", "Zurückweisung mangels erheblicher Rechtsfrage", "JJT_20261001_OGH0002_0050OB00050_26B0000_000", "OGH"))}}}}},
                # Rechtssatz ohne Kette: die Stammentscheidung selbst wird übernommen
                {"Data": {"Metadaten": {
                    "Technisch": {"ID": "JJR_20250303_OGH0002_0050OB00030_25C0000_001"},
                    "Judikatur": {"Geschaeftszahl": {"item": "5Ob30/25c"}, "Normen": {"item": "MRG §12a"},
                                  "Entscheidungsdatum": "2025-03-03", "Justiz": {"Rechtssatznummern": {"item": "RS0300003"}}}}}},
                # ohne Kette, mehrere Geschäftszahlen: alte fallen weg, neue ohne Datum
                {"Data": {"Metadaten": {
                    "Technisch": {"ID": "JJR_19980101_OGH0002_0010OB00007_98A0000_001"},
                    "Judikatur": {"Geschaeftszahl": "1Ob7/98a; 3Ob44/24m", "Normen": {"item": "ABGB §1096"},
                                  "Entscheidungsdatum": "2025-06-01", "Justiz": {"Rechtssatznummern": {"item": "RS0400004"}}}}}},
            ],
        }
    }
}

FEED = (HIER / "fixtures" / "feed.xml").read_bytes() if (HIER / "fixtures" / "feed.xml").exists() else None

# Rechtssatz-Dokument im Aufbau des RIS (gekürzt)
RS_XML = """<?xml version="1.0" encoding="utf-8"?><risdok xmlns="http://www.bka.gv.at"><metadaten /><nutzdaten>
<abschnitt nr="1" typ="ns"><kzinhalt typ="p"><absatz typ="kz">OGH</absatz></kzinhalt>
<ueberschrift typ="titel">Rechtssatznummer</ueberschrift><absatz typ="erltext" ct="rechtssatznummer">RS0100001</absatz>
<ueberschrift typ="titel">Rechtssatz</ueberschrift>
<absatz typ="erltext" ct="rechtssatz">Eigenbedarf setzt einen   dringenden Bedarf voraus.</absatz>
<absatz typ="erltext" ct="rechtssatz">Bloße <i>Zweckmäßigkeit</i> genügt nicht.</absatz>
<ueberschrift typ="titel">Entscheidungstexte</ueberschrift>
<absatz typ="erltext" ct="entscheidungstexte">TE OGH 2019-01-01 5 Ob 1/19a</absatz>
</abschnitt></nutzdaten></risdok>""".encode("utf-8")

# Förderzusagen im Layout von pdftotext -layout (linke Spalte Förderungswerber, rechte Spalte Absender).
# Aufbau wie in den veröffentlichten Zusagen der MA 50; Namen von Privatpersonen und Hausverwaltung erfunden.
KOPF_RECHTS = ["Amt der Wiener Landesregierung", "MA 50-HS | Muthgasse 62", "1190 Wien", "Telefon +43 1 4000 00000", "www.wien.gv.at"]


def briefkopf(links: list[str], absender: str = "MA50-HS | Muthgasse 62, 1190 Wien") -> str:
    zeilen = [absender]
    for i in range(max(len(links), len(KOPF_RECHTS))):
        l = links[i] if i < len(links) else ""
        r = KOPF_RECHTS[i] if i < len(KOPF_RECHTS) else ""
        zeilen.append((l.ljust(64) + r).rstrip() if r else l)
    return "\n".join(zeilen) + "\n\n\n"


FOERDERZUSAGE_VERTRETEN = briefkopf([
    '"Österreichisches Siedlungswerk" Gemeinnützige Woh-',
    "nungsaktiengesellschaft (FN 112897a)",
    "vertreten durch:",
    "immo 360 grad gmbh - Zweig.nl. - Technik (FN 207416z)",
    "Handelskai 130/Büro 7",
    "1020 Wien",
]) + """MA50–HS-481363-2026-10                                          Wien, 9. Juni 2026
Wien 3, Bechardgasse 15
(FO 0293/2024)

                                                            Z U SIC HE R U NG

                                                                    I.

im Folgenden kurz „Förderungswerberin bzw. Förderungswerber“ genannt, werden gemäß § 45 im
Zusammenhang mit § 37 WWFSG 1989 zur Vornahme von Sanierungsmaßnahmen in dem Objekt Wien 3, Bechardgasse 15

auf der Liegenschaft                                        EZ 797
der Katastralgemeinde                                       01006 Landstraße

ein einmaliger nichtrückzahlbarer Beitrag im Ausmaß von 123.130,00 EUR zur Vornahme folgender
Sanierungsmaßnahmen zugesichert:

§ 8 (Erhaltungsmaßnahmen, einm. nichtrückz. Beitrag)
                                                                                              Seite 3/9
\f
                                                  II.

Für die Zusicherung gelten folgende Bedingungen, Beschränkungen und Auflagen:
Für zur Gänze bestandsfreie Objekte ist ausschließlich eine Förderung im Rahmen einer Totalsanierung möglich.
"""

FOERDERZUSAGE_WEG = briefkopf([
    "WEG MUSTERG 5-7 (9110000000001)",
    "- Eigentümergemeinschaft (WEG) gemäß Grund-",
    "buchsauszug vom 2. Juni 2026",
    "vertreten durch:",
    "Muster Hausverwaltung GmbH",
    "(FN 123456a)",
    "Beispielgasse 11/13",
    "1090 Wien",
    "per E-Mail",
]) + """MA50–HS-1373304-2025-9                                          Wien, 3. Juli 2026
Wien 14, Mustergasse 5-7

                                                                    I.

im Folgenden kurz "Förderungswerberin bzw. Förderungswerber" genannt, werden gemäß § 45 ...
rungsmaßnahmen in dem Objekt in Wien 14, Mustergasse 5-7
auf der Liegenschaft                                        EZ 1733
der Katastralgemeinde                                       01207 Hütteldorf
folgende Förderungsleistungen durch das Land Wien zur Vornahme der u.a. Sanierungsmaßnahme
   • ein einmaliger nichtrückzahlbarer Beitrag gemäß § 6 Abs. 2 im Ausmaß von 698.837,00 EUR.
§ 6 (thermisch Sanierung der Gebäudehülle, einm. nichtrückz. Beitrag)

                                                  II.
"""

FOERDERZUSAGE_STADT = briefkopf([
    "Stadt Wien",
    "vertreten durch:",
    "Wiener Wohnen –",
    "Bausanierungsmanagement",
    "Rosa-Fischer-Gasse 2",
    "1030 Wien",
]) + """MA50–HS-282608-2026-4                                           Wien, 12. Mai 2026
Wien 10, Beispielhof 1

                                                                    I.

zur Vornahme von Sanierungsmaßnahmen in dem Objekt in
Wien 10, Beispielhof 1
folgende Förderungsleistungen durch das Land Wien zugesichert:
Förderungsleistungen für die Sockelsanierung:
• Für thermisch-energetische Sanierungsmaßnahmen gemäß § 12 Abs. 3 San-Dek-VO 2024 wird ein einmali-
ger nichtrückzahlbarer Beitrag in der Höhe von 57.888,00 EUR gewährt.
• Ein 20-jähriges Förderungsdarlehen gemäß § 4 Abs. 1 und § 12 Abs. 1 Z 1 San-Dek-VO 2024 in der Höhe von
1.212.204,80 EUR gegen die ausdrückliche Zustimmung im zu errichtenden Schuldschein, dass ohne wei-
teres ein Pfandrecht für die Darlehensforderung des Landes Wien samt Zinsen im Ausmaß von 1 %
jährlich und eine Nebengebührenkaution in der Höhe von 40 % der zugesicherten Darlehensbeträge,
das sind 484.881,92 EUR, einverleibt werden.

                                                  II.
"""

FOERDERZUSAGE_NEUBAU = briefkopf([
    "Beispiel",
    "Gemeinnützige Wohnungs- &",
    "Siedlungsanlagen GmbH",
    "Musterstraße 13",
    "1020 Wien",
], absender="MA50-Neubauförderung | Muthgasse 62, 1190 Wien") + """MA50-NF-NF-671832-2024                                          Wien, 09.04.2026
Bauvorhaben: 22., Oberes Musterfeld, Bpl. E1
WWFSG 1989

                                                               I.

Beispiel Gemeinnützige Wohnungs- & Siedlungsanlagen GmbH (FN 90067b), im Folgenden
kurz "Förderungswerberin" genannt, wird zur Errichtung einer Wohnhausanlage mit insgesamt 45 Wohnungen
- ein verzinstes Darlehen gemäß § 3 NeubauVO 2007 im Betrag von 3.061.369,50 EUR für 45 Woh-
nungen, dass ein Pfandrecht samt einer Nebengebührenkaution in der Höhe von 40 vH des zugesicherten Darlehensbetrages, das sind
1.224.547,80 EUR, einverleibt werde,
- ein zusätzliches Landesdarlehen gemäß § 6 NeubauVO 2007 („Superförderung“), LGBl. für Wien
Nr. 27/2007, im Betrag von 437.338,50 EUR, (150,-- EUR/m² Wohnnutzfläche),
- ein zusätzlicher Baukostenzuschuss (= nichtrückzahlbarer Zuschuss gemäß § 6a Abs. 1 NeubauVO
2007 im Betrag von 874.677,00 EUR, unter der Voraussetzung, dass ein Höchstbetragspfandrecht in Höhe von 150 vH
des zugesicherten nichtrückzahlbaren Zuschusses (das sind 1.312.015,50 EUR) intabuliert werde,
Das Förderungsdarlehen des Landes gemäß § 3 Neubauverordnung 2007 für 45 Wohnungen im Betrag von 3.061.369,50 EUR
ist halbjährlich zu tilgen.
werberin an das Land Wien eine Konventionalstrafe in der Höhe von derzeit 36.340,00 EUR zu bezahlen.

                                                          III.
"""

FOERDERZUSAGE_PRIVAT = briefkopf([
    "Max Mustermann",
    "Beispielgasse 3",
    "1080 Wien",
]) + """MA50–HS-555555-2026-3                                           Wien, 2. Februar 2026
Wien 8, Pfeilgasse 32

                                                                    I.

ein einmaliger nichtrückzahlbarer Beitrag im Ausmaß von 14.000,00 EUR zur Vornahme folgender
Sanierungsmaßnahmen zugesichert:
§ 11 (Erhöhung Wohnkomfort, einm. nichtrückz. Beitrag)

                                                                    II.
"""

FOERDERZUSAGE_MEG = briefkopf([
    "WEG Mustergasse 1 (9110000000002)",
    "- Miteigentümerinnen und Miteigentümer (MEG)",
    "gemäß Grundbuchsauszug vom 04.09.2025",
    "vertreten durch:",
    "Muster Hausverwaltung GmbH (FN 123456a)",
    "Beispielgasse 11/13",
    "1090 Wien",
]) + """MA50–HS-777777-2025-2                                           Wien, 4. Oktober 2025
Wien 16, Mustergasse 1

                                                                    I.

ein einmaliger nichtrückzahlbarer Beitrag im Ausmaß von 34.210,00 EUR zur Vornahme folgender
Sanierungsmaßnahmen zugesichert:

                                                                    II.
"""

FOERDERZUSAGE_BILD = "\f\f" + """                                                                                              Seite 3/9

                                                  II.

Für die Zusicherung gelten folgende Bedingungen, Beschränkungen und Auflagen:
1) Die Bestimmungen des WWFSG bilden einen Bestandteil dieser Zusicherung.
"""

# für den Browsertest
FOERDERZUSAGE = FOERDERZUSAGE_WEG


GEMEINDEBAUTEN_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><buildings>
<metadata><metadata_modified>2026-11-02</metadata_modified><title>Wohnen in Wien: Gemeindebauten</title></metadata>
<building><addresses>
 <address><city>Wien</city><street>Troststraße</street><streetnumber>8-16</streetnumber><type>HAUPT</type><zipcode>1100</zipcode></address>
 <address><city>Wien</city><street>Angeligasse</street><streetnumber>17a</streetnumber><type>ALIAS</type><zipcode>1100</zipcode></address>
</addresses><buildingName>Troststraße 8-16</buildingName><id>774</id><numberOfFlats>202</numberOfFlats>
<yearOfConstructions><yearOfConstruction><yearFrom>1954</yearFrom><yearTo>1955</yearTo></yearOfConstruction>
<yearOfConstruction><yearFrom>1947</yearFrom><yearTo>1951</yearTo></yearOfConstruction></yearOfConstructions></building>
<building><addresses>
 <address><city>Wien</city><street>Friedrich-Engels-Platz</street><streetnumber>17</streetnumber><type>HAUPT</type><zipcode>1200</zipcode></address>
</addresses><buildingName>Engels-Platz-Hof</buildingName><id>775</id><numberOfFlats>111</numberOfFlats>
<yearOfConstructions><yearOfConstruction><yearFrom>1949</yearFrom><yearTo>1951</yearTo></yearOfConstruction></yearOfConstructions></building>
<building><addresses>
 <address><city>Wien</city><street>Troststraße</street><streetnumber>20</streetnumber><type>HAUPT</type><zipcode>1110</zipcode></address>
</addresses><buildingName>Anderer Bezirk</buildingName><id>776</id><numberOfFlats>40</numberOfFlats>
<yearOfConstructions><yearOfConstruction><yearFrom>1960</yearFrom><yearTo>1961</yearTo></yearOfConstruction></yearOfConstructions></building>
<building><addresses/><buildingName>Ohne Adresse</buildingName><id>777</id><numberOfFlats>5</numberOfFlats></building>
</buildings>"""


class RisTest(unittest.TestCase):
    def test_dokumente_und_felder(self):
        docs = abruf.dokumente(RIS_SEITE)
        self.assertEqual(len(docs), 2)
        self.assertEqual(abruf.treffer_gesamt(RIS_SEITE), 2)
        d = abruf.lese_dokument(docs[0])
        self.assertEqual(d["id"], "JJT_20261001_OGH0002_0050OB00107_26K0000_000")
        self.assertEqual(d["gz"], ["5Ob107/26k"])
        self.assertEqual(d["normen"], ["WEG 2002 §5 Abs2", "WEG 2002 §2 Abs2"])
        self.assertEqual(d["datum"], "2026-10-01")
        self.assertEqual(d["veroeffentlicht"], "2026-10-20")
        self.assertTrue(d["url"].startswith("https://www.ris.bka.gv.at/"))
        self.assertEqual(d["rs"], ["RS0123456"])
        d2 = abruf.lese_dokument(docs[1])
        self.assertEqual(d2["gz"], ["5Ob99/26x", "5Ob100/26y"])
        self.assertEqual(d2["normen"], ["MRG §30 Abs2 Z1"])
        self.assertIsNone(d2["url"])

    def test_einzelnes_dokument_als_dict(self):
        seite = json.loads(json.dumps(RIS_SEITE))
        seite["OgdSearchResult"]["OgdDocumentResults"]["OgdDocumentReference"] = RIS_SEITE["OgdSearchResult"]["OgdDocumentResults"]["OgdDocumentReference"][0]
        seite["OgdSearchResult"]["OgdDocumentResults"]["Hits"] = "1"
        self.assertEqual(len(abruf.dokumente(seite)), 1)
        self.assertEqual(abruf.treffer_gesamt(seite), 1)

    def test_fehler_wird_erkannt(self):
        self.assertIsNotNone(abruf.fehlermeldung({"OgdSearchResult": {"Error": {"Message": "Ungültiger Parameter"}}}))
        self.assertIsNone(abruf.fehlermeldung(RIS_SEITE))

    def test_neu_md(self):
        docs = [abruf.lese_dokument(r) for r in abruf.dokumente(RIS_SEITE)]
        md = abruf.baue_neu_md(docs, [], "2026-11-17")
        self.assertIn("1 Sachentscheidungen, 1 Zurückweisungen", md)
        self.assertIn("5Ob107/26k", md)
        self.assertIsNone(abruf.baue_neu_md([], [], "2026-11-17"))


class RisAbfrageTest(unittest.TestCase):
    """Rechtssätze je Norm abfragen, Entscheidungen aus den Ketten bauen; ohne Netz."""

    def setUp(self):
        self.gesendet = []
        self.antwort = RIS_RS_SEITE
        self.gesichert = (abruf.ris_seite, abruf.PAUSE, abruf.NORMEN, abruf.MIN_ENTSCHEIDUNGEN, abruf.hole, abruf.RS_PAUSE)
        self.abgerufen = []

        def falsch_hole(url, accept, versuche=4):
            self.abgerufen.append(url)
            if url.endswith(".xml"):
                return RS_XML
            raise abruf.urllib.error.URLError("kein Netz im Test")
        abruf.hole = falsch_hole
        abruf.RS_PAUSE = 0

        self.texte = {"OgdSearchResult": {"OgdDocumentResults": {"Hits": "0"}}}

        def falsch_seite(params):
            self.gesendet.append(params)
            if params.get("Seitennummer") != "1":
                return {"OgdSearchResult": {"OgdDocumentResults": {"Hits": "3"}}}
            return self.texte if "DokumenttypSucheInEntscheidungstexten" in params else self.antwort
        abruf.ris_seite = falsch_seite
        abruf.PAUSE = 0
        abruf.NORMEN = ["MRG"]

    def tearDown(self):
        abruf.ris_seite, abruf.PAUSE, abruf.NORMEN, abruf.MIN_ENTSCHEIDUNGEN, abruf.hole, abruf.RS_PAUSE = self.gesichert

    def test_beisaetze_und_anmerkungen(self):
        eintraege, neue, st, rs_info = abruf.abruf_ris("2005-01-01", {})
        e = eintraege["JJT_20261001_OGH0002_0050OB00050_26B0000_000"]
        self.assertEqual(e["rsa"], {"RS0100001": "Auch; Beis wie T1; Beisatz: Hier: Eigenbedarf für Enkel; (siehe auch § 30). (T2)"})
        self.assertEqual(e["rss"], ["RS0200002"])   # dort erstmals formuliert
        self.assertEqual(eintraege["JJT_20190101_OGH0002_0050OB00001_19A0000_000"]["rss"], ["RS0100001"])
        info = rs_info["RS0100001"]
        self.assertEqual(info["t"], {"T1": "Der Bedarf muss dringend sein.", "T2": "Hier: Eigenbedarf für Enkel; (siehe auch § 30)."})
        self.assertEqual(info["id"], "JJR_20190101_OGH0002_0050OB00001_19A0000_001")
        self.assertTrue(info["xml"].endswith("_001.xml"))
        self.assertIsNone(rs_info["RS0200002"]["xml"])
        self.assertEqual(abruf.rechtssatz_reihenfolge(eintraege)[:2], ["RS0100001", "RS0200002"])  # neueste Entscheidung zuerst

    def test_texte_der_rechtssaetze(self):
        self.assertEqual(abruf.rechtssatz_text(RS_XML), "Eigenbedarf setzt einen dringenden Bedarf voraus. Bloße Zweckmäßigkeit genügt nicht.")
        self.assertEqual(abruf.t_texte("Auch; Beis wie T1 nur: Wenn auch die Höhe strittig ist (§ 502 ZPO). (T12)"),
                         {"T12": "Wenn auch die Höhe strittig ist (§ 502 ZPO)."})
        self.assertEqual(abruf.t_texte("Auch; Beis wie T1; Veröff: SZ 2005/12"), {})
        import tempfile
        abruf.MIN_ENTSCHEIDUNGEN = 1
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(abruf.main(["--ohne-feed", "--basis", tmp]), 0)
            cache = json.loads((pathlib.Path(tmp) / "data" / "cache" / "rechtssaetze.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(cache), ["RS0100001", "RS0200002", "RS0300003", "RS0400004"])
            self.assertTrue(cache["RS0100001"]["text"].startswith("Eigenbedarf setzt"))
            self.assertEqual(cache["RS0100001"]["t"]["T1"], "Der Bedarf muss dringend sein.")
            self.assertNotIn("text", cache["RS0200002"])   # ohne Link zum Inhalt
            # zweiter Lauf: vorhandene Texte werden nicht noch einmal geladen
            vorher = len(self.abgerufen)
            self.assertEqual(abruf.main(["--ohne-feed", "--basis", tmp]), 0)
            self.assertEqual(len(self.abgerufen), vorher)

    def test_abbruch_nach_fehlern(self):
        def kaputt(url, accept, versuche=4):
            raise abruf.urllib.error.URLError("Zeitüberschreitung")
        abruf.hole = kaputt
        cache = {}
        links = {f"RS{i:07d}": f"https://ogd.ris.bka.gv.at/x{i}.xml" for i in range(8)}
        st = abruf.lade_rechtssatztexte(cache, links, sorted(links), 100)
        self.assertEqual((st["fehler"], st["abgebrochen"], st["geladen"]), (5, True, 0))
        st = abruf.lade_rechtssatztexte({}, links, sorted(links), 100, minuten=-1)   # Zeitbudget schon aufgebraucht
        self.assertEqual((st["zeit_um"], st["fehler"], st["geladen"]), (True, 0, 0))

    def test_abfrage_rechtssaetze_ganzer_bestand(self):
        docs, gesamt = abruf.frage_norm("MRG")
        p = self.gesendet[0]
        self.assertEqual(p["DokumenttypSucheInRechtssaetzen"], "true")
        self.assertEqual((p["Applikation"], p["Gericht"], p["Norm"]), ("Justiz", "OGH", "MRG"))
        for weg in ("DokumenttypSucheInEntscheidungstexten", "SucheInRechtssaetzen", "EntscheidungsdatumVon", "ImRisSeit"):
            self.assertNotIn(weg, p)
        self.assertEqual((len(docs), gesamt), (4, 4))
        self.assertEqual(docs[0]["gz"], ["5Ob1/19a", "5Ob50/26b", "1R1/26a", "5Ob9/99z"])
        self.assertEqual(len(docs[0]["kette"]), 4)
        self.assertEqual(docs[0]["kette"][1]["id"], "JJT_20261001_OGH0002_0050OB00050_26B0000_000")

    def test_entscheidungen_aus_ketten(self):
        eintraege, neue, st, rs_info = abruf.abruf_ris("2005-01-01", {})
        self.assertEqual(sorted(eintraege), ["GZ:3ob44/24m", "GZ:5ob30/25c", "JJT_20190101_OGH0002_0050OB00001_19A0000_000", "JJT_20261001_OGH0002_0050OB00050_26B0000_000"])
        self.assertFalse(any(";" in g for e in eintraege.values() for g in e["gz"]))
        self.assertIsNone(eintraege["GZ:3ob44/24m"]["datum"])  # Datum unbekannt bei mehreren Zahlen
        self.assertEqual(eintraege["GZ:5ob30/25c"]["datum"], "2025-03-03")
        e = eintraege["JJT_20261001_OGH0002_0050OB00050_26B0000_000"]
        self.assertEqual(e["normen"], ["MRG §30 Abs2 Z1", "MRG §30 Abs2 Z8"])  # über beide Rechtssätze gesammelt
        self.assertEqual(e["rs"], ["RS0100001", "RS0200002"])
        self.assertEqual(e["art"], "Zurückweisung mangels erheblicher Rechtsfrage")
        self.assertEqual(e["schlagworte"], "Kündigung; Eigenbedarf; Enkel")  # nur vom eigenen Rechtssatz
        self.assertTrue(e["url"].endswith("JJT_20261001_OGH0002_0050OB00050_26B0000_000"))
        self.assertEqual(eintraege["JJT_20190101_OGH0002_0050OB00001_19A0000_000"]["schlagworte"], "Kündigung; Eigenbedarf")
        self.assertEqual((st["vor_ab"], st["andere_gerichte"], st["ohne_kette"]), (2, 1, 2))
        self.assertEqual(neue, [])  # Erstlauf: keine Benachrichtigung

    def test_neue_entscheidung_im_folgelauf(self):
        alt = {"JJT_20190101_OGH0002_0050OB00001_19A0000_000": {"id": "JJT_20190101_OGH0002_0050OB00001_19A0000_000", "neu_ab": "2019-01-01"},
               "GZ:5ob30/25c": {"id": "GZ:5ob30/25c", "neu_ab": "2025-03-03"},
               "GZ:3ob44/24m": {"id": "GZ:3ob44/24m", "neu_ab": "2025-06-01"}}
        eintraege, neue, st, rs_info = abruf.abruf_ris("2005-01-01", alt)
        self.assertEqual(neue, ["JJT_20261001_OGH0002_0050OB00050_26B0000_000"])
        self.assertEqual(eintraege["JJT_20190101_OGH0002_0050OB00001_19A0000_000"]["neu_ab"], "2019-01-01")

    def test_fremde_dokumente(self):
        self.antwort = RIS_SEITE  # Entscheidungstexte statt Rechtssätze
        eintraege, neue, st, rs_info = abruf.abruf_ris("2005-01-01", {})
        self.assertEqual((len(eintraege), st["fremd"]), (0, 2))

    def test_ergaenzung_aus_entscheidungstexten(self):
        self.texte = RIS_SEITE  # zwei Entscheidungstexte mit Entscheidungsart
        entsch = {
            "JJT_20261001_OGH0002_0050OB00107_26K0000_000": {"id": "JJT_20261001_OGH0002_0050OB00107_26K0000_000", "gz": ["5Ob107/26k"], "art": None, "url": None},
            "GZ:5ob100/26y": {"id": "GZ:5ob100/26y", "gz": ["5 Ob 100/26y"], "art": None, "url": None},
        }
        st = abruf.ergaenze_aus_texten(entsch, [{"ImRisSeit": "EinemMonat"}])
        p = self.gesendet[0]
        self.assertEqual((p["DokumenttypSucheInEntscheidungstexten"], p["Rechtsgebiet"], p["ImRisSeit"]), ("true", "Zivilrecht", "EinemMonat"))
        a = entsch["JJT_20261001_OGH0002_0050OB00107_26K0000_000"]
        self.assertEqual((a["art"], a["veroeffentlicht"]), ("Ordentliche Erledigung (Sachentscheidung)", "2026-10-20"))
        self.assertTrue(a["url"].endswith("JJT_20261001_OGH0002_0050OB00107_26K0000_000"))
        b = entsch["GZ:5ob100/26y"]  # über die zweite Geschäftszahl gefunden
        self.assertEqual((b["art"], b["veroeffentlicht"]), ("Zurückweisung mangels erheblicher Rechtsfrage", "2026-10-10"))
        self.assertEqual((st["texte"], st["zugeordnet"], st["art"]), (2, 2, 2))

    def test_werte_bleiben_erhalten(self):
        alt = {"JJT_20261001_OGH0002_0050OB00050_26B0000_000": {"id": "JJT_20261001_OGH0002_0050OB00050_26B0000_000", "neu_ab": "2026-10-05",
                                                             "art": "Zurückweisung aus anderen Gründen", "veroeffentlicht": "2026-10-20"},
               "GZ:5ob30/25c": {"id": "GZ:5ob30/25c", "neu_ab": "2025-03-03", "url": "https://www.ris.bka.gv.at/Dokument.wxe?Abfrage=Justiz&Dokumentnummer=JJT_X"}}
        eintraege, neue, st, rs_info = abruf.abruf_ris("2005-01-01", alt)
        e = eintraege["JJT_20261001_OGH0002_0050OB00050_26B0000_000"]
        self.assertEqual(e["art"], "Zurückweisung mangels erheblicher Rechtsfrage")  # neuere Angabe aus der Kette gilt
        self.assertEqual(e["veroeffentlicht"], "2026-10-20")
        self.assertTrue(eintraege["GZ:5ob30/25c"]["url"].endswith("JJT_X"))

    def test_nachladen_jahr_fuer_jahr(self):
        import tempfile
        abruf.MIN_ENTSCHEIDUNGEN = 1
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(abruf.main(["--ohne-feed", "--nachladen", "--ab", "2024-01-01", "--basis", tmp]), 0)
        jahre = [(p.get("EntscheidungsdatumVon"), p.get("EntscheidungsdatumBis")) for p in self.gesendet if "DokumenttypSucheInEntscheidungstexten" in p]
        self.assertEqual(jahre[:2], [("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31")])

    def test_umstellung_vom_rechtssatz_bestand(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            basis = pathlib.Path(tmp)
            (basis / "data").mkdir()
            alt = {"stand": "2026-11-17", "eintraege": [{"id": "JJR_20200101_OGH0002_0050OB00001_20A0000_001", "gz": ["5Ob1/20a"]}]}
            (basis / "data" / "ris.json").write_text(json.dumps(alt), encoding="utf-8")
            # zu wenige Treffer: nichts überschreiben
            self.assertEqual(abruf.main(["--ohne-feed", "--basis", str(basis)]), 1)
            self.assertEqual(json.loads((basis / "data" / "ris.json").read_text(encoding="utf-8")), alt)
            # plausibel: neuer Bestand nur aus Entscheidungen, keine Benachrichtigungsflut
            abruf.MIN_ENTSCHEIDUNGEN = 1
            self.assertEqual(abruf.main(["--ohne-feed", "--basis", str(basis)]), 0)
            neu = json.loads((basis / "data" / "ris.json").read_text(encoding="utf-8"))
            self.assertEqual(len(neu["eintraege"]), 4)
            self.assertFalse(any(e["id"].startswith("JJR_") for e in neu["eintraege"]))
            self.assertFalse((basis / "neu.md").exists())


class FeedTest(unittest.TestCase):
    @unittest.skipIf(FEED is None, "keine Feed-Probe")
    def test_feed(self):
        items = abruf.lese_feed(FEED)
        self.assertEqual(len(items), 1)
        e = items[0]
        self.assertEqual(e["dokumente"], ["JJT_20261001_OGH0002_0050OB00107_26K0000_000"])
        self.assertEqual(e["gz"], ["5 Ob 107/26k"])
        self.assertEqual(e["datum"], "2026-10-01")
        self.assertTrue(e["kurz"].startswith("Die in § 5"))

    def test_verhandlungsspiegel_ist_keine_entscheidung(self):
        def item(titel):
            return (f"<item><title>{titel}</title><link>https://www.ogh.gv.at/{len(titel)}/</link>"
                    f"<category>{abruf.FEED_KATEGORIE}</category><description>Text</description>"
                    "<pubDate>Mon, 23 Nov 2026 08:00:00 +0000</pubDate></item>")
        xml = ("<rss><channel>" + item("Verhandlungsspiegel 23. November bis 27. November 2026")
               + item("Mietzinsminderung bei Baulärm") + "</channel></rss>").encode("utf-8")
        self.assertEqual([e["titel"] for e in abruf.lese_feed(xml)], ["Mietzinsminderung bei Baulärm"])
        self.assertFalse(abruf.ist_entscheidung({"titel": "Verhandlungsspiegel 1. bis 5. Dezember"}))

    def test_benachrichtigung_nur_mit_bezug_zu_mrg_wgg(self):
        eintraege = {"GZ:5ob107/26k": {"gz": ["5 Ob 107/26k"], "url": "https://ogd.ris.bka.gv.at/Dokument.wxe?Abfrage=Justiz&Dokumentnummer=JJT_20261001_OGH0002_0050OB00107_26K0000_000"}}
        feed = [
            {"titel": "Bedarfsobjekte", "link": "https://www.ogh.gv.at/a/", "gz": ["5 Ob 107/26k"], "dokumente": [], "kurz": ""},            # GZ unter den RIS-Treffern
            {"titel": "A", "link": "https://www.ogh.gv.at/b/", "gz": [], "dokumente": ["JJT_20261001_OGH0002_0050OB00107_26K0000_000"], "kurz": ""},  # Dokumentnummer
            {"titel": "Befristung", "link": "https://www.ogh.gv.at/c/", "gz": ["9 Ob 1/26a"], "dokumente": [], "kurz": "Nach § 29 MRG ist …"},  # Text nennt das MRG
            {"titel": "Betrug im Onlinehandel", "link": "https://www.ogh.gv.at/d/", "gz": ["11 Os 5/26x"], "dokumente": [], "kurz": "Strafrecht"},  # ohne Bezug
        ]
        self.assertEqual([f["titel"] for f in abruf.mit_bezug(feed, eintraege)], ["Bedarfsobjekte", "A", "Befristung"])
        md = abruf.baue_neu_md([], abruf.mit_bezug(feed, eintraege), "2026-11-23")
        self.assertNotIn("Betrug", md)
        self.assertIn(abruf.SEITE_URL, md)


class SeiteTest(unittest.TestCase):
    def test_zusammenfuehren(self):
        ris = [abruf.lese_dokument(r) for r in abruf.dokumente(RIS_SEITE)]
        auswahl = [{"k": "5Ob107/26k", "gz": "5 Ob 107/26k", "d": "2026-10-01", "t": "Zur Definition der Bedarfsobjekte", "th": "W", "o": 1}]
        feed = [{"titel": "X", "link": "https://www.ogh.gv.at/x/", "dokumente": ["JJT_20261001_OGH0002_0050OB00107_26K0000_000"], "gz": []}]
        # Nur MRG und WGG: die Entscheidung zum WEG bleibt draußen, außer der Text der Auswahl nennt das MRG
        e = seite_bauen.baue_eintraege(auswahl, feed, ris)
        self.assertEqual([x["k"] for x in e], ["5Ob99/26x"])
        for r in ris:   # dieselbe Entscheidung, diesmal mit einer MRG-Norm
            if r["normen"][0].startswith("WEG"):
                r["normen"] = ["MRG §1 Abs4", "WEG 2002 §2 Abs2"]
        e = seite_bauen.baue_eintraege(auswahl, feed, ris)
        self.assertEqual(len(e), 2)
        a = next(x for x in e if x["k"] == "5Ob107/26k")
        self.assertEqual(a["t"], "Zur Definition der Bedarfsobjekte")
        self.assertEqual(a["th"], "M")   # Thema nach MRG/WGG, nicht nach der Rubrik der Auswahl („W“)
        self.assertEqual(a["n"], ["MRG §1 Abs4", "WEG 2002 §2 Abs2"])   # die Karte zeigt weiter alle Normen
        self.assertEqual(a["o"], 1)
        self.assertEqual(a["ou"], "https://www.ogh.gv.at/x/")
        b = next(x for x in e if x["k"] == "5Ob99/26x")
        self.assertEqual(b["a"], "Z")
        self.assertEqual(b["th"], "M")
        self.assertEqual(b["gzw"], ["5 Ob 100/26y"])

    def test_rechtssaetze_fuer_die_seite(self):
        b = seite_bauen.beziehung
        self.assertEqual(b("Auch; Beis wie T1; Beisatz: Hier: Eigenbedarf. (T2)", False), ("a", [2, 1], [], []))
        self.assertEqual(b("Vgl auch; nur T3", False), ("v", [], [3], []))
        self.assertEqual(b("Vgl aber; Veröff: SZ 2005/12", False), ("va", [], [], []))
        self.assertEqual(b("nur T3; Beis wie T5", False), ("n", [5], [3], []))
        self.assertEqual(b("Ähnlich; Beisatz: Hier: ohne Nummer", False), ("ae", [], [], ["Hier: ohne Nummer"]))
        self.assertEqual(b("Gegenteilig", False), ("g", [], [], []))
        self.assertEqual(b(None, True), ("s", [], [], []))
        self.assertEqual(b("", False), ("", [], [], []))
        lang = "Wort " * 100
        cache = {"RS1": {"id": "JJR_1", "text": "Grundsatz eins.", "t": {"T1": "Beisatz eins.", "T2": "Beisatz zwei.", "T9": "nicht gebraucht"}},
                 "RS2": {"id": "JJR_2", "text": lang},
                 "RS3": {"id": "JJR_3"}}   # ohne Text: kein Verweis
        eintraege = [
            {"k": "a", "_rs": {"rs": ["RS1", "RS2", "RS3"], "rsa": {"RS1": "Vgl auch; Beis wie T2"}, "rss": ["RS2"]}},
            {"k": "b", "_rs": {"rs": ["RS1"], "rsa": {"RS1": "Auch; Beis wie T1"}, "rss": []}},
            {"k": "c"},
        ]
        tab = seite_bauen.verbinde_rechtssaetze(eintraege, cache)
        self.assertEqual([x["n"] for x in tab], ["RS1", "RS2"])
        self.assertEqual(tab[0]["b"], {"2": "Beisatz zwei.", "1": "Beisatz eins."})   # nur gebrauchte Beisätze
        self.assertNotIn("b", tab[1])
        self.assertTrue(tab[1]["t"].endswith(" …") and len(tab[1]["t"]) <= seite_bauen.RS_TEXT_MAX)
        self.assertEqual(eintraege[0]["r"], [[1, "s"], [0, "v", [2]]])   # erstmals hier zuerst
        self.assertEqual(eintraege[1]["r"], [[0, "a", [1]]])
        self.assertFalse(any("_rs" in e for e in eintraege))
        self.assertNotIn("r", eintraege[2])

    def test_thema_und_gz(self):
        self.assertEqual(seite_bauen.thema_aus_normen(["MRG §16 Abs1"]), "M")
        self.assertEqual(seite_bauen.thema_aus_normen(["MRG §20", "WGG §14 Abs1"]), "G")
        self.assertEqual(seite_bauen.thema_aus_normen(["WGG 1979 §22"]), "G")
        zu = seite_bauen.zu_mrg_wgg
        self.assertTrue(zu({"n": ["ABGB §1096", "MRG §1 Abs4"]}))
        self.assertFalse(zu({"n": ["WEG 2002 §16", "ABGB §1096"]}))
        self.assertTrue(zu({"t": "Befristung nach dem Mietrechtsgesetz"}))
        self.assertTrue(zu({"t": "Kostendeckende Miete", "s": "§ 14 WGG regelt das Entgelt"}))
        self.assertFalse(zu({"t": "Wohnungseigentum: Benützungsregelung"}))
        self.assertEqual(seite_bauen.gz_anzeige("5Ob107/26k"), "5 Ob 107/26k")
        self.assertEqual(seite_bauen.gz_anzeige("10 ObS 47/13d"), "10 ObS 47/13d")

    def test_script_sicher(self):
        html = seite_bauen.baue_seite("<script>/*DATEN*/</script>", {"x": "</script><b>"})
        self.assertNotIn("</script><b>", html)

    def test_fassung_fuer_github_pages(self):
        web = seite_bauen.fuer_web("<head><title>x</title></head><body></head></body>")
        self.assertEqual(web.count('rel="manifest"'), 1)
        self.assertTrue(web.startswith('<head><title>x</title><link rel="manifest"'))
        for name in seite_bauen.WEB_DATEIEN:
            self.assertTrue((HIER.parent / "vorlage" / name).is_file(), name)
        manifest = json.loads((HIER.parent / "vorlage" / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual({i["src"] for i in manifest["icons"]}, {"icon-192.png", "icon-512.png"})


class WienTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.traeger = wien.lade_traeger(HIER.parent / "data" / "wien_traeger.json")

    def ds(self, titel, dist=""):
        return {"id": "x", "titel": titel, "datum": "2026-06-10", "link": "https://www.data.gv.at/datasets/x", "share": None, "dist": dist}

    def test_unternehmen_mit_vertreter(self):
        e = wien.lies_foerderzusage(FOERDERZUSAGE_VERTRETEN, self.ds("Förderzusage, thermisch-energetische Sanierung (481363-2026)", "ERH (481363-2026)"), self.traeger)
        self.assertEqual(e["gz"], "481363-2026")
        self.assertEqual(e["datum"], "2026-06-09")
        self.assertEqual(e["empfaenger_typ"], "unternehmen")
        self.assertEqual(e["empfaenger"], '"Österreichisches Siedlungswerk" Gemeinnützige Wohnungsaktiengesellschaft')
        self.assertEqual(e["empfaenger_fn"], "112897a")
        self.assertEqual(e["traeger"], "oesw")
        self.assertEqual(e["vertreter"], "immo 360 grad gmbh - Zweig.nl. - Technik")
        self.assertEqual(e["vertreter_fn"], "207416z")
        self.assertEqual((e["bezirk"], e["adresse"], e["ez"], e["kg"]), (3, "Bechardgasse 15", "797", "Landstraße"))
        self.assertEqual(e["betraege"], [{"art": "Beitrag", "eur": 123130.0}])
        self.assertEqual(e["massnahmen"], ["Erhaltungsarbeiten"])  # Kürzel ERH, nicht der Titel
        self.assertEqual(e["pruefen"], [])

    def test_eigentuemergemeinschaft(self):
        e = wien.lies_foerderzusage(FOERDERZUSAGE_WEG, self.ds("Förderzusage (1373304-2025)", "TES (1373304-2025)"), self.traeger)
        self.assertEqual(e["empfaenger_typ"], "weg")
        self.assertEqual(e["empfaenger"], "WEG MUSTERG 5-7")
        self.assertEqual(e["vertreter"], "Muster Hausverwaltung GmbH")
        self.assertEqual(e["vertreter_fn"], "123456a")
        self.assertEqual((e["bezirk"], e["adresse"]), (14, "Mustergasse 5-7"))
        self.assertEqual(e["nicht_rueckzahlbar"], 698837.0)
        self.assertEqual(e["massnahmen"], ["Thermische Sanierung"])

    def test_stadt_wien_kaution_nicht_gezaehlt(self):
        e = wien.lies_foerderzusage(FOERDERZUSAGE_STADT, self.ds("Förderzusage für Sockelsanierung (282608-2026)", "SOS (282608-2026)"), self.traeger)
        self.assertEqual((e["empfaenger_typ"], e["empfaenger"], e["vertreter"]), ("stadt", "Stadt Wien", "Wiener Wohnen"))
        self.assertEqual(e["traeger"], "wiener-wohnen")
        self.assertEqual(e["betraege"], [{"art": "Beitrag", "eur": 57888.0}, {"art": "Darlehen", "eur": 1212204.8}])
        self.assertEqual(e["massnahmen"], ["Sockelsanierung"])

    def test_neubau(self):
        e = wien.lies_foerderzusage(FOERDERZUSAGE_NEUBAU, self.ds("Förderzusage für die Errichtung einer Wohnhausanlage (671832-2024)", "22, Oberes Musterfeld, BPl. E1 (671832-2024)"), self.traeger)
        self.assertEqual(e["gz"], "671832-2024")
        self.assertEqual(e["datum"], "2026-04-09")
        self.assertEqual(e["empfaenger"], "Beispiel Gemeinnützige Wohnungs- & Siedlungsanlagen GmbH")
        self.assertEqual(e["empfaenger_fn"], "90067b")  # erst in Abschnitt I genannt
        self.assertEqual((e["bezirk"], e["adresse"]), (22, "Oberes Musterfeld, Bpl. E1"))
        self.assertEqual(e["wohnungen"], 45)
        self.assertEqual(e["massnahmen"], ["Neubau"])
        # Kaution, Pfandrecht, Strafe und die Wiederholung im Tilgungsabsatz zählen nicht
        self.assertEqual(e["betraege"], [{"art": "Darlehen", "eur": 3061369.5}, {"art": "Darlehen", "eur": 437338.5}, {"art": "Zuschuss", "eur": 874677.0}])

    def test_privatperson_ohne_namen(self):
        e = wien.lies_foerderzusage(FOERDERZUSAGE_PRIVAT, self.ds("Förderzusage (555555-2026)"), self.traeger)
        self.assertEqual(e["empfaenger_typ"], "privat")
        self.assertIsNone(e["empfaenger"])
        self.assertIsNone(e["adresse"])
        self.assertIsNone(e["ez"])
        self.assertEqual(e["bezirk"], 8)
        self.assertEqual(e["massnahmen"], ["Wohnkomfort"])
        self.assertNotIn("Mustermann", json.dumps(e, ensure_ascii=False))
        self.assertNotIn("Pfeilgasse", json.dumps(e, ensure_ascii=False))

    def test_miteigentuemer_ohne_adresse(self):
        e = wien.lies_foerderzusage(FOERDERZUSAGE_MEG, self.ds("Förderzusage (777777-2025)"), self.traeger)
        self.assertEqual(e["empfaenger_typ"], "meg")
        self.assertIsNone(e["empfaenger"])
        self.assertIsNone(e["adresse"])
        self.assertEqual(e["bezirk"], 16)
        self.assertEqual(e["vertreter"], "Muster Hausverwaltung GmbH")

    def test_erste_seiten_nur_bild(self):
        e = wien.lies_foerderzusage(FOERDERZUSAGE_BILD, self.ds("Förderzusage für Sockelsanierung (1234040-2025)", "SOS (1234040-2025)"), self.traeger)
        self.assertEqual(e["empfaenger_typ"], "unbekannt")
        self.assertEqual(e["gz"], "1234040-2025")
        self.assertEqual(e["datum"], "2026-06-10")  # Veröffentlichungsdatum
        self.assertEqual(e["massnahmen"], ["Sockelsanierung"])
        self.assertEqual(e["pruefen"], ["Erste Seiten nur als Bild", "Betrag nicht erkannt"])

    def test_namen_und_personen(self):
        self.assertEqual(wien.verbinde(["Komm.Rat Immobilien-", "und Vermögenstreuhand GmbH"]), "Komm.Rat Immobilien- und Vermögenstreuhand GmbH")
        self.assertEqual(wien.verbinde(["Gebäudeverwaltung-Reali-", "tätenkanzlei OG"]), "Gebäudeverwaltung-Realitätenkanzlei OG")
        self.assertEqual(wien.partei(["Maria Kirchner", "Beispielgasse 1", "1010 Wien"])["art"], "privat")
        self.assertEqual(wien.partei(["Max Muster e.U. (FN 999999a)"])["art"], "privat")
        self.assertEqual(wien.partei(["Wiener Wohnen –", "Bausanierungsmanagement", "Rosa-Fischer-Gasse 2", "1030 Wien"])["name"], "Wiener Wohnen")

    def test_traeger_zuordnung(self):
        faelle = {
            "Gemeinnützige Wohnungs- und Siedlungsgenossenschaft SIEDLUNGSUNION reg. Gen.m.b.H.": "siedlungsunion",
            "GESIBA Gemeinnützige Siedlungs- und Bauaktiengesellschaft": "gesiba",
            "WIGEBA Wiener Gemeindewohnungs Baugesellschaft m.b.H.": "wigeba",
            "\"Heimbau\" Gemeinnützige Bau-, Wohnungs- u. Siedlungsgenossenschaft": "heimbau",
            "MIGRA Gemeinnützige Wohnungsges.m.b.H.": "migra",
            "Gemeinnützige Wohn- und Siedlungsgesellschaft Schönere Zukunft Ges.m.b.H.": "schoenere-zukunft",
            "Gemeinnützige Bau-, Wohn- und Siedlungsgenossenschaft \"Neues Leben\" reg. Gen.m.b.H.": "neues-leben",
            "GEWOG Gemeinnützige Wohnungsbau-Gesellschaft m.b.H.": "gewog",
            "BUWOG Group GmbH": "buwog",
            "Wohnbauvereinigung für Privatangestellte Gemeinnützige Gesellschaft mit beschränkter Haftung": "wbv-gpa",
            "Wohnbauvereinigung GFW Gemeinnützige GmbH": "wbv-gfw",
            "\"Österreichisches Siedlungswerk\" Gemeinnützige Wohnungsaktiengesellschaft": "oesw",
            "Österreichisches Volkswohnungswerk Gemeinnützige Ges.m.b.H.": "oevw",
            "Gemeinnützige Bau-Wohn- und Siedlungsgenossenschaft \"Heim\" reg. Gen.m.b.H": "heim",
        }
        faelle.update({
            "Gemeinnützige Bau- und Siedlungsgenossenschaft FRIEDEN reg.Gen.mbH.": "frieden",
            "Gemeinnützige Ein- und Mehrfamilienhäuser Baugenossenschaft reg. Gen.m.b.H.": "ebg",
            "Stadt Wien": "wiener-wohnen",
        })
        for name, key in faelle.items():
            self.assertEqual(wien.ordne_zu(name, self.traeger), key, name)
        # Firmenbuchnummer geht vor dem Namen
        self.assertEqual(wien.ordne_zu({"name": "irgendein Name", "fn": "52149s"}, self.traeger), "gesiba")
        # keine Fehltreffer bei ähnlichen Wörtern
        self.assertIsNone(wien.ordne_zu("Wanderungsströme nach Geburtsland (Migration)", self.traeger))
        self.assertIsNone(wien.ordne_zu("Aufbau einer Datenbank", self.traeger))
        self.assertIsNone(wien.ordne_zu("Heimbauer Straße 3", self.traeger))

    def test_pruefberichte_ohne_liste(self):
        leer = {"traeger": None, "vertreter": None, "vertreter_fn": None, "vertreter_traeger": None}
        fz = [dict(leer, id="a", empfaenger="Beispiel Gemeinnützige Wohnungs- & Siedlungsanlagen GmbH", empfaenger_fn="90067b",
                   nicht_rueckzahlbar=1000.0, darlehen=0.0)]
        pb = [{"id": "p1", "titel": "BEISPIEL Gemeinnützige Wohnungs- und Siedlungsanlagen Gesellschaft mit beschränkter Haftung - Auszug gemäß § 28 Abs 8. WGG (1-2026)",
               "datum": "2026-07-17", "gj": 2025, "traeger": None},
              {"id": "p2", "titel": "Gemeinnützige Bau- und Wohnungsgenossenschaft „Muster“ registrierte Genossenschaft m.b.H. - Auszug gemäß § 28 Abs 8. WGG (2-2026)",
               "datum": "2026-06-01", "gj": 2025, "traeger": None},
              {"id": "p3", "titel": "MIGRA Gemeinnützige Wohnungsges.m.b.H. - Auszug gemäß § 28 Abs 8. WGG (3-2026)",
               "datum": "2026-03-05", "gj": 2024, "traeger": "migra"}]
        bt = [{"id": "b1", "titel": "Gemeinnützige Bau- und Wohnungsgenossenschaft \"Muster\" reg. Gen.m.b.H. Bescheinigung § 7 Abs 6 Z3 lit c BTVG (4-2026)",
               "datum": "2026-04-09", "traeger": None}]
        ueb, weitere, nur_dok = wien.baue_ueberblick(self.traeger, fz, pb, bt, [])
        nach = {u["key"]: u for u in ueb}
        self.assertEqual((weitere, nur_dok), (1, 1))
        # gleicher Name wie in der Förderzusage, nur anders geschrieben
        self.assertEqual(len(nach["fn-90067b"]["pruefberichte"]), 1)
        self.assertEqual(nach["fn-90067b"]["typ"], "gemeinnützig")
        # unbekannte Bauvereinigung: eigener Eintrag mit Prüfbericht und Bescheinigung
        muster = [u for u in ueb if u["key"].startswith("wgg-")]
        self.assertEqual(len(muster), 1)
        self.assertEqual((muster[0]["typ"], len(muster[0]["pruefberichte"]), len(muster[0]["btvg"])), ("gemeinnützig", 1, 1))
        self.assertTrue(muster[0]["key"].isascii())
        self.assertEqual(len(nach["migra"]["pruefberichte"]), 1)
        self.assertEqual(sum(len(u["pruefberichte"]) for u in ueb), 3)
        self.assertEqual(wien.firmenname(bt[0]["titel"]), "Gemeinnützige Bau- und Wohnungsgenossenschaft \"Muster\" reg. Gen.m.b.H.")

    def test_gemeindebauten(self):
        gb = wien.lies_gemeindebauten(GEMEINDEBAUTEN_XML.encode("utf-8"))
        self.assertEqual((gb["stand"], gb["anzahl"], gb["wohnungen"]), ("2026-11-02", 4, 202 + 111 + 40 + 5))
        self.assertEqual(len(gb["bauten"]), 3)   # zum Zuordnen nur Einträge mit Adresse
        self.assertEqual(gb["bauten"][0]["bauzeit"], [[1947, 1951], [1954, 1955]])
        idx = wien.gemeindebau_index(gb["bauten"])
        finde = lambda bez, adr: [x["name"] for x in wien.finde_gemeindebau(idx, gb["bauten"], bez, adr)]
        self.assertEqual(finde(10, "Troststraße 8-16"), ["Troststraße 8-16"])            # Hauptadresse
        self.assertEqual(finde(10, "Angeligasse 17a"), ["Troststraße 8-16"])             # Nebenadresse
        self.assertEqual(finde(10, "Trost-Straße 8 - 16"), ["Troststraße 8-16"])         # andere Schreibweise
        self.assertEqual(finde(20, "Friedrich-Engels-Platz 17-18"), ["Engels-Platz-Hof"])  # Bereich überlappt
        self.assertEqual(finde(20, "Friedrich-Engels-Platz"), ["Engels-Platz-Hof"])      # ohne Nummer, nur ein Bau
        self.assertEqual(finde(11, "Troststraße 8-16"), [])                              # anderer Bezirk
        self.assertEqual(finde(10, "Am Wienerfeld West"), [])
        self.assertEqual(finde(None, "Troststraße 8-16"), [])
        with self.assertRaises(ValueError):
            wien.lies_gemeindebauten(b"<buildings><metadata/></buildings>")

    def test_wiener_wohnen_dokumente(self):
        self.assertTrue(wien.ist_ww_dokument("Hausordnung Stadt Wien - Wiener Wohnen (1169385-2025)"))
        self.assertTrue(wien.ist_ww_dokument("Leitfaden Jahresabrechnung, Stadt Wien - Wiener Wohnen (1170208-2025)"))
        self.assertTrue(wien.ist_ww_dokument("Geschäftsbericht 2024 (1167823-2025)", "Geschäftsbericht 2024 der Unternehmung Stadt Wien - Wiener Wohnen"))
        self.assertTrue(wien.ist_ww_dokument("Zahlen, Daten, Fakten (1169719-2025)", "Zahlen, Daten, Fakten über den Wiener Gemeindebau"))
        self.assertTrue(wien.ist_ww_dokument("Vergaberichtlinien Wohnungsvergabe NEU (971447-2026)"))
        self.assertFalse(wien.ist_ww_dokument("Geschäftsbericht 2024 (1-2025)", "Geschäftsbericht eines anderen Unternehmens"))
        self.assertFalse(wien.ist_ww_dokument("Stadt Wien - Wiener Wohnen 14., Hütteldorfer Straße 268-274, Tischlerarbeiten"))
        self.assertFalse(wien.ist_ww_dokument("Hausbesorger-Bekleidung für Wiener Wohnen"))


class VpiTest(unittest.TestCase):
    KOPF_NEU = "C-VPIZR-0;C-VPICOICOP18_5-0;F-VPIMZBM;F-VPIMZVM;F-VPIMZVJM;F-VPIPZVM;F-VPIPZVJM"

    def test_gesamtindex_aus_hauptdatei(self):
        csv = "\n".join([self.KOPF_NEU,
                         "VPIZR-202601;VPICOICOP18-0;100,30000;99,90000;;0,40000;",
                         "VPIZR-202601;VPICOICOP18-01;104,10000;103,00000;;1,10000;",
                         "VPIZR-202602;VPICOICOP18-0;100,90000;100,30000;;0,60000;",
                         "VPIZR-202602;VPICOICOP18-011;99,00000;;;;"]).encode("utf-8")
        self.assertEqual(vpi.lies_reihe(csv), {"2026-01": 100.3, "2026-02": 100.9})
        alt = "C-VPIZR-0;C-VPI1-0;F-VPIMZBM\nVPIZR-195903;VPI-0;99,3\nVPIZR-195904;VPI-0;100,0\n".encode("utf-8")
        self.assertEqual(vpi.lies_reihe(alt), {"1959-03": 99.3, "1959-04": 100.0})
        with self.assertRaises(ValueError):
            vpi.lies_reihe(b"irgendwas;anderes\n1;2")

    def test_vorlaeufig_und_luecken(self):
        zr = "code;name;;en_name\nVPIZR-202609;Sep.26;;September 2026\nVPIZR-202610;Okt.26 (vorl.);;October 2026 (prel.)\n"
        self.assertEqual(vpi.lies_vorlaeufig(zr.encode("utf-8")), {"2026-10"})
        r = vpi.als_reihe("x", "VPI X", {"2025-11": 1.0, "2026-01": 3.0})
        self.assertEqual((r["von"], r["bis"], r["werte"]), ("2025-11", "2026-01", [1.0, None, 3.0]))

    def test_ablauf_mit_dateien(self):
        heute = dt.date.today()
        monate = []
        j, m = heute.year, heute.month
        for _ in range(8):
            monate.insert(0, f"{j:04d}{m:02d}")
            j, m = (j - 1, 12) if m == 1 else (j, m - 1)
        with tempfile.TemporaryDirectory() as tmp:
            quelle = pathlib.Path(tmp) / "quelle"
            quelle.mkdir()
            zeilen = [self.KOPF_NEU] + [f"VPIZR-{mo};VPICOICOP18-0;{100 + i},{i}0000;;;;" for i, mo in enumerate(monate)]
            (quelle / "A.csv").write_text("\n".join(zeilen), encoding="utf-8")
            (quelle / "A_C-VPIZR-0.csv").write_text("code;name\n" + "\n".join(f"VPIZR-{mo};x{' (vorl.)' if mo == monate[-1] else ''}" for mo in monate), encoding="utf-8")
            alt_basen, alt_sleep = vpi.BASEN, vpi.time.sleep
            vpi.BASEN = [("a", "VPI A", "A"), ("b", "VPI B", "B")]   # B fehlt -> Fehler, A wird trotzdem gespeichert
            vpi.time.sleep = lambda s: None
            try:
                rc = vpi.main(["--basis", tmp, "--quelle", quelle.as_uri() + "/"])
            finally:
                vpi.BASEN, vpi.time.sleep = alt_basen, alt_sleep
            self.assertEqual(rc, 1)
            daten = json.loads((pathlib.Path(tmp) / "data" / "vpi.json").read_text(encoding="utf-8"))
            self.assertEqual([r["key"] for r in daten["reihen"]], ["a"])
            self.assertEqual(daten["reihen"][0]["werte"][0], 100.0)
            self.assertEqual(daten["vorlaeufig"], [f"{monate[-1][:4]}-{monate[-1][4:]}"])

    def test_freiwillige_reihe_laesst_lauf_nicht_scheitern(self):
        heute = dt.date.today()
        monate = []
        j, m = heute.year, heute.month
        for _ in range(8):
            monate.insert(0, f"{j:04d}{m:02d}")
            j, m = (j - 1, 12) if m == 1 else (j, m - 1)
        with tempfile.TemporaryDirectory() as tmp:
            quelle = pathlib.Path(tmp) / "quelle"
            quelle.mkdir()
            # HVPI-Datei im Format von Statistik Austria (Gesamtindex „HVPI-0“)
            kopf = "C-VPIZR-0;C-HVPICOICOP18_5-0;F-VPIMZBM;F-VPIGEWBM"
            zeilen = [kopf] + [f"VPIZR-{mo};HVPI-0;{100 + i},50000;100,00000" for i, mo in enumerate(monate)] + [f"VPIZR-{monate[0]};HVPI-01;90,0;12,1"]
            (quelle / "H.csv").write_text("\n".join(zeilen), encoding="utf-8")
            (quelle / "H_C-VPIZR-0.csv").write_text("code;name\n" + "\n".join(f"VPIZR-{mo};x" for mo in monate), encoding="utf-8")
            alt_basen, alt_sleep = vpi.BASEN, vpi.time.sleep
            vpi.BASEN = [("h", "HVPI H", "H", True), ("x", "HVPI X", "X", True)]   # X fehlt, ist aber freiwillig
            vpi.time.sleep = lambda s: None
            try:
                rc = vpi.main(["--basis", tmp, "--quelle", quelle.as_uri() + "/"])
            finally:
                vpi.BASEN, vpi.time.sleep = alt_basen, alt_sleep
            self.assertEqual(rc, 0)
            daten = json.loads((pathlib.Path(tmp) / "data" / "vpi.json").read_text(encoding="utf-8"))
            self.assertEqual([r["key"] for r in daten["reihen"]], ["h"])
            self.assertEqual(daten["reihen"][0]["werte"][:2], [100.5, 101.5])

    def test_hvpi_in_basen(self):
        self.assertIn("hvpi2025", [b[0] for b in vpi.BASEN])


class TestRichtwerte(unittest.TestCase):
    def test_kompakt(self):
        d = {"richtwerte": {"laender": ["A", "B"], "staende": [
                {"ab": "2023-04-01", "werte": [1.0, 2.0], "quelle": "q1"},
                {"ab": "2026-04-01", "werte": [1.1, 2.1], "link": "https://x"},
                {"ab": "2020-01-01", "werte": [1.0]}]},   # unvollständig -> fällt weg
             "kategorien": {"spalten": ["A"], "staende": []}}
        k = seite_bauen.kompakt_richtwerte(d)
        self.assertEqual([s["ab"] for s in k["richtwerte"]["s"]], ["2026-04-01", "2023-04-01"])
        self.assertNotIn("kategorien", k)
        self.assertIsNone(seite_bauen.kompakt_richtwerte(None))

    def test_datei_im_repo_vollstaendig(self):
        d = json.loads((HIER.parent / "data" / "richtwerte.json").read_text(encoding="utf-8"))
        k = seite_bauen.kompakt_richtwerte(d)
        self.assertEqual(len(k["richtwerte"]["s"]), len(d["richtwerte"]["staende"]))
        self.assertEqual(len(k["kategorien"]["s"]), len(d["kategorien"]["staende"]))
        self.assertEqual(k["richtwerte"]["k"][-1], "Wien")


if __name__ == "__main__":
    unittest.main()
