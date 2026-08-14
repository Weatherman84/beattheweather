# Version 10.7.5

Stand: 14. August 2026
Ausgangsbasis: veröffentlichte Version 10.7.4, `main`-Commit `1a19613`

## Ergebnis

Version 10.7.5 ist ein reiner Produktions-Hotfix für Live-Refresh und Actual-
Selbstheilung. Forecast-Engine, Champion-Gewichte, Biaswerte, Madrid-Anchor,
Regimewirkungen, Day-Lock, Challenger-Gates und Trading-Logik bleiben unverändert.

## Behobene Fehler

### Streamlit-Refresh

- Der Button heißt jetzt **Refresh METAR + TAF**.
- Er ruft ausschließlich `collect_live_aviation(airport, include_taf=True)` auf.
- METAR und TAF verwenden jeweils einen einzelnen Versuch mit fünf Sekunden Timeout.
- Der Button lädt keine Modelle, Hourly Forecasts, Actual-Reanalysis oder Marktdaten.
- Der Button startet ausdrücklich keinen GitHub-Workflow.
- Persistente Forecast-Sammlung bleibt beim kontrollierten GitHub-Datenbank-Writer.

Damit kann der Streamlit-Prozess nicht mehr minutenlang in der vollständigen
`collect()`-Pipeline hängen.

### Actual-Selbstheilung

- `collect_aviation_journal()` rekonstruiert nun bei jedem Collector-Lauf die letzten
  sieben abgeschlossenen Lokaltage aus `archive + live`.
- Die Reparatur ist nicht mehr vom kritischen Trading- oder Post-Peak-Fenster abhängig.
- Der bestehende monotone Quellenschutz bleibt erhalten:
  `stored-metar-station` kann nicht durch `metar-provisional` oder Reanalysis
  herabgestuft werden.
- Es werden nur gezielte Upserts durchgeführt; Datenbank und Historie werden weder
  gelöscht noch zurückgesetzt.

## Reale Reparaturprobe

Auf einer isolierten Kopie des aktuellen Produktionsstands wurden alle sechs Airports
für den 10. bis 13. August erfolgreich zu `stored-metar-station` hochgestuft. Dabei
wurden folgende falsche Werte korrigiert:

| Airport/Tag | Vorher | Stationsmaximum |
|---|---:|---:|
| EDDM · 10.08. | 28 °C | 34 °C |
| EHAM · 10.08. | 21 °C | 23 °C |
| LTFM · 10.08. | 26 °C | 28 °C |
| EDDM · 11.08. | 30 °C | 31 °C |
| EPWA · 11.08. | 21 °C | 22 °C |
| LTAC · 11.08. | 31 °C | 32 °C |
| LTFM · 11.08. | 26 °C | 27 °C |

Auch bereits numerisch richtige Provisionals wurden auf die korrekte finale
Stations-Lineage hochgestuft.

## Tests

- Regression: finaler Stationswert kann nicht durch Provisional herabgestuft werden.
- Regression: Provisional bleibt monoton, wenn ein Peak aus dem Providerfenster fällt.
- Neu: Aviation Journal repariert einen abgeschlossenen Tag außerhalb jedes
  Trading-Fensters.
- Neu: Streamlit-Button enthält weder `collect([airport])` noch einen GitHub-Dispatch.
- Reparaturprobe ausschließlich auf einer Datenbankkopie; produktive Daten wurden beim
  Build nicht verändert.
- Ruff ohne Befund.
- 165/165 Tests gegen `src` bestanden.
- 165/165 Tests gegen den mechanischen `build/lib`-Spiegel bestanden.
- 165/165 Tests in beiden Modi aus der frisch entpackten, datenfreien Release-ZIP
  bestanden.

## Weiterhin offener Infrastrukturpunkt

GitHub enthält zwar den `*/10`-Cron, die tatsächlich gespeicherten Läufe nach dem
v10.7.4-Upload hatten jedoch häufig 50 bis 120 Minuten Abstand. Zwei Modellläufe
dauerten rund 13 beziehungsweise 18 Minuten. GitHub garantiert keine exakte Cron-
Ausführung. v10.7.5 macht diesen Befund sichtbar, behauptet aber keine technisch nicht
erreichbare Zehn-Minuten-Garantie.

## Deployment

1. Inhalt von `UPLOAD_TO_GITHUB` hochladen und vorhandene Dateien ersetzen.
2. Grünen Test-Workflow abwarten.
3. Workflow **5 - Consolidated ten-minute collector** einmal manuell starten.
4. Prüfen, dass die Actuals vom 10. bis 13. August `stored-metar-station` sind und die
   sieben oben genannten Korrekturen enthalten.
5. Workflow **8 - Daily archive verification and SQLite maintenance** einmal starten.
6. Streamlit über **Manage app → Reboot app** neu starten.
7. **Refresh METAR + TAF** einmal testen; dabei darf kein GitHub-Workflow erscheinen.

Workflow 1 und Workflow 7 sind nicht erforderlich. Das Release enthält bewusst keine
Produktionsdatenbank und kein History-Archiv.
