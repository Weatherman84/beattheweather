# Version Handoff 10.7.9.1

## Ursache

Die All-airport Overview verwendete den für historische Checkpoints vorgesehenen
kausalen Rekonstruktionspfad. Airport detail verwendete dagegen den aktuellen
Live-Datenpfad. Insbesondere die Behandlung von `available_at`, `run_at`, aktuellen
Actuals und Modellfrische konnte deshalb unterschiedliche Championwerte erzeugen.
Zusätzlich konnte die Overview bis zu 60 Sekunden gecacht bleiben.

## Korrektur

- Ein zentraler `build_current_live_nowcast` ist nun die einzige aktuelle
  Championberechnung für Overview und Airport detail.
- Beide Ansichten verwenden identische Datenfenster, Frischegrenzen, Regimeprofile und
  Regime-Memory-Konfiguration.
- Overview-Cache: maximal 15 Sekunden und weiterhin an die Dateiversion der SQLite-
  Datenbank gebunden.
- Jeder Overview-Wert zeigt seine Berechnungszeit.
- Airport detail zeigt den ersten gespeicherten Live-Champion nach D0@10 mit Forecast-
  und METAR-Zeitstempel, Evidence und Freshness.

## Nicht verändert

Keine produktive Forecast-, Bias-, Weighting-, TAF-, Regime-, Day-Lock-, Safety- oder
Trading-Regel wurde verändert. Datenbank und Archive benötigen keine Migration und
keinen Backfill.

## Verifikation

- identischer LEMD-Champion in Overview und Detail bei gleichem Datenstand und `as_of`;
- erster Live-Champion funktioniert auch am aktuellen, noch nicht finalisierten Tag;
- 191 Tests gegen `src` und `build/lib`;
- Ruff und SQLite-Integritätsprüfung.

## Deployment

1. Hotfix-ZIP entpacken und den Inhalt von `UPLOAD_TO_GITHUB` hochladen.
2. Grünen GitHub-Test abwarten.
3. Streamlit einmal neu booten.
4. `All airports` öffnen und `Refresh all airports` einmal ausführen.
5. Einen Airport in `Airport detail` öffnen und den identischen Championwert prüfen.

Workflow 5, Workflow 8 und Backfills sind für diesen reinen Code-Hotfix nicht zwingend.

