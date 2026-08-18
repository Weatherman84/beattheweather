# Version Handoff 10.7.9

## Release-Grenze

v10.7.9 ist ein Stabilitäts-, Datenqualitäts- und Trading-Desk-Release. Es ändert
keine produktive Forecast-Formel und promotet keinen Challenger.

## Implementiert

- neue Standardansicht für alle sechs Airports mit Champion, METAR, Tagesmaximum,
  Trend, Forecast Chain, Reliability und temperatur-sortierten relevanten Buckets;
- ein globaler, fehlertoleranter Refresh mit Wiederverwendung frischer Modelle und
  weiterhin seriellen SQLite-Schreibvorgängen;
- Detailansicht entlang der realen Nutzungsreihenfolge; Forecast Chain und Reliability
  stehen direkt nebeneinander;
- Reliability als Exact Bucket, ±1 °C, MAE und N, ausschließlich aus scheduled,
  pre-peak OOS-Snapshots mit finalem Stations-Actual;
- vereinheitlichte Zeitpunkte und Forecast-Stufen mit zentralem Glossar;
- vereinfachtes Accuracy & Reliability ohne die redundante aktive Stufe
  `Final incl. TAF`; TAF bleibt separate Guidance;
- Market Comparison und Shadow Watcher aus der normalen Navigation verborgen; schwere
  Shadow-/Basket-Frames werden im normalen Trading Desk nicht geladen;
- Verified Maintenance im schnellen Collector bereits ab 35 MiB;
- Checkpoint-Marktstatus und Modell-Auswahl-/Ausschlussgründe als additive Lineage;
- Research-only Post-Peak-Diagnostik für Radiation-only Upper-Tail-Zustände.

## Verifiziert

- Ausgangsdatenbank: `PRAGMA quick_check = ok`, Daten bis 18. August 2026;
- additive Schema-Migration: 88 auf 92 Forecast-Snapshot-Spalten;
- unveränderte Kerntabellen-Row-Counts nach der Migration;
- sechs reale Airport-Zusammenfassungen erfolgreich aufgebaut;
- 189 Tests gegen `src` grün;
- 189 Tests gegen `build/lib` grün;
- Ruff für App, Source, Tests und Build grün.

## Bewusst nicht verändert

- Champion-Gewichte, Airport-Biases und Anchors;
- Regimekoeffizienten und TAF-Wirkung;
- produktive Day-/Peak-Lock- oder Upper-Tail-Regel;
- Promotion-, Safety-, Kalibrierungs- und Markt-Konflikt-Gates;
- Wettlogik und `RESEARCH ONLY`-Status;
- Historical Replay oder automatische Produktionsänderungen aus Research.

## Deployment

1. Das schlanke Delta-Paket in das bestehende Repository hochladen und Dateien ersetzen.
2. Den grünen GitHub-Test abwarten.
3. Workflow **8 - Daily archive verification and SQLite maintenance** einmal starten.
4. Danach Workflow **5 - Consolidated ten-minute collector** einmal manuell starten.
5. Streamlit einmal über **Manage app → Reboot app** neu starten.
6. `All airports` öffnen, einmal `Refresh all airports` ausführen und danach für zwei
   Airports die Detailansicht prüfen.

Kein Backfill, Workflow 1, Workflow 7 oder Historical Replay ist für dieses Update nötig.

## Rollback

Vor dem Upload bleibt der aktuelle Repository-Commit der Wiederherstellungspunkt. Für
den Code-Rollback die v10.7.8-Dateien erneut hochladen. Die vier neuen
Forecast-Snapshot-Spalten sind nullable/defaulted und werden von v10.7.8 ignoriert;
ein Datenbank-Downgrade ist nicht erforderlich. Bestehende Forecast-, Actual-, Markt-
und OOS-Zeilen werden nicht umgeschrieben.

## Nächster Schritt

Nach mehreren stabilen Live-Tagen kann der isolierte 30-Tage-Replay-Pilot für LEMD und
EDDM als separate Research-Version beginnen. Die Post-Peak-Fälle vom 17. und 18. August
bleiben bis zur Replay-/OOS-Prüfung diagnostisch und verändern den Champion nicht.
