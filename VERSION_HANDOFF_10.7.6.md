# Version 10.7.6

Stand: 14. August 2026
Ausgangsbasis: v10.7.5-Hotfix auf produktivem v10.7.4-`main` `1a19613`

## Ergebnis

v10.7.6 ersetzt den zu schmalen METAR-/TAF-only-Button aus v10.7.5 durch einen
gezielten, schnellen **Live Trading Refresh**. Er aktualisiert den vollständigen
Informationsstand, den der Trading Desk für den ausgewählten Airport und Zieltag
benötigt, ohne zur blockierenden historischen `collect()`-Pipeline zurückzukehren.

## Aktualisierte Live-Quellen

- alle für den Airport konfigurierten Open-Meteo-Tagesmodelle;
- Hourly-Pfad jedes dieser Modelle inklusive Taupunkt, Wolken, Wind, Strahlung und
  850-hPa-Temperatur, soweit der Provider die Variable anbietet;
- Meteoblue, wenn der API-Key konfiguriert ist;
- aktueller 48-Stunden-METAR-Pfad;
- aktuelle TAF-Revision;
- Polymarket-Preise, Best Bid und Best Ask für genau den ausgewählten Zieltag.

## Laufzeit- und Fehlergrenzen

- Alle Provider-Aufrufe laufen parallel.
- Open-Meteo/Meteoblue/Polymarket: ein Versuch, höchstens sieben Sekunden pro Request.
- METAR/TAF: ein Versuch, höchstens fünf Sekunden pro Request.
- Open-Meteo-Metadaten: ein Versuch, höchstens fünf Sekunden.
- Datenbankschreibvorgänge bleiben seriell und erfolgen erst nach Abschluss der
  Netzwerkphase.
- Ein einzelner Providerfehler verwirft nicht die erfolgreichen Ergebnisse anderer
  Quellen; die App nennt die fehlgeschlagenen Quellen ausdrücklich.

## Bewusste Abgrenzung

Der Button führt nicht aus:

- historische Forecast- oder Marktpreis-Backfills;
- Reanalysis-Actuals;
- Research-Checkpoint-Rekonstruktionen;
- fünf Markttage statt des ausgewählten Zieltags;
- GitHub-Workflow-Dispatch;
- Git-Commit oder Push.

Persistentes kausales Journaling bleibt beim kontrollierten Workflow-5-Writer. Der
Button aktualisiert die aktive Streamlit-Datenkopie für die unmittelbare Trading-
Entscheidung.

## Stale-Model-Fix

Der produktive Stale-Filter verwendet `Forecast.fetched_at` und lässt regulär nur
Modelle bis zum konfigurierten Alter von 90 Minuten in den Champion einfließen. Der neue
Refresh schreibt für jedes erfolgreich abgefragte Modell einen neuen echten
`fetched_at`-Zeitpunkt. Dadurch fließen erfolgreich aktualisierte Modelle unmittelbar
wieder in den Live Forecast ein. Ein wirklich fehlgeschlagener Provider bleibt korrekt
als stale beziehungsweise fehlend sichtbar.

## Übernommen aus v10.7.5

- Actual-Selbstheilung bei jedem Aviation-Journal-Lauf, unabhängig vom Trading-Fenster;
- monotone Source-Priorität und Schutz finaler `stored-metar-station`-Actuals;
- gezielte Reparatur der bestätigten falschen Werte vom 10. und 11. August;
- keine Produktionsdatenbank und keine History-Artefakte im Release.

## Unverändert und geschützt

- Forecast- und Champion-Formeln;
- Modellgewichte und Biaswerte;
- Madrid-Anchor und AROME-Gewichtung;
- Regimewirkungen, TAF-Stufe und Day-Lock;
- Challenger-/Rollback-/30-OOS-Gates;
- Edge-, Basket- und Trading-Logik bleibt `RESEARCH ONLY`.

## Deployment

1. Inhalt von `UPLOAD_TO_GITHUB` vollständig hochladen und vorhandene Dateien ersetzen.
2. Grünen Workflow **Test** abwarten.
3. Workflow **5 - Consolidated ten-minute collector** einmal manuell starten.
4. Workflow **8 - Daily archive verification and SQLite maintenance** einmal starten.
5. Streamlit über **Manage app → Reboot app** neu starten.
6. Im Trading Desk **Refresh live trading data** drücken.
7. Prüfen, dass aktualisierte Modellzahlen, METAR/TAF, Polymarket-Buckets und Laufzeit
   angezeigt werden und kein GitHub-Workflow startet.

Workflow 1 und Workflow 7 sind nicht erforderlich.

## Verifikation

- Ruff: ohne Befund;
- vollständige Tests gegen `src`: 166 bestanden;
- vollständige Tests gegen `build/lib`: 166 bestanden;
- geschützte Forecast-/Trading-Engine und Produktionsdatenbank: unverändert;
- Release enthält weder Produktionsdatenbank noch History-Archiv.
