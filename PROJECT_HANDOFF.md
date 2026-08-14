# Weatherman Project Handoff

Stand: 14. August 2026
Gebaut: **v10.7.6**
Produktive Ausgangsbasis: **v10.7.4**, `main`-Commit `1a19613`

## Aktueller Auftrag und Ergebnis

v10.7.6 ist ein UI-/Daten-/Prozess-Hotfix ohne meteorologische Engine-Änderung. Er
kombiniert zwei notwendige Korrekturen:

1. Stations-Actuals heilen sich bei jedem Collector-Lauf unabhängig vom Trading-Fenster.
2. Der Trading Desk besitzt wieder einen vollständigen manuellen Live-Refresh für Modelle,
   Hourly-Pfade, Meteoblue, METAR, TAF und Polymarket, ohne die schwere `collect()`-
   Pipeline synchron auszuführen.

## Ursache der Refresh-Probleme

- v10.7.4 führte beim Streamlit-Button `collect([airport])` aus. Das aktualisierte zwar
  viele Quellen, startete aber zusätzlich historische Actual-, Mehrtages-Markt- und
  Journalpfade. Ein Live-Test hing länger als 30 Sekunden; produktive Modellläufe
  benötigten teilweise 13 bis 18 Minuten.
- v10.7.5 begrenzte den Button deshalb auf METAR und TAF. Das verhinderte das Hängen,
  ließ aber bei verspätetem GitHub-Collector Modelle mit `fetched_at > 90 Minuten` stale
  und aktualisierte keine Polymarket-Preise. Für manuelles Trading war das zu schmal.

## Architektur v10.7.6

### On-demand Live Trading Refresh

Für genau den ausgewählten Airport und Zieltag werden parallel abgerufen:

- sämtliche konfigurierte Open-Meteo-Daily-Modelle;
- die zugehörigen Hourly-Pfade;
- Meteoblue bei vorhandenem Key;
- METAR und TAF;
- Polymarket inklusive Best Bid/Best Ask.

Jede Quelle hat einen einzelnen begrenzten Versuch. METAR/TAF besitzen fünf Sekunden,
die übrigen Provider höchstens sieben Sekunden Timeout. Open-Meteo-Metadaten sind auf
einen fünfsekündigen Versuch begrenzt. Erfolgreiche Ergebnisse werden anschließend in
einer einzigen seriellen Datenbankphase gespeichert.

Der Button führt keine Backfills, Reanalysis, Research-Rekonstruktionen, mehrtägigen
Marktschleifen, GitHub-Dispatches, Commits oder Pushes aus. Das kausale Produktionsjournal
bleibt beim kontrollierten Workflow-5-Writer.

### Stale-Semantik

Der Live-Nowcast filtert anhand von `fetched_at` und maximal 90 Minuten Alter. Jeder
erfolgreiche On-demand-Fetch schreibt einen neuen echten Fetch-Zeitpunkt. Erfolgreich
aktualisierte Modelle fließen deshalb sofort wieder in den Champion ein. Nicht erreichbare
Provider bleiben sichtbar stale; sie werden nicht künstlich als frisch markiert.

### Actual-Selbstheilung

Der stets laufende Aviation-Journal-Pfad rekonstruiert weiterhin die letzten sieben
abgeschlossenen Lokaltage aus `archive + live`, unabhängig von Critical Window und
Post-Peak Window. Source-Priorität und monotone Provisional-Grenze bleiben erhalten.

Die isolierte Produktionskopie bestätigte diese Korrekturen:

- EDDM 10.08.: `28 → 34 °C`
- EHAM 10.08.: `21 → 23 °C`
- LTFM 10.08.: `26 → 28 °C`
- EDDM 11.08.: `30 → 31 °C`
- EPWA 11.08.: `21 → 22 °C`
- LTAC 11.08.: `31 → 32 °C`
- LTFM 11.08.: `26 → 27 °C`

## Unverändert und geschützt

- Champion-Modellgewichte und Biaswerte;
- Madrid-Anchor und AROME-Gewichtung;
- produktive Regime und Day-Lock;
- TAF bleibt separate Forecast-Stufe;
- Challenger-/Rollback-/30-OOS-Gates;
- Edge-, Basket- und Trading-Logik bleibt `RESEARCH ONLY`;
- keine automatische Engine-Anpassung oder Promotion.

## Deployment und Abnahme

1. Gesamten Inhalt von `UPLOAD_TO_GITHUB` hochladen.
2. Grünen Test abwarten.
3. Workflow **5 - Consolidated ten-minute collector** manuell starten.
4. Actuals vom 10.–13. August und `stored-metar-station` prüfen.
5. Workflow **8 - Daily archive verification and SQLite maintenance** starten.
6. Streamlit neu booten.
7. **Refresh live trading data** für mindestens Madrid und einen zweiten Airport testen.
8. Kontrollieren: aktualisierte Modelle/Hourly/METAR/TAF/Polymarket, transparente
   Teilfehler, kein GitHub-Workflow durch den Button.

Workflow 1 und Workflow 7 sind nicht erforderlich.

## Weiter beobachten

- reale Button-Laufzeit und einzelne Providerfehler;
- tatsächliche GitHub-Collector-Cadence statt nur YAML-Cron;
- D-1@20, D0@06, D0@10 und Live-Coverage;
- Türkei-D0@10, LTFM-Marktcoverage und Post-Peak-Journaling;
- alle fachlichen Airport-/Regime-Hypothesen ausschließlich OOS.

## Nächste Forschungsstufe

Das Historical Replay Lab bleibt getrennt. Der Madrid-/München-Pilot beginnt erst nach
produktiver Abnahme von v10.7.6. Historisch-kausale, rekonstruierte und nicht verfügbare
Evidenz dürfen nicht vermischt werden.
