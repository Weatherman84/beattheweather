# Weatherman Project Handoff

Stand: 16. August 2026

Gebaut: **v10.7.8**

Ausgangsbasis: produktive **v10.7.7**, Code ab `336b033`; umgesetzt auf dem aktuellen
Collector-Datenstand `04891c6`.

## Ergebnis

v10.7.8 ist ein Speicher- und Trading-Desk-Hotfix. Es verändert keine produktive
Forecast-Formel. Die bestehende SQLite-Datenbank wird nur durch nullable/defaulted
Provenance-Spalten erweitert; vorhandene Zeilen werden nicht neu berechnet oder gelöscht.

## v10.7.8 Ergebnis

- Root Cause des Streamlit-Ausfalls: `read_archive_live` materialisierte vor dem
  Airport-Filter jede vollständige komprimierte Partition. Das Trading Desk hielt zudem
  13 historische Frames und unnötige Hochfrequenzzeiträume gleichzeitig.
- Der gleiche ausgewählte-Airport-Leselauf sank von ca. 777 MB auf 186 MB Peak-RSS und
  von 29,5 MB auf 4,9 MB tatsächlich gehaltener Frame-Daten.
- Archivfilter werden zeilenweise beim Dekomprimieren angewandt; Datumsgrenzen schneiden
  Partitionen und Zeilen vor der DataFrame-Erzeugung. Hourly-, Markt-, Signal-, Shadow-,
  Basket- und Regime-Daten sind im Trading Desk auf den aktiven Zieltag begrenzt.
- Die 90-Tage-Modellkalibrierung, vollständigen finalen Actuals, Forecast-Snapshots,
  Challenger-Varianten und OOS-Gates bleiben erhalten. Live-Regimes werden nicht durch
  wenige Tage Historie ersetzt.
- Airport Research ist in Streamlit ausgeblendet und führt beim Direktaufruf keine
  Archivabfragen mehr aus. Research-Module und Roharchive bleiben für isolierte Jobs.
- Forecast Ladder History ist pro ausgewähltem Airport verfügbar: D-1 Champion,
  D0@06/D0@10/erstes Live jeweils als vollständige Raw/Bias/METAR/Champion-Kette,
  Actual-Quelle, Fehler, Evidence, Freshness, Source Age und Bias/MAE/N.
- Checkpoint-Coverage trennt erwartete, verfügbare und Champion-verwendete Modelle.
  Coverage ist auf 100 % begrenzt; zusätzliche Fremdmodelle verändern die relevante
  Freshness nicht.
- Der aktuelle Coverage-Bericht zeigt 44/144 beobachtete Slots, Median-Laufzeit ca.
  27 Sekunden, P95 ca. 124 Sekunden und Median-Queue 0 Sekunden. Damit liegt der
  beobachtete Engpass bei GitHubs Schedule-Dispatch, nicht in Collector-Laufzeit oder
  SQLite-Concurrency. Die Ursache nicht erzeugter Cron-Events bleibt von GitHub verborgen.

Weitere Details, Acceptance Criteria und Rollback: `VERSION_HANDOFF_10.7.8.md`.

## Verifizierte Befunde und Ursachen

- Die am 14. August beobachtete Collector-Cadence von 14 Läufen, median 59,8 Minuten,
  ist mit einem nominellen Zehn-Minuten-Cron nicht vereinbar.
- GitHub-Cron ist keine Startzeitgarantie. Zusätzlich serialisiert die globale
  `weatherman-database`-Concurrency jeden Datenbank-Writer mit
  `cancel-in-progress: false`. Das verhindert Korruption, bildet bei langen Jobs aber
  eine Warteschlange.
- Im bisherigen Live-Pfad wurden Provider und Airports weitgehend sequenziell gelesen.
  Retries, Setup/Checkout und Git-Pull/Commit/Push lagen im selben Job. Außerdem wurde
  eine abgeschlossene TAF-Sonderreparatur standardmäßig bei jedem Lauf geprüft.
- Der alte Collector speicherte nur einen zusammengefassten Zeitstempel. Scheduler-
  Verzögerung, Actions-Queue und eigentliche Python-Laufzeit waren dadurch nicht sauber
  auseinanderzuhalten.
- `scheduled-precutoff` beschrieb die technische Erstellung, nicht die Frische des
  ältesten verwendeten Modells. Dadurch konnten planmäßige, aber alte Snapshots zu gut
  erscheinen.

## Produktive Fixes

### Sichererer schneller Collector

- Der Cron ist auf `:07/:17/:27/:37/:47/:57` verschoben.
- Fällige Daily-/Hourly-/Meteoblue-Reads laufen mit begrenztem Worker-Pool und je einem
  kurzen Versuch. METAR und TAF werden ebenfalls parallel gelesen.
- SQLAlchemy/SQLite bleibt vollständig Single-Writer: Worker führen keine
  Datenbankschreibvorgänge aus; Ergebnisse werden danach seriell persistiert.
- Die bekannte Madrid-TAF-Gap-Reparatur ist nur noch über
  `--recover-known-taf-gap` explizit aktivierbar.
- Polymarket-Preis- und CLOB-Laufzeit sowie tatsächlich geschriebene Zeilen werden
  separat erfasst.

### Actual- und Probability-Schutz

- Finale `stored-metar-station`-Actuals können nicht durch `metar-provisional` oder
  Reanalysis-/Archivwerte überschrieben werden.
- Provisorische Actuals sind aus Kalibrierungs- und Promotion/OOS-Stichproben
  ausgeschlossen. Alte Daten ohne Provenance bleiben lesbar, werden aber nicht
  automatisch hochgestuft.
- Neue Shadow-Zeilen werden nur gespeichert, wenn Raw-, Fair-/Champion- und Snapshot-
  Lineage vollständig vorhanden und getrennt sind. Bestehende Legacy-Zeilen werden
  nicht künstlich rückbefüllt.

## Neue Observability

Jeder neue Collector-Lauf speichert:

- inferierten Soll-Slot;
- Actions-Event-Erstellung und Queue-Start;
- Python-Start, Ende und Laufzeit;
- Trigger-, Queue- und Gesamtdrift;
- Provider- und Airport-Laufzeiten;
- Status, Zeilen, Versuche und Grund je Airport/Quelle.

Der Coverage-Audit zeigt beobachtete und fehlende Soll-Slots sowie Median/P95 der
Laufzeit und Verzögerungen. Fehlende Triggerursachen bleiben ausdrücklich inferiert,
weil GitHub nicht für jeden ausgefallenen Cron-Slot einen Datensatz liefert.

Neue Checkpoints speichern zusätzlich:

- `target_time`, `forecast_run_at`, `forecast_available_at`, `forecast_fetched_at`;
- minimales, medianes und maximales Quellenalter; das operative
  `source_age_at_checkpoint` ist konservativ das älteste verwendete Modell;
- erwartete/verwendete Modellzahl und Coverage;
- Status `scheduled-precutoff`, `reconstructed-causal` oder `unavailable`;
- Freshness `fresh` (bis 30 min), `aging` (bis 90 min), `stale` (über 90 min) oder
  `unavailable`;
- Evidenz `complete` (Coverage mindestens 80 %), `partial` (mindestens 60 %),
  `insufficient` oder `unavailable`.

Die Schwellen sind zunächst Observability-Klassen, keine Trading-Gates. Historische
Kausalität wird unverändert über `available_at <= target_time` bestimmt, nie durch einen
späteren Abrufzeitpunkt.

## Research-only

- `research-peak-lock` erklärt pro Kandidat den produktiven Blocker und simuliert einen
  alternativen Lock erst nach Modellpeak, null verbleibender Modellerwärmung und einer
  fallenden METAR-Reihe. Der Bericht verändert keine Day-Lock-Logik.
- `replay-readiness` erzeugt eine Provider-/Coverage-Matrix nach Airport, Modell,
  Zeitpunkt und Evidenzklasse. Echte historische Snapshots, kausale Rekonstruktionen
  und `unavailable` werden getrennt; Leakage-Risiken werden dokumentiert.
- Beide Befehle schreiben ausschließlich Dateien unter `artifacts/research` und keine
  Produktions- oder OOS-Tabellen.

## Geschützt und unverändert

- Madrid-Anchor und bestehende AROME-HD-Behandlung;
- Champion-Gewichte und Biaswerte;
- produktive Regime-Koeffizienten und Day-Lock-Schwellen;
- TAF als separate Forecast-Stufe;
- keine festen Airport-Aufschläge;
- Challenger-, Rollback- und mindestens 30 sequenzielle OOS-Tage-Gates;
- Edge-/Wettlogik bleibt `RESEARCH ONLY`;
- keine Safety-/Kalibrierungs-/Marktkonflikt-Lockerung;
- kein 365-Tage-Replay und keine automatische Promotion.

## Deployment

1. Paketinhalt hochladen und grünen Test abwarten.
2. Workflow **5 - Consolidated ten-minute collector** einmal manuell starten.
3. Im Coverage-Bereich einen neuen v10.7.8-Lauf mit getrennten Zeitstempeln prüfen.
4. Workflow **8 - Daily archive verification and SQLite maintenance** starten.
5. Streamlit einmal neu booten und Trading Desk/Checkpoint-Anzeige prüfen.
6. Den manuellen Live-Refresh für mindestens zwei Airports testen.

Workflow 1, Workflow 7 und ein Jahres-Backfill sind nicht erforderlich.

## Rollback

Der Release ist code-seitig durch erneutes Hochladen des letzten v10.7.7-Pakets
rückrollbar. Die neuen SQLite-Spalten sind additiv und werden von v10.7.7 ignoriert;
ein Datenbank-Downgrade oder Löschen von Spalten ist nicht erforderlich. Vor dem Upload
bleibt die aktuelle Repository-/DB-Version der Wiederherstellungspunkt.

## Empfehlung für v10.8.0

Nach produktiver Abnahme von v10.7.8 kann ein strikt isolierter 30-Tage-Pilot für
Madrid und München beginnen. Voraussetzung ist, dass die neue Collector-Lineage über
mehrere reale Läufe valide ist und der Readiness-Bericht die Pilotinputs je Zeitpunkt
als historisch-kausal oder ausdrücklich `reconstructed-research` klassifiziert. Ein
365-Tage-Replay bleibt bis zur Pilotabnahme gesperrt.
