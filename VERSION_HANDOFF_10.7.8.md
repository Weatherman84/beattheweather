# Version Handoff 10.7.8

## Release-Grenze

v10.7.8 stabilisiert den produktiven Streamlit-Trading-Desk, korrigiert die
Checkpoint-Provenance und ergänzt eine ressourcenschonende Forecast Ladder History.
Forecast-Engine, Biases, Gewichte, Anchors, Regimekoeffizienten, Day-/Peak-Lock,
TAF-Stufe, Promotion- und Trading-Gates bleiben unverändert. Historical Replay ist
nicht Bestandteil dieses Releases.

## Implementiert

- zeilenweises Airport-/Zeitfiltering komprimierter Archive vor DataFrame-Erzeugung;
- Zieltagbegrenzung der Hochfrequenzdaten im Trading Desk;
- 90-Tage-Kalibrierungsfenster ohne Verkürzung der Regime-/OOS-Evidenz;
- Airport Research aus der Produktionsnavigation entfernt und Direktseite entschärft;
- Forecast Ladder History mit D-1, D0@06, D0@10 und erstem Live-Stand;
- Raw/Bias/METAR/Champion, signierter Fehler, Actual-Provenance, Evidence, Freshness,
  Source Age sowie Bias/MAE/N;
- Filter für Zeitraum, reguläre OOS-geeignete Produktionssnapshots und Rekonstruktionen;
- `expected`, `available`, `used by Champion` und Extra-Modelle getrennt gespeichert;
- Coverage maximal 100 % und Freshness nur aus relevanten erwarteten Quellen;
- Cadence-Diagnose mit Trigger-, Queue-, Median- und P95-Laufzeit.

## Gemessener Nutzen

Auf dem produktiven Datenstand `04891c6` sank ein reproduzierbarer Leselauf für einen
Airport und dieselben Trading-Desk-Tabellen:

| Messwert | v10.7.7 | v10.7.8 |
|---|---:|---:|
| Peak-RSS | ca. 777 MB | ca. 186 MB |
| gehaltene DataFrames | 29,5 MB | 4,9 MB |
| geladene Zeilen | 111.199 | 11.249 |

Die Messung isoliert den Datenladepfad; Streamlit- und Plotly-Overhead kommt im Betrieb
hinzu. Sie belegt dennoch, dass die akute Vollarchiv-Materialisierung entfernt ist.

## Collector-Befund

Der aktuelle 24-Stunden-Bericht enthält 44 von 144 erwarteten Slots (30,6 %), Median-
Laufzeit 27 Sekunden, P95 124 Sekunden und Median-Concurrency-Queue 0 Sekunden. Die
gespeicherten Jobs sind damit deutlich kürzer als zehn Minuten und blockieren einander
nicht nennenswert. Fehlende Slots entstehen vor dem Workflow-Start an der GitHub-
Schedule-Dispatch-Grenze. GitHub liefert für nicht erzeugte Cron-Events keinen
Skip-Grund; der Bericht kennzeichnet diese Schlussfolgerung daher als beobachtete
Bottleneck-Grenze, nicht als beweisbare interne GitHub-Ursache.

## Nicht übernommen

- keine Engine-, Anchor-, Bias-, Gewichts- oder Regimeänderung;
- keine München-/Madrid-/Istanbul-Pauschalkorrektur;
- keine Challenger-Promotion;
- keine Day-/Peak-Lock- oder TAF-Änderung;
- keine Lockerung von Safety-, Kalibrierungs- oder Markt-Konflikt-Gates;
- kein paralleler SQLite-Writer und keine riskante Workflow-Aufteilung;
- kein 30- oder 365-Tage-Replay;
- keine automatische Ableitung produktiver Regeln aus der Ladder History.

## Tests und Acceptance

- Ruff vollständig grün;
- 181 Tests gegen `src` grün;
- vollständige Suite gegen den mechanischen `build/lib`-Spiegel erforderlich;
- additive Migration auf einer Datenbankkopie;
- SQLite `PRAGMA quick_check` und unveränderte Kerntabellen-Row-Counts;
- Spiegelvergleich `src/weatherman` gegen `build/lib/weatherman`;
- frisches Entpacken und erneuter Test des Upload-ZIP;
- kein Produktions-DB- oder History-Archiv im Upload-Paket.

## Deployment

1. Den vollständigen Inhalt von `UPLOAD_TO_GITHUB` hochladen.
2. Grünen GitHub-Test abwarten.
3. Workflow **5 - Consolidated ten-minute collector** einmal manuell starten.
4. Workflow **8 - Daily archive verification and SQLite maintenance** einmal starten.
5. Streamlit über **Manage app → Reboot app** einmal neu starten.
6. Trading Desk für mindestens zwei Airports öffnen, Forecast Ladder History prüfen und
   je einen manuellen Live-Refresh testen.

Workflow 1, Workflow 7 und ein Backfill sind nicht erforderlich.

## Rollback

Das zuvor verwendete v10.7.7-Paket erneut vollständig hochladen. Die neuen Spalten sind
additiv und werden von v10.7.7 ignoriert; sie müssen nicht gelöscht werden. Vorhandene
Forecast-, Actual-, Markt- und OOS-Zeilen werden von v10.7.8 nicht umgeschrieben.

## Nächster Schritt

Nach stabiler produktiver Beobachtung kann v10.8.0 als physisch isolierter Research-
Pilot beginnen: LEMD und EDDM über 30 Tage, anschließend bei bestandenen Coverage- und
Leakage-Gates Ausweitung auf die sechs Trading-Airports. Replay-Berechnungen dürfen nie
bei normalen Streamlit-Reruns laufen und niemals automatisch den Champion verändern.
