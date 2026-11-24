# Wohnrecht – OGH zu MRG und WGG, Wohnbauträger Wien, Indexrechner

Seite öffnen: https://johnsweat.github.io/wohnrecht/

Am Handy: Seite über den Link öffnen und im Browsermenü „Zum Startbildschirm hinzufügen“ wählen.

Eine einzelne HTML-Seite zum Nachschlagen und Aktuell-Bleiben, jede Woche automatisch aktualisiert:

- **OGH-Entscheidungen zu MRG und WGG** (Mietrechtsgesetz, Wohnungsgemeinnützigkeitsgesetz) – mit Rechtssätzen aus dem RIS, Volltextsuche darin, Filtern (Thema, Jahr, Paragraf), Neu-Bereich, Hinweisen auf geänderte Rechtslage, Merken und Notizen. Entscheidungen, die nur andere Gesetze betreffen (etwa WEG oder ABGB allein), sind seit November 2026 nicht mehr enthalten.
- **Wohnbauträger Wien** – Förderzusagen der MA 50 (Sanierung und Neubau) mit Förderungswerber, Vertreter (meist die Hausverwaltung), Objekt, Betrag und Maßnahme; dazu Prüfberichtsauszüge (§ 28 Abs 8 WGG) und BTVG-Bescheinigungen. Gruppiert nach Trägern wie GESIBA, Heimbau, MIGRA, Neues Leben, Sozialbau, Stadt Wien – Wiener Wohnen; weitere Unternehmen (z. B. Hausverwaltungen) werden über die Firmenbuchnummer automatisch zusammengeführt, Bauvereinigungen mit Prüfbericht oder BTVG-Bescheinigung über den Firmennamen. Förderzusagen an die Stadt Wien sind über die Adresse den Gemeindebauten von Wiener Wohnen zugeordnet (Name, Wohnungen, Bauzeit); die Karte „Stadt Wien – Wiener Wohnen“ zeigt dazu Infoblätter und Berichte von Wiener Wohnen. Darunter: Hintergrunddokumente der Stadt Wien (Rechtsgutachten Wärme-/Kältekosten, Berichtsstandard Wohnbauförderung, Stadtrechnungshof).
- **Indexrechner (VPI)** – Veränderung zwischen zwei Monaten im Verbraucherpreisindex von Statistik Austria (alle Basen von VPI 2025 bis VPI I/II 1958), mit Faktor, Betrag und Schwelle; vorläufige Werte sind gekennzeichnet. Nur Rechnung, keine rechtliche Beurteilung (z. B. MieWeG).

## Benutzen

Am einfachsten über den Link oben. Für unterwegs ohne Netz: `dist/ogh-wohnrecht.html` herunterladen und im Browser öffnen; die Datei enthält alle Daten (Stand der letzten Aktualisierung). Notizen bleiben im jeweiligen Browser; über „Notizen sichern / laden“ lassen sie sich exportieren und auf einem anderen Gerät importieren.

Der Filter steht in jeder Rubrik oben an seinem Platz. Weiter unten in den Einträgen dockt er als Leiste am oberen Rand an und fährt beim Antippen oder Herunterziehen heraus, wie die Benachrichtigungsleiste am Handy. Zwei Schalter sorgen für eine aufgeräumte Liste: „Einträge nur mit Paragrafen ausblenden“ (Entscheidungen, zu denen das RIS keinen Kurztext führt, sondern nur die Paragrafen) und „Förderzusagen mit „prüfen“ ausblenden“ (unsicher ausgelesene Zusagen). Beide Einstellungen merkt sich der Browser.

## Aktualisierung

GitHub Actions führt jeden Montag den Ablauf **Aktualisieren** aus (`.github/workflows/aktualisieren.yml`). Weil GitHub geplante Läufe nicht garantiert (sie können sich verspäten oder ausfallen), stößt der Zeitplan täglich an; gerechnet wird aber nur montags oder wenn die letzte RIS-Abfrage 7 oder mehr Tage zurückliegt. Ein ausgefallener Montag wird so am nächsten Tag nachgeholt. Schritte des Ablaufs:

1. `scripts/abruf.py` – OGH-Entscheidungen aus dem RIS (Open-Government-Data-Schnittstelle) und neue Hervorhebungen aus dem OGH-Feed. Weil das RIS die Normen nur bei Rechtssätzen führt, fragt das Skript alle Rechtssätze zu MRG und WGG ab und baut aus deren Entscheidungsketten die Liste der Entscheidungen (mit Link zum Entscheidungstext). Die Entscheidungsart kommt aus den Entscheidungstexten. Zu jeder Entscheidung zeigt die Seite die Rechtssätze (vom OGH formulierte Rechtsgrundsätze) mit der Angabe, wie die Entscheidung dazu steht (erstmals hier, bestätigt, vgl. aber …), und den Beisätzen. Die Texte lädt der Ablauf einmal in `data/cache/rechtssaetze.json` (beim ersten Mal einige Tausend Abrufe, mit Zeitbudget je Lauf), danach nur neue.
2. `scripts/wien.py` – Dokumente der Stadt Wien über die Suchschnittstelle von data.gv.at; Förderzusagen werden als PDF geladen und ausgewertet. Dazu der Datensatz „Gemeindebauten“ von Wiener Wohnen (verkleinert in `data/cache/gemeindebauten.json`; fällt der Abruf aus, gilt der letzte Stand).
3. `scripts/vpi.py` – Verbraucherpreisindex von Statistik Austria (Gesamtindex je Monat und Basis) nach `data/vpi.json`
4. `scripts/seite_bauen.py` – baut die Seite: `docs/index.html` für GitHub Pages (mit Manifest und Symbol für den Startbildschirm) und `dist/ogh-wohnrecht.html` als Einzeldatei

Danach schreibt der Ablauf die Änderungen ins Repository; GitHub Pages (Einstellung: Zweig `main`, Ordner `/docs`) veröffentlicht die neue Fassung innerhalb weniger Minuten.

Gibt es neue Entscheidungen, legt der Ablauf ein Issue an; dadurch kommt eine Benachrichtigung (je nach GitHub-Einstellung per Mail oder App).

Manuell starten: **Actions → Aktualisieren → Run workflow**. Schalter: „voll“ baut den RIS-Bestand ohne Benachrichtigung neu auf, „nachladen“ gleicht einmalig alle Entscheidungstexte ab 2005 ab (Entscheidungsart, etwa 15 Minuten), „diagnose“ schreibt nur Feldstatistiken ins Protokoll.

Kein KI-Aufruf, keine Zugangsdaten nötig; nur Python-Standardbibliothek und `pdftotext`.

## Daten und Lizenzen

| Quelle | Inhalt | Lizenz/Status |
|---|---|---|
| RIS – Rechtsinformationssystem des Bundes | OGH-Entscheidungen (Metadaten, Links) | CC BY 4.0 |
| ogh.gv.at | vom OGH vorgestellte Entscheidungen (Titel, Kurztext) | öffentliche Veröffentlichungen des OGH |
| data.gv.at / Stadt Wien | Förderzusagen, Prüfberichtsauszüge, BTVG-Bescheinigungen, Dokumente von Wiener Wohnen | Veröffentlichungen nach dem Informationsfreiheitsgesetz |
| Stadt Wien – Wiener Wohnen | Datensatz „Gemeindebauten“ (Name, Wohnungen, Bauzeit, Adressen) | CC BY 3.0 AT |
| Statistik Austria | Verbraucherpreisindex (Gesamtindex, alle Basen) | CC BY 4.0 |

Automatisch verdichtete Texte und ausgelesene Werte sind keine amtlichen Angaben; maßgeblich ist das Originaldokument. Keine Rechtsberatung.

**Datenschutz:** Ist eine Förderzusage an Privatpersonen oder Miteigentümer gerichtet, speichert die Seite keinen Namen und kürzt die Adresse auf den Bezirk; dasselbe gilt für Einzelpersonen als Vertreter. Die aus den PDFs ausgelesenen Texte liegen nicht im Repository, nur im Zwischenspeicher von GitHub Actions (`data/cache/wien_texte/`, in `.gitignore`); fehlt er, lädt der Ablauf die PDFs neu.

**Grenzen:** Bei einem Teil der Förderzusagen sind die ersten Seiten nur als Bild veröffentlicht. Dann stehen Förderungswerber, Objekt und Betrag nur im PDF; die Seite markiert diese Zusagen mit „prüfen“.

## Ordner

- `data/` – Daten (Grundbestand `ogh_auswahl.json`, Trägerliste `wien_traeger.json`, von Hand gepflegte Hintergrunddokumente `dokumente.json`, Abrufergebnisse)
- `docs/` – fertige Seite für GitHub Pages (wird bei jedem Lauf neu gebaut)
- `dist/` – dieselbe Seite als Einzeldatei zum Herunterladen
- `scripts/` – Abruf und Seitenbau
- `vorlage/` – HTML-Vorlage, Manifest und Symbole
- `tests/` – `python -m unittest discover -s tests -p "test_*.py"`; Browsertests mit Playwright

## Trägerliste anpassen

`data/wien_traeger.json`: je Träger ein Name, die Firmenbuchnummer (`fn`, wenn bekannt), ein Suchmuster (regulärer Ausdruck) und die Art (gemeinnützig, gewerblich, kommunal). Die Zuordnung läuft zuerst über die Firmenbuchnummer, dann über das Suchmuster. Nicht aufgeführte Unternehmen erscheinen automatisch, sobald sie in einer Förderzusage stehen. Änderungen wirken beim nächsten Lauf; sofort: `python scripts/wien.py --nur-auswerten && python scripts/seite_bauen.py`.

## Hintergrunddokumente anpassen

`data/dokumente.json`: je Dokument Titel, Datum, Link zum Datensatz auf data.gv.at, Link zur Datei und der Ort auf der Seite (`vpi` beim Indexrechner, `wien` in der Rubrik Wien). Die Links werden nicht automatisch geprüft.
