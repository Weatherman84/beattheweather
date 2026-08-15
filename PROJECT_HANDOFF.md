# Weatherman Project Handoff

Stand: 15. August 2026

Gebaut: **v10.7.7**

Ausgangsbasis: **v10.7.6**, geprüft auf `main`-Commit
`218308d7fbbb6939ad6b62034afb370448b714ec`

## Ergebnis

v10.7.7 ist das freigegebene Stabilitäts-, Observability- und Research-Readiness-
Release. Es verändert keine produktive Forecast-Formel. Die bestehende SQLite-Datenbank
wird nur durch nullable/defaulted Metadaten-Spalten erweitert; vorhandene Zeilen werden
nicht neu berechnet oder gelöscht.

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
3. Im Coverage-Bereich einen neuen v10.7.7-Lauf mit getrennten Zeitstempeln prüfen.
4. Workflow **8 - Daily archive verification and SQLite maintenance** starten.
5. Streamlit einmal neu booten und Trading Desk/Checkpoint-Anzeige prüfen.
6. Den manuellen Live-Refresh für mindestens zwei Airports testen.

Workflow 1, Workflow 7 und ein Jahres-Backfill sind nicht erforderlich.

## Rollback

Der Release ist code-seitig durch erneutes Hochladen des letzten v10.7.6-Pakets
rückrollbar. Die neuen SQLite-Spalten sind additiv und werden von v10.7.6 ignoriert;
ein Datenbank-Downgrade oder Löschen von Spalten ist nicht erforderlich. Vor dem Upload
bleibt die aktuelle Repository-/DB-Version der Wiederherstellungspunkt.

## Empfehlung für v10.8.0

Nach produktiver Abnahme von v10.7.7 kann ein strikt isolierter 30-Tage-Pilot für
Madrid und München beginnen. Voraussetzung ist, dass die neue Collector-Lineage über
mehrere reale Läufe valide ist und der Readiness-Bericht die Pilotinputs je Zeitpunkt
als historisch-kausal oder ausdrücklich `reconstructed-research` klassifiziert. Ein
365-Tage-Replay bleibt bis zur Pilotabnahme gesperrt.
