# Weatherman Project Handoff

Stand: 20. August 2026

Gebaut: **v10.7.10**

Ausgangsbasis: öffentliche v10.7.9.1, geprüfter Collector-HEAD
`e845f55b3cb2cee8c7fec7b0e67ef6a4c45b8d8d`; nachfolgende reine Datencommits
werden beim Upload nicht durch eine Paketdatenbank überschrieben.

## v10.7.10 Stabilitäts- und Datenfix

- Ein stale Forecast ist ausnahmslos diagnostisch und kann nicht mehr in den Champion
  zurückfallen. Bei null frischen Modellen existiert kein Live-Champion; bei einem
  frischen Modell bleibt die Vorschau stale/handelsgesperrt.
- Checkpoints speichern expected, available, fresh und used getrennt. Der in der
  Provenance gezeigte `used_by_champion`-Status stammt aus derselben Auswahl wie die
  tatsächliche Berechnung.
- Der schnelle Collector persistiert bei schwellenbedingter Maintenance Datenbank und
  verifizierte Archive atomar. Ein nicht gestagtes Archiv verhindert den Commit.
- Der bestätigte Verlustpfad wurde rückwirkend repariert: UTC 16. und 17. August wurden
  aus den committeten SQLite-Ständen `cd912130` und `a7f796e9` wiederhergestellt.
  62.812 eindeutige Zeilen ergänzen 26 Tagespartitionen; das Gesamtarchiv enthält
  danach 579.736 hash- und roundtrip-verifizierte Zeilen.
- Meteoblue verwendet ohne neuen Key ausschließlich das bestehende Free-Tier: ein
  Versuch pro Airport/Lokaltag ab 09:00, persistente Zählung erfolgreicher und
  fehlgeschlagener Versuche und 24 Stunden Cooldown nach 429/Quota/Credit-Fehlern.
  Open-Meteo, METAR, TAF und Polymarket sind davon entkoppelt.
- Post-Peak Upper Tail, Munich Late Heating und Reheating-Klassifikation bleiben
  Research-only und werden erst in v10.8.0 replayt.

Produktive Forecast-Gewichte, Biases, Regimekoeffizienten, TAF-Stufe, Day-/Peak-Lock,
Promotion-Gates und Wettlogik sind unverändert.

## v10.7.9.1 Synchronisations-Hotfix

- Overview und Airport detail rufen denselben zentralen aktuellen Nowcast-Builder auf.
- Der Overview-Pfad verwendet nicht mehr die historische kausale Checkpoint-
  Rekonstruktion, die abweichende Run-Zeitstempel und Modellselektionen erzeugen konnte.
- Der Cache ist auf 15 Sekunden begrenzt und zusätzlich an die Datenbankversion gebunden.
- Der erste gespeicherte Live-Champion nach D0@10 erscheint mit Forecast- und METAR-
  Zeitstempel im oberen KPI-Bereich der Airport-Detailseite.
- Keine Forecast-, Bias-, Regime-, TAF-, Lock- oder Wahrscheinlichkeitsformel wurde
  verändert.

Regression: Overview und Detail lieferten beim selben `as_of` für LEMD exakt denselben
Championwert; 191 Tests sind in beiden Codepfaden erforderlich.

## v10.7.9 Ergebnis

v10.7.9 baut den produktiven Trading Desk um die tatsächliche Nutzungsreihenfolge auf:
Sechs-Airport-Übersicht, Ein-Klick-Gesamtrefresh, Kernmetriken, Forecast Chain,
Reliability und temperatur-sortierte Buckets. Accuracy by Timing wurde auf eine kompakte
Champion-Zeitpunktübersicht plus einklappbare Ladder reduziert und terminologisch
vereinheitlicht.

Stabilität und Datenqualität:

- Der All-Airport-Pfad reduziert jeden Airport sofort auf kleine Dictionaries; sechs
  historische DataFrame-Sätze werden nicht gleichzeitig im Streamlit-State gehalten.
- Der globale Refresh fragt nur fällige Modelle neu ab, aktualisiert METAR/TAF/Markt,
  isoliert Providerfehler je Airport und behält SQLite als Single Writer.
- Verified Maintenance startet im Fast-Collector bereits ab 35 MiB; 48 MiB bleibt das
  harte Limit.
- Finale Stations-Actuals bleiben monoton geschützt; ein expliziter 48-Stunden-
  Regressionstest verhindert eine Rückstufung durch provisional Actuals.
- Checkpoints speichern Marktstatus/-zeit/-Bucketzahl sowie erwartete, verfügbare,
  frische, verwendete und ausgeschlossene Modelle samt Ausschlussgrund.
- Post-Peak-/Upper-Tail-Diagnostik speichert den Radiation-only-Kandidaten, Upper-Tail-
  Masse, Trend, Restwärmung und Peakabstand ausschließlich als Research-Lineage.

Nicht verändert wurden Champion-Formel, Gewichte, Biases, Anchors, Regimekoeffizienten,
TAF-Wirkung, Day-/Peak-Lock, Promotion-/Safety-Gates und Wettlogik. Kein Challenger wurde
promotet; Historical Replay bleibt eine separate Research-Version.

Verifikation: 189 Tests gegen `src`, 189 Tests gegen den mechanischen `build/lib`-
Spiegel, Ruff auf App/Source/Tests/Build, SQLite `quick_check=ok`. Kerntabellen-Row-Counts
blieben bei der additiven Schema-Migration unverändert.

---

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
3. Im Coverage-Bereich einen neuen v10.7.10-Lauf mit getrennten Zeitstempeln prüfen.
4. Workflow **8 - Daily archive verification and SQLite maintenance** starten.
5. Streamlit einmal neu booten und Trading Desk/Checkpoint-Anzeige prüfen.
6. Den manuellen Live-Refresh für mindestens zwei Airports testen.

Workflow 1, Workflow 7 und ein Jahres-Backfill sind nicht erforderlich.

## Rollback

Der Release ist code-seitig durch erneutes Hochladen des letzten v10.7.9.1-Pakets
rückrollbar. Die neue SQLite-Spalte ist additiv und wird von v10.7.9.1 ignoriert;
ein Datenbank-Downgrade oder Löschen von Spalten ist nicht erforderlich. Vor dem Upload
bleibt die aktuelle Repository-/DB-Version der Wiederherstellungspunkt.

## Empfehlung für v10.8.0

Nach produktiver Abnahme von v10.7.10 kann ein strikt isolierter 30-Tage-Pilot für
Madrid und München beginnen. Voraussetzung ist, dass die neue Collector-Lineage über
mehrere reale Läufe valide ist und der Readiness-Bericht die Pilotinputs je Zeitpunkt
als historisch-kausal oder ausdrücklich `reconstructed-research` klassifiziert. Ein
365-Tage-Replay bleibt bis zur Pilotabnahme gesperrt.
