# Version 10.7.4

Stand: 13. August 2026  
Ausgangsbasis: produktive Version 10.7.3, Commit `e021ec9`

## Ergebnis

Version 10.7.4 setzt den Research-Handoff vom 12. August um. Der P0-Fehler, durch den
rollende provisorische METAR-Werte bereits finale Tagesmaxima absenken konnten, ist
behoben. Gleichzeitig wird der zehnminütige Collector vom schweren Archiv- und
Maintenance-Pfad getrennt. Die meteorologischen Champion-Parameter bleiben unverändert.

## Behobene P0-Punkte

- Actuals besitzen eine explizite Quellenqualität. `stored-metar-station` gewinnt gegen
  `metar-provisional`; ein provisorisches Maximum ist innerhalb derselben Qualitätsstufe
  monoton.
- Vor jeder provisorischen Ableitung rekonstruiert der Collector die letzten sieben
  abgeschlossenen Lokaltage aus Archiv plus Live-METAR und schreibt sie als finale
  Stationswerte.
- Die produktive Datenkopie bestätigte die automatische Reparatur für den 10. August:
  EDDM `28 → 34 °C`, EHAM `21 → 23 °C`, LTFM `26 → 28 °C`.
- Provisorische Actuals werden nur noch für den jüngsten zulässigen Lokaltag abgeleitet;
  ein abgeschnittener 48-Stunden-Antwortbereich darf ältere Tage nicht neu bewerten.

## Collector und Archivbetrieb

- Workflow 5 bleibt der einzige geplante Collector und nutzt den schnellen Datenbankjob.
- Der schnelle Lauf sammelt, reconciliiert, prüft aktuelle Coverage und persistiert;
  Retention, vollständige Archivvalidierung und SQLite-Maintenance entfallen dort.
- Workflow **8 - Daily archive verification and SQLite maintenance** führt die schwere
  Prüfung täglich um 02:17 UTC oder manuell aus.
- Das Audit trennt aktuelle Fehler von historischen Befunden. Ein alter Gap bleibt als
  Historie sichtbar, erzeugt aber keine aktive rote Warnung. Aktuelle Staleness, ein seit
  mehr als 20 Minuten fehlender Lauf und neue Gaps bleiben aktive Fehler.
- Auf der mitgelieferten realen Datenkopie sank der Coverage-Check von rund 13,1 auf
  0,9 Sekunden. Die tatsächliche GitHub-Scheduler-Cadence muss nach Deployment beobachtet
  werden; GitHub garantiert keine sekundengenaue Cron-Ausführung.

## Research-Lineage und Anzeige

- Shadow-Auswertungen speichern Raw- und Champion-Bucket-Wahrscheinlichkeit getrennt.
- Gespeichert und angezeigt werden Forecast-Snapshot-Zeit, Zieltag, lokale Capture-Zeit,
  Information Set, D-2/D-1/D0-Phase, ausführbarer Preis, Kosten, Netto-Gap und Blocker.
- `fair_probability` bleibt aus Kompatibilitätsgründen die Champion-Wahrscheinlichkeit;
  `raw_probability` enthält die echte unadjustierte Modellwahrscheinlichkeit.
- Forecast-Snapshots speichern Modal-Bucket vor TAF, finalen Champion-Modal-Bucket und
  `taf_modal_bucket_flip`.
- Madrids Phase-/CAVOK-/Radiation-Guard wird nur als Challenger aufgezeichnet. Er ist
  nicht Teil des produktiven Forecasts und besitzt keine Promotion-Abkürzung.

## Unverändert und geschützt

- Champion-Gewichte und Biaswerte;
- Madrids produktiver Anchor und die AROME-Gewichtung;
- Persistent-Hot, terminaler Day-Lock und bestehende feste Uplifts;
- mindestens 30 echte OOS-Tage vor einer Challenger-Promotion;
- Edge-, Basket- und Trading-Logik bleibt `RESEARCH ONLY`.

## Deployment

1. Inhalt von `UPLOAD_TO_GITHUB` hochladen und den Test-Workflow grün abwarten.
2. Workflow **5 - Consolidated ten-minute collector** einmal manuell starten.
3. Prüfen, dass EDDM/EHAM/LTFM für den 10. August `stored-metar-station` und
   `34/23/28 °C` zeigen.
4. Workflow **8 - Daily archive verification and SQLite maintenance** einmal manuell
   starten und den vollständigen Archivcheck abwarten.
5. Streamlit über **Manage app → Reboot app** neu starten.

Workflow 1 und Workflow 7 müssen für dieses Update nicht erneut gestartet werden. Das
Release-Paket enthält bewusst keine `data/weatherman.db` und kein History-Archiv, damit
der Upload die inzwischen jüngeren Produktionsdaten nicht überschreibt.

## Abnahme nach Deployment

### Sofort

- Test, Workflow 5 und Workflow 8 sind grün.
- Der Collector schreibt einen erfolgreichen Run und repariert die drei bestätigten
  Actuals ohne neuere Daten zu verlieren.
- Shadow zeigt Raw und Champion getrennt und bezeichnet Champion nie als Raw.
- Daily Audit meldet Manifest, Roundtrip, Hash und SQLite-Integrität als gültig.

### Nach mindestens drei geplanten Läufen

- Läufe erscheinen ungefähr im Zehn-Minuten-Takt; kein aktueller Gap > 20 Minuten.
- Der schnelle Job beendet sich vor dem nächsten geplanten Slot.
- Stale- oder Coverage-Meldungen unterscheiden aktive und historische Befunde.

### Nach 24 Stunden

- D-1@20, D0@06 und D0@10 werden regulär erfasst, soweit sie fällig sind.
- Türkei-D0@10, LTFM-Marktcoverage und Post-Peak-Journaling gesondert prüfen.
- Workflow 8 läuft genau einmal und Workflow 5 bleibt währenddessen über dieselbe
  Concurrency-Gruppe serialisiert.

## Lokale Abnahme

- Ruff ohne Befund.
- 163 Tests mit dem Quellpfad bestanden.
- 163 Tests gegen den mechanischen Spiegel `build/lib` bestanden.
- 163 Tests aus dem datenfreien Release-Staging bestanden.
