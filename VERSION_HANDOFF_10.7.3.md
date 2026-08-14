# Version 10.7.3

## Neu

- Verlustfreie, kopiebasierte Archivmigration für alle relevanten append-only Tabellen.
- Deterministische gzip-JSONL-Tagespartitionen mit Manifest, SHA-256, Row-count,
  Zeitbereich, Spalten-/Schema- und Roundtrip-Prüfung.
- Gemeinsame deduplizierende `archive + live`-Leseschicht für Trading Desk, Research,
  Accuracy, TAF und Nowcast.
- Konsolidierter zehnminütiger Collector mit `collection_runs`,
  `collection_coverage` und sichtbarem Coverage-Audit.
- Vollständiges TAF-Revisionsjournal mit Content-Hash, First-seen-/Fetch-Zeit,
  Revisionsbezug, Backfill-Marker und exakter Forecast-Snapshot-Lineage.
- Gezielter Workflow 7 für die transparent klassifizierte Wiederherstellung der Lücken
  vom 10./11. August 2026.
- Monotoner terminaler Peak-Lock innerhalb desselben Flughafen-Lokaldatums.

## Geändert

- Aktive SQLite-Retention standardmäßig drei Tage; Collection-Protokolle 14 Tage.
- Datenbank-Jobs validieren Archiv und SQLite, erzwingen eine aktive Grenze von 48 MiB
  und committen Archiv-/Coverage-Dateien über denselben sicheren Git-Retry-Pfad.
- Workflow 5 ist der einzige geplante Datenbank-Writer. Workflow 2 und 4 bleiben manuell.
- TAF-Auswertung trennt offizielle Revisionsgenauigkeit von der tatsächlich zum
  Weatherman-Checkpoint bekannten Revision.
- Feuchteansicht zeigt Taupunkt und Temperatur–Taupunkt-Spread separat.
- `Champion expected maximum`, Zentrum vor Bucket-Konditionierung,
  Verteilungsmittel und Modal-Bucket sind getrennt beschriftet.
- `Raw model` heißt `Uncalibrated Champion probability`.

## Nicht übernommen

- Keine PostgreSQL-Auswahl oder produktive Stage-2-Migration.
- Keine Änderung an Madrids Anchor, Champion-Gewichten, Biaswerten oder allgemeinen
  Day-Lock-Schwellen.
- Keine festen München-/Istanbul-/anderen Airport-Aufschläge.
- Keine vorgezogene Challenger-Promotion; das 30-OOS-Tage-Gate bleibt bestehen.
- Keine Änderung an Edge-/Wettlogik und keine Behandlung historischer Marktpreise als
  ursprüngliche Orderbücher.
- Fehlende damalige Weatherman-Livezustände werden nicht erfunden.

## Weiter beobachten

- Reguläre, pünktliche D-1@20-, D0@06- und D0@10-Checkpoints aller sechs Airports.
- Vollständige kritische Livefenster und Post-Peak-Journaling.
- Actions-Queue-Latenz, ausgefallene/verspätete Läufe und Persistenzbestätigung.
- Amsterdam/München `observed_support` und der einmal leere Tagesanalyse-Lauf.
- Flughafenbefunde für München, Madrid, Warschau, Amsterdam, Istanbul und Ankara nur
  als Evidenz/Watchlist, nicht als neue Champion-Regel.
- TAF-Accuracy erst mit hinreichend großem, vollständig revisioniertem OOS-Sample.

## Offene Punkte

- Die mitgelieferte Quellversion enthält keine aktuelle produktive
  `data/weatherman.db`. Deshalb sind reale Tabelle-/Indexgrößen vor/nach Migration,
  das produktive Unter-50-MB-Ergebnis und der echte Archivmanifestumfang noch offen.
- Workflow 7 muss produktiv laufen; sein Bericht unter
  `data/collection/recovery-2026-08-10-11.json` ist das Ergebnis des echten Backfills.
- Der manuelle Collector-Smoke-Test sowie 24 Stunden und sieben Tage Scheduler-Beobachtung
  können erst nach Deployment bestätigt werden.

## Akzeptanzstatus

| Kriterium | Status vor Deployment | Nachweis |
|---|---|---|
| Migration zuerst auf Kopie | lokal erfüllt | Maintenance-Integrationspfad |
| Aktive SQLite deutlich unter 50 MB | synthetisch erfüllt; Produktion offen | 48-MiB-Hard-Gate |
| Zweiter Lauf idempotent | lokal erfüllt | v10.7.3-Regressionstest |
| Partition Roundtrip/Row-count/Zeit/Hash | lokal erfüllt | Manifestvalidator |
| Archiv + live entspricht Vormigration | lokal erfüllt | Forecast-/Observation-Stichprobe |
| As-of trennt live/reconstructed/backfill | lokal erfüllt | TAF-/Checkpoint-Tests |
| Mehrere TAF-Revisionen bleiben erhalten | lokal erfüllt | TX37→TX38-Test |
| EPWA-Nachtanstieg öffnet Lock nicht | lokal erfüllt | terminaler Lock-Test |
| Ein geplanter Schreibpfad | lokal erfüllt; Produktion offen | Workflow-/Collector-Tests |
| Ausfall/Verspätung erscheint im Audit | implementiert; Produktion offen | Coverage-Audit |
| Reguläre feste Checkpoints | Produktion offen | nächstes Livefenster |
| Kritische Livefenster abgedeckt | Produktion offen | 24h/7d Coverage |
| Lint und Tests | erfüllt | `ruff check app.py src tests`; `pytest -q` |
| Manueller Workflow-Smoke-Test | Produktion offen | Workflow 5 manuell |
| Alle Ansichten lesen Archiv + live | lokal implementiert/getestet | zentrale Leseschicht |

Lokales Endergebnis des Release-Builds: **151 Tests bestanden**, Ruff ohne Befund.

## Produktions-Checkliste nach Deployment

### Sofort

1. GitHub-Test grün abwarten.
2. Workflow 7 einmal ausführen und Recovery-Klassifikation prüfen.
3. `last-maintenance.json`: `integrity_check=ok`, Archiv validiert, aktive DB < 50 MB.
4. Workflow 5 manuell ausführen; Run, Coverage und Git-Persistenz müssen sichtbar sein.
5. Trading Desk und Airport Research öffnen; keine Archiv-/DB- oder Quellenfehler.

### Nach 24 Stunden

1. Kein ungeklärter Collector-Gap > 20 Minuten.
2. Verspätete/fehlgeschlagene Läufe enthalten konkreten Grund.
3. Alle fälligen festen Checkpoints sind regulär, nicht nur rekonstruiert.
4. METAR, TAF, Forecast und Markt sind während aktiver Fenster nicht stale.
5. SQLite bleibt < 50 MB; erneuter Maintenance-Lauf erzeugt keine Duplikate.
6. Nach-Peak-METARs erzeugen weiter Forecast-, Varianten- und Regime-Snapshots.

### Nach 7 Tagen

1. Archivmanifest erneut vollständig validieren; keine Hash-/Row-count-Abweichung.
2. Archiv+Live-Stichproben für mehrere Airports/Tage mit Analyseansichten vergleichen.
3. Scheduler-Latenz, Persistenzstatus und fehlende Checkpoints zusammenfassen.
4. TAF-Revisionsabdeckung und bekannte-at-checkpoint Auswertung prüfen.
5. Erst dann Stage 1 produktiv als stabil markieren und Stage-2-Recherche freigeben.
