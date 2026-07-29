# Weatherman – nur über GitHub starten

Du musst **keine Befehle eingeben**, nichts programmieren und nichts auf deinem Computer
installieren.

## Was du brauchst

- ein GitHub-Konto;
- die entpackten Dateien aus dem Weatherman-Paket;
- optional deinen Meteoblue API-Key.

## Schritt 1: Neues GitHub-Projekt erstellen

1. Öffne <https://github.com/new>.
2. Bei **Repository name** schreibe: `weatherman`
3. Wähle **Private**.
4. Setze **keinen** Haken bei „Add a README file“.
5. Klicke auf **Create repository**.

## Schritt 2: Fertige Dateien hochladen

1. Entpacke die heruntergeladene ZIP-Datei auf deinem Computer.
2. Öffne darin den Ordner `UPLOAD_TO_GITHUB`.
3. Auf der leeren GitHub-Seite klicke auf den Link **uploading an existing file**.
4. Markiere **den gesamten Inhalt** des Ordners `UPLOAD_TO_GITHUB`.
5. Ziehe alles in das große Upload-Feld auf GitHub.
6. Warte, bis alle Dateien aufgelistet sind.
7. Klicke unten auf **Commit changes**.

Wichtig: Lade nicht die ZIP-Datei selbst zu GitHub hoch. GitHub würde sie nicht automatisch
entpacken. Lade den Inhalt von `UPLOAD_TO_GITHUB` hoch.

Nach dem Upload sollten auf der Startseite unter anderem diese Einträge sichtbar sein:

- `.github`
- `config`
- `src`
- `tests`
- `app.py`
- `README.md`
- `pyproject.toml`

Ab Version 9.5.2 liegt das technische Startmodul innerhalb von `src`. Dadurch kann
GitHub den Test auch dann vollständig ausführen, wenn bei einem Update keine neue
Python-Datei im Repository-Hauptverzeichnis angelegt wurde.

Ab Version 9.5.3 wechseln **Trading Desk** und **Airport Research** über
Streamlits interne Seitennavigation. Beide Bereiche bleiben im selben Browser-Tab;
der frühere absolute Markdown-Link wird nicht mehr verwendet.

## Schritt 3: Meteoblue-Key hinterlegen

Wenn du Meteoblue noch nicht verwenden möchtest, überspringe diesen Schritt.

1. Öffne dein Weatherman-Repository auf GitHub.
2. Klicke oben auf **Settings**.
3. Links auf **Secrets and variables** klicken.
4. Darunter **Actions** auswählen.
5. Klicke auf **New repository secret**.
6. Bei **Name** exakt eintragen: `METEOBLUE_API_KEY`
7. Bei **Secret** deinen echten Meteoblue-Key einfügen.
8. Klicke auf **Add secret**.

Der Key ist danach geschützt und wird nicht öffentlich angezeigt.

## Schritt 4: Historische Daten einmalig laden

1. Klicke oben im Repository auf **Actions**.
2. Falls GitHub nach einer Bestätigung fragt, aktiviere die Workflows.
3. Klicke links auf **1 - Initial history backfill**.
4. Rechts auf **Run workflow** klicken.
5. Die Zahl `365` unverändert lassen.
6. Noch einmal auf den grünen Button **Run workflow** klicken.

Nach einigen Sekunden erscheint ein neuer Workflow-Lauf. Während er läuft, ist das Symbol
gelb. Bei Erfolg wird es grün. Der erste Backfill kann mehrere Minuten dauern.

Dieser Lauf lädt historische Wetterdaten und speichert sie automatisch in deinem
Repository. Du musst sonst nichts tun.

## Schritt 5: Aktuelle Vorhersagen sammeln

1. Bleibe im Bereich **Actions**.
2. Klicke links auf **2 - Collect current forecasts**.
3. Klicke rechts auf **Run workflow**.
4. Bestätige noch einmal mit dem grünen Button **Run workflow**.

Danach sammelt GitHub automatisch alle drei Stunden neue Vorhersagen, METAR- und TAF-Daten.

## Schritt 6: Historische Marktpreise optional nachladen

Dieser Schritt ist nur für die rückwirkende Polymarket-Simulation nötig.

1. Klicke unter **Actions** auf **3 - Backfill historical market prices**.
2. Starte zunächst mit `30` Tagen.
3. Klicke auf **Run workflow**.

Der Lauf speichert historische YES-Handelspreise nahe zwei festen Entscheidungszeitpunkten.
Das sind keine rekonstruierten alten Orderbücher oder Best-Asks; die App kennzeichnet diese
Ergebnisse deshalb ausdrücklich als historische Preissimulation.

## Woran erkennst du, dass es funktioniert?

- Der Workflow erhält ein grünes Häkchen.
- Auf der Startseite des Repositorys erscheint der Ordner `data`.
- Im Ordner `data` liegt anschließend die Datei `weatherman.db`.

Ein rotes Kreuz bedeutet, dass ein Fehler aufgetreten ist. Öffne in diesem Fall den
fehlgeschlagenen Workflow und kopiere die rote Fehlermeldung in den Chat.

## Enthaltene Flughäfen und Modelle

Das **Trading Desk** sammelt die vollständigen Live-Daten für Madrid, Amsterdam,
Warschau, Ankara, Istanbul Airport (LTFM) und München (EDDM). **Airport Research**
führt zusätzlich einen breiten
Katalog internationaler Polymarket-Temperaturstationen und entdeckt neue
Temperaturmarkt-Städte automatisch. Noch nicht zuordenbare Städte bleiben sichtbar als
`station mapping required`, statt still ausgelassen zu werden.

Für das breite Research werden ECMWF, GFS und ICON sowie feste Entscheidungs-Snapshots
verwendet. Die regionalen Modelle, Meteoblue, METAR, TAF und die engmaschige
Polymarket-Preissammlung bleiben auf die aktivierten Trading-Airports begrenzt.

## Neu in Version 6

- Der historische Modellvergleich verwendet einen festen **D-1-Zeitpunkt**. Dadurch werden
  Vorhersagen verglichen, die für jeden Tag aus derselben Entfernung stammen.
- Der **Heat Spike Score** berücksichtigt Modelltrend, Modellübereinstimmung, trockene Luft,
  Bewölkung, Erwärmungsgeschwindigkeit und den Vergleich zwischen METAR und Modellverlauf.
- Sobald ein METAR-Tagesmaximum vorliegt, entfernt das Dashboard alle bereits unmöglichen
  niedrigeren Temperaturbereiche und verteilt die Wahrscheinlichkeiten neu.
- Die Simulation verwendet bei jedem vergangenen Tag nur den Bias, der bis dahin bereits
  bekannt war. Die angezeigten Quoten von 2,0 bleiben eine Testannahme und sind keine echten
  historischen Marktpreise.

Nach einem Update auf Version 6 bitte den Workflow **1 - Initial history backfill** einmal
erneut ausführen. Danach **2 - Collect current forecasts** starten. Das Dashboard übernimmt
die neue Datenbank anschließend automatisch.

## Neu in Version 7

- Das Dashboard findet automatisch die passenden täglichen Polymarket-Temperaturmärkte für
  Madrid, Amsterdam, Warschau und Ankara.
- Im neuen Reiter **Market comparison** stehen unsere Wahrscheinlichkeit, der angezeigte
  Marktwert, das beste Gebot, der aktuelle YES-Kaufpreis und die Modelldifferenz nebeneinander.
- Eine auffällige positive Differenz wird erst ab acht Prozentpunkten markiert. Sie ist ein
  Modellsignal und ausdrücklich keine Gewinnzusage oder automatische Handelsempfehlung.
- GitHub speichert die Marktpreise alle drei Stunden. Damit entsteht ab Version 7 eine echte
  Preishistorie für spätere Auswertungen.
- Neue Ist-Temperaturen werden im normalen Sammel-Workflow automatisch nachgetragen. Ein
  regelmäßiger manueller Backfill ist dafür nicht mehr erforderlich.

Polymarket-Marktdaten sind öffentlich lesbar. Für Version 7 wird kein Polymarket-Key und kein
Wallet-Zugang benötigt. Nach dem Upload reicht es, **2 - Collect current forecasts** einmal
manuell auszuführen. Der Backfill muss beim Update von Version 6 auf Version 7 nicht erneut
gestartet werden.

## Korrektur in Version 7.1

- Ein Fehler einer einzelnen Datenquelle setzt nicht mehr die gesamte Datenbank-Sitzung außer
  Kraft. Nur der betroffene Datenblock wird zurückgesetzt; alle anderen Quellen laufen weiter.
- Oben im Dashboard stehen die letzten Updatezeiten für Forecast, METAR und Polymarket in der
  jeweiligen Flughafen-Ortszeit.
- Der Accuracy-Reiter zeigt verständlich an, ob D0-Morgendaten noch fehlen oder bereits
  gesammelt wurden und nur auf die später verfügbaren Ist-Werte warten.
- Der Polymarket-Reiter unterscheidet zwischen „noch gar keine Marktdaten gesammelt“ und „für
  das ausgewählte Datum wurde noch kein Markt veröffentlicht“.

Nach dem Upload von Version 7.1 nur **2 - Collect current forecasts** einmal ausführen. Ein
erneuter Backfill ist nicht erforderlich.

## Neu in Version 8

- Das Dashboard erkennt nun, ob der Temperaturtag noch läuft oder ob das Tagesmaximum
  praktisch feststeht.
- Dafür werden nicht einfach die Polymarket-Prozente kopiert. Entscheidend sind ein frischer
  METAR-Wert, die Temperaturentwicklung der letzten Stunden, die noch erwartete
  Sonneneinstrahlung und der restliche Temperaturanstieg in den stündlichen Wettermodellen.
- Erst wenn es am Flughafen mindestens 16 Uhr ist, die Temperatur nicht mehr steigt, fast
  keine Sonneneinstrahlung mehr erwartet wird und auch die stündlichen Modelle keine
  nennenswerte Erwärmung zeigen, erhält der Tag den Status **Peak locked**.
- Bei **Peak locked** wird das bereits erreichte METAR-Tagesmaximum mit 100 % angezeigt.
  Unmögliche höhere und niedrigere Temperaturen verschwinden aus der Verteilung.
- Ist der Polymarket-Markt offiziell aufgelöst, übernimmt die Anzeige den offiziellen
  Gewinnerbereich und zeigt **Officially resolved**.
- Für abgeschlossene Temperaturtage werden keine neuen „Possible edge“-Hinweise mehr
  angezeigt. Der Marktvergleich bleibt zur Kontrolle und für die Preishistorie sichtbar.
- Die neue Kennzahl **Model warming left** zeigt, wie viel Erwärmung die vorsichtigste der
  aktuellen stündlichen Modellkurven noch zulässt.

Nach dem Upload von Version 8 nur **2 - Collect current forecasts** einmal ausführen. Ein
erneuter Backfill ist nicht erforderlich. Danach in Streamlit bei Bedarf **Reboot app** oder
**Rerun** wählen.

## Neu in Version 9

- Weatherman führt ab jetzt automatisch ein **Signal-Tagebuch**. Bei jedem Lauf von Workflow 2
  werden die damalige Modellwahrscheinlichkeit, der echte YES-Kaufpreis, die Modelldifferenz
  und der Zeitpunkt gespeichert.
- Als Testsignal zählt weiterhin nur **Possible edge**, also eine Modelldifferenz von mindestens
  acht Prozentpunkten und ein tatsächlich vorhandener YES-Kaufpreis.
- Im neuen Reiter **Tracked performance** wird pro Temperaturbereich nur das erste solche
  Signal als hypothetischer Einsatz von 1 Dollar erfasst.
- Sobald Polymarket den Markt offiziell aufgelöst hat, berechnet das Dashboard Trefferquote,
  Testgewinn oder Testverlust und Rendite.
- Eine Tabelle vergleicht Madrid, Amsterdam, Warschau und Ankara. Dadurch wird mit der Zeit
  sichtbar, an welchen Flughäfen Weatherman am zuverlässigsten arbeitet.
- Es werden keine echten Wetten oder automatischen Käufe ausgeführt. Gebühren, schlechtere
  Ausführungspreise und Liquiditätsgrenzen sind in der Testrechnung nicht enthalten.

Alte v7- und v8-Signale werden bewusst nicht nachträglich rekonstruiert. Sonst könnten später
bekannte Wetterdaten unbemerkt in eine frühere Entscheidung einfließen. Das saubere Tagebuch
beginnt mit dem ersten Sammellauf nach dem v9-Upload.

Nach dem Upload von Version 9 nur **2 - Collect current forecasts** einmal ausführen. Ein
Backfill ist nicht erforderlich. Der Reiter **Tracked performance** füllt sich danach
automatisch; abgeschlossene Ergebnisse erscheinen jeweils nach der offiziellen Marktauflösung.

## Neu in Version 9.1

- Der neue Reiter **Airport analysis** vergleicht die Wetterqualität aller vorhandenen
  Flughäfen über die letzten 30, 90 oder 365 Tage.
- Für jedes Wettermodell stehen Datenmenge, Bias, MAE, RMSE, Treffer auf den exakten
  Temperaturbereich und Treffer innerhalb von ±1 °C in einer verständlichen Scorecard.
- Der **Forecast Score** von 0 bis 100 fasst diese Wetterkennzahlen zusammen. Eine zusätzliche
  Qualitätsangabe zeigt, ob die Datenmenge begrenzt, mittel oder stark ist.
- Das Live-Modell verwendet nun dynamische Gewichte. Modelle mit kleineren, nach der
  Bias-Korrektur verbleibenden Fehlern der letzten 90 Tage erhalten mehr Gewicht. Bei wenigen
  Daten bleiben die Gewichte bewusst näher an einer Gleichverteilung.
- Das gewichtete Ensemble wird ohne Zukunftswissen getestet: Für jeden vergangenen Testtag
  dürfen ausschließlich Ergebnisse älterer Tage verwendet werden.
- **Forecast confidence** berücksichtigt historische Genauigkeit, aktuelle
  Modellübereinstimmung, Datenmenge und Aktualität der Live-Messungen.
- Forecast Score und Trade Score bleiben getrennt. Ein genauer Wetterflughafen ist nicht
  automatisch ein guter Trading-Flughafen.
- Trade Score bleibt unter 10 unabhängig abgeschlossenen Flughafentagen gesperrt. Von 10 bis
  29 Tagen ist er vorläufig, von 30 bis 99 zunehmend belastbar und ab 100 Tagen belastbarer.
- Maximaler Drawdown, tägliche Sharpe-Kennzahl und Wahrscheinlichkeitskalibrierung sind bereits
  vorbereitet, werden aber erst bei ausreichend vielen echten Ergebnissen angezeigt.

Nach dem Upload von Version 9.1 nur **2 - Collect current forecasts** einmal ausführen. Ein
erneuter Backfill ist nicht erforderlich. Danach in Streamlit **Reboot app** oder **Rerun**
wählen.

## Korrektur in Version 9.1.1

- Der Heat-Spike-Score verwendet jetzt Windgeschwindigkeit **und** Windrichtung.
- Wenn verfügbar, hat die aktuelle METAR-Messung Vorrang; sonst wird der Median der aktuellen
  stündlichen Modelle verwendet. Windrichtungen mehrerer Modelle werden zirkulär gemittelt.
- Jeder Flughafen besitzt zunächst vorsichtige warme und kühlende Windsektoren. Beispielsweise
  wird in Amsterdam kontinentaler Ostwind anders bewertet als maritimer Westwind.
- Der Windbeitrag ist auf wenige Scorepunkte und höchstens ±0,4 °C Nowcast-Korrektur begrenzt,
  bis genügend Daten für eine flughafenspezifische Kalibrierung vorhanden sind.
- Die verwendete Windstärke, Richtung und Quelle werden direkt im Heat-Spike-Modul angezeigt.

Nach dem Upload reicht erneut **2 - Collect current forecasts**. Die Datenbank wird automatisch
um die METAR-Windrichtung ergänzt; ein Backfill ist nicht erforderlich.

## Neu in Version 9.2

- Weatherman lädt bei jedem Sammellauf den aktuellen Flughafen-TAF und archiviert Ausgabezeit,
  Gültigkeit, Rohtext, TX/TN sowie die dekodierten `FM`-, `BECMG`-, `TEMPO`- und
  `PROB30/40`-Phasen.
- Das neue Modul **TAF guidance** zeigt eine explizite TX-Höchsttemperatur samt Zeitpunkt,
  Wind und Böen, Bewölkung, Niederschlags- und Gewitterrisiken während des typischen
  Aufheizfensters sowie Änderungen gegenüber dem vorherigen TAF.
- Wettermodelle und TAF bleiben getrennt sichtbar. Bei Übereinstimmung steigt das Vertrauen
  leicht. Bei einem Konflikt wird die Verteilung vor allem breiter; der TAF darf den finalen
  Mittelpunkt höchstens um 0,5 °C verschieben und zählt nie als zusätzliches Wettermodell.
- Aktuelle METAR-Daten haben im Live-Nowcast weiterhin Vorrang vor TAF und Modellen.
- TAF-TX-Fehler werden getrennt nach D-1, D0 morning und Live gespeichert und ausgewertet,
  sobald passende Ist-Temperaturen vorliegen. TAFs ohne TX bleiben als wertvolle
  Bedingungsprognose erhalten, werden aber nicht künstlich als Temperaturvorhersage gewertet.
- Der manuelle Aktualisierungsknopf öffnet die Datenbank anschließend neu, leert den
  Berechnungscache und führt das Dashboard sauber erneut aus. Er meldet ausdrücklich, ob der
  METAR-Zeitstempel vorgerückt ist oder ob die Luftfahrtquelle noch keinen neueren Bericht
  geliefert hat. Ein App-Reboot ist dafür nicht mehr nötig.

Nach dem Upload von Version 9.2 nur **2 - Collect current forecasts** einmal ausführen und im
Dashboard **Rerun** wählen. Ein historischer Backfill ist nicht erforderlich; das unverfälschte
TAF-Archiv wächst ab dem ersten v9.2-Lauf automatisch.

## Neu in Version 9.3

- Solange das Dashboard geöffnet ist, prüft ein leichter Live-Poller die offizielle
  Aviation-Weather-Quelle automatisch alle 60 Sekunden auf einen neuen METAR. TAFs werden in
  diesem Live-Modus alle zehn Minuten geprüft.
- Ein neuer Bericht führt sofort zu einer Neuberechnung des Nowcasts; ein manueller Refresh
  oder App-Reboot ist nicht erforderlich.
- Das Dashboard zeigt den letzten API-Check und den ersten Erkennungszeitpunkt des neuesten
  METAR an.
- Flughafenspezifische Routinezeiten aktivieren kurz vor einem fälligen Bericht den Schutz
  **METAR pending – do not trade**. Bis der neue Bericht tatsächlich vorliegt, werden neue
  Edge-Signale gesperrt.

## Korrektur und Messung in Version 9.3.1

- Der TAF wirkt nur noch über einen einzigen Temperaturpfad und kann den finalen Mittelpunkt
  insgesamt höchstens um ±0,25 °C verschieben. Raw Model Mean, Bias Corrected und METAR
  Conditioned bleiben davon unverändert.
- Ein TAF-TX gilt ausschließlich für sein exaktes Zieldatum. Ist der angegebene TX-Zeitpunkt
  vorbei und die METAR-Reihe fällt, wird sein Temperatureinfluss für diesen Tag auf null
  gesetzt. Der archivierte TX bleibt für die spätere Genauigkeitsmessung erhalten.
- Die Peak-Lock-Logik verankert künftige stündliche Modellpfade am aktuellen METAR und
  vergleicht sie mit dem bereits gemessenen Tagesmaximum. Ein falsches Abendniveau des Modells
  kann das Aufheizfenster dadurch nicht mehr künstlich offen halten.
- Bei einer nahezu sicheren Marktmeinung von mindestens 98 %, die dem Weatherman-Modell um
  mindestens zehn Prozentpunkte widerspricht, erscheint **Market–model conflict**. Der Markt
  verändert die Wetterprognose nicht, blockiert aber vorsorglich neue Edge-Signale.
- Jeder Sammellauf speichert ab jetzt vier getrennte Forecast-Stufen mit identischem
  Zeitstempel: **Raw model mean**, **Bias corrected**, **METAR conditioned** und **Final incl.
  TAF**.
- Der Accuracy-Reiter misst Bias, MAE, RMSE, exakte Bucket-Treffer und Treffer innerhalb
  ±1 °C für jede Stufe getrennt. Live-Ergebnisse werden zusätzlich nach Stunden bis zum
  modellierten Peak aufgeteilt. Als Ist-Wert wird bevorzugt das Tagesmaximum der relevanten
  Flughafen-METARs verwendet; Archivdaten dienen nur als Fallback.

Nach dem Upload von Version 9.3.1 reicht **2 - Collect current forecasts** und einmal
**Rerun**. Die neue Forecast-Ladder beginnt bewusst erst mit diesem Lauf; ältere Zwischenstufen
werden nicht mit später bekannten Daten rekonstruiert. Ein Backfill ist nicht erforderlich.

## Neu in Version 9.4.1

Version 9.4.1 enthält zusätzlich einen CI-Hotfix: Ruff 0.16 aktivierte beim
bisherigen offenen Versionsbereich deutlich strengere Prüfregeln und ließ den
GitHub-Test dadurch trotz funktionierender Anwendung fehlschlagen. Die geprüften
Regeln sind nun explizit konfiguriert, die Ruff-Version ist festgeschrieben und
der Test prüft gezielt die Anwendungsdateien in `app.py`, `src/` und `tests/`.

- Die Forecast-Ladder trennt jetzt sechs Stufen: **Raw model mean**, **Weighted raw
  ensemble**, **Bias corrected · equal weight**, **Bias corrected · performance weighted**,
  **METAR conditioned** und **Final incl. TAF**.
- Der METAR-conditioned Mittelpunkt verwendet konservativ begrenzte Einzelbeiträge aus
  Temperaturabweichung, beobachteter gegenüber modellierter Trockenheit, METAR-Bewölkung,
  beobachteter gegenüber modellierter Erwärmungsrate, jüngstem Stationsfehler,
  Strahlungsproxy, aktuellem Windsektor und Modelllauftrend.
- TAF-Wetterbedingungen bleiben bewusst in der nachgelagerten Stufe **Final incl. TAF**.
  Dadurch lässt sich separat messen, ob der TAF den Live-Nowcast verbessert oder
  verschlechtert.
- Jeder Einzelbeitrag und jedes zugrunde liegende Feature wird pro Snapshot gespeichert und
  im Dashboard angezeigt. Das ermöglicht später eine Walk-forward-Kalibrierung pro Flughafen
  und Zeit bis zum Peak.
- Die abendliche Peak-Lock-Logik akzeptiert klare späte METAR-Abkühlung als Ersatz für eine
  fehlende Strahlungsvariable. Angekerte Modellpfade müssen weiterhin bestätigen, dass der
  nächste Temperatur-Bucket nicht mehr erreichbar ist. Die Anzeige nennt offene Lock-Blocker.
- Lange Desktop-Kennzahlen stehen höchstens zu dritt in einer Zeile und werden nicht mehr in
  fünf schmale Karten gepresst.
- Das Modellbalkendiagramm erhält eine Provenienz-Tabelle. Abrufzeit wird nicht mehr als
  Modelllaufzeit ausgegeben. Meteoblue speichert `modelrun_utc` und
  `modelrun_updatetime_utc`, sofern die API sie liefert; fehlende Open-Meteo-Laufmetadaten
  werden sichtbar als nicht geliefert gekennzeichnet.
- **Tracked performance** enthält zusätzlich „Always-consensus“-Benchmarks. Pro Forecast-Stufe
  und Informationszeitpunkt wird genau der wahrscheinlichste Bucket mit einem hypothetischen
  Einsatz von 1 Dollar verfolgt, auch wenn kein Edge vorliegt.
- Workflow **3 - Backfill historical market prices** ermöglicht eine rückwirkende
  D-1-Preissimulation mit Polymarket-Handelspreisen. Wegen fehlender alter Orderbücher bleibt
  sie methodisch von der höherwertigen Vorwärtsaufzeichnung getrennt.
- Der Accuracy-Reiter rekonstruiert Raw, Weighted Raw und beide Bias-Stufen historisch für D-1
  ohne Zukunftswissen. Live- und TAF-Stufen werden weiterhin nur aus tatsächlich gespeicherten
  Snapshots bewertet.
- Meteoblue erscheint in Airport Analysis und Individual Weather Model Accuracy immer als
  **meteoblue mLM**. Fehlen auswertbare Forecast-Actual-Paare, steht dort sichtbar
  **No scored data**, statt dass die Zeile verschwindet.
- Airport- und Einzelmodell-Scorecards verwenden bevorzugt das tatsächliche
  Flughafen-METAR-Tagesmaximum; Archivwerte bleiben Fallback.
- Erklärungen für MAE gain, RMSE, Market-leading range, Market probability und
  **After median modelled peak** sind direkt im Dashboard enthalten.

Beim Update auf Version 9.4.1 reicht zunächst **2 - Collect current forecasts** und einmal
**Rerun**. Die Datenbank erweitert sich automatisch. Workflow 1 muss nicht erneut laufen,
wenn der bestehende D-1-Backfill vorhanden ist. Workflow 3 ist optional und nur für die
historische Marktpreissimulation erforderlich.

## Neu in Version 9.5

- Die Anwendung ist in zwei Arbeitsbereiche getrennt: **Trading Desk** für den
  ausgewählten Live-Airport und **Airport Research** für alle flughafenübergreifenden
  Auswertungen.
- Das Trading Desk lädt nur noch Daten des ausgewählten Airports. Airport Research
  verwendet einen eigenen 15-Minuten-Cache und berechnet ausschließlich das ausgewählte
  Analysemodul.
- Der Begriff D-1 ist nicht mehr doppeldeutig:
  - **D-1 · 24h lead** ist die standardisierte meteorologische Rekonstruktion mit
    exakt 24 Stunden Vorlauf pro gültiger Modellstunde.
  - **D-1 Evening · 20:00** verwendet den letzten Snapshot, der spätestens um
    20:00 lokaler Airportzeit am Vortag bekannt war.
  - **D0 Morning · 10:00** verwendet den letzten Snapshot, der spätestens um
    10:00 lokaler Airportzeit am Zieltag bekannt war.
  - Ein Snapshot nach dem Cut-off darf niemals rückwirkend verwendet werden. Der
    Abstand des verwendeten Snapshots zum Cut-off bleibt messbar.
- Der neue Workflow **4 - Collect airport research checkpoints** läuft alle 30 Minuten,
  ruft aber nur Airports ab, deren lokaler 20:00- oder 10:00-Cut-off unmittelbar
  bevorsteht.
- Polymarket-Temperaturmarkt-Städte werden automatisch entdeckt und in einem eigenen
  Universe-Verzeichnis gespeichert. Bekannte Städte werden einer Research-Station
  zugeordnet; unbekannte Städte erscheinen als Mapping-Aufgabe.
- **Airport Analysis** enthält das Airport-Leaderboard und vergleicht Sample Size,
  MAE, RMSE, Treffer innerhalb ±1 °C und die exakte Markt-Bucket-Hit-Rate.
  Celsius- und Fahrenheit-Märkte werden
  anhand ihrer jeweiligen Bucket-Breite getrennt behandelt.
- Airport Analysis und Accuracy by Timing sind die Kernmodule der neuen Research-Seite.
  Forecast Stages, Live-Factor Diagnostics, Strategy Performance und Universe/Data
  Coverage sind dort als separat ladbare Module integriert.
- Die eigenständige synthetische **D-1 $1 simulation** wurde entfernt. Standardisierte
  $1-Kennzahlen bleiben in Strategy Performance erhalten: P/L, ROI, Trefferquote,
  Entry-Anzahl und maximaler Drawdown. Tatsächlich vorwärts gespeicherte Asks bleiben
  von historischen Trade-Price-Samples methodisch getrennt.
- Kandidaten-Stationen müssen vor einer Hochstufung zum Trading-Airport gegen die
  offizielle Polymarket-Resolution-Source geprüft werden. Das Dashboard zeigt diesen
  Mapping-Status ausdrücklich an.

### Update von v9.4.1 auf v9.5

1. Den gesamten Inhalt von `UPLOAD_TO_GITHUB` hochladen und vorhandene Dateien ersetzen.
2. **2 - Collect current forecasts** einmal starten.
3. **4 - Collect airport research checkpoints** einmal manuell starten; danach läuft
   dieser Workflow automatisch.
4. **1 - Initial history backfill** mit `365` Tagen erneut starten, damit auch die neu
   aufgenommenen Research-Airports sofort eine historische D-1-24h-Basis erhalten.
5. Streamlit einmal **Rerun** ausführen.

Die bestehende Datenbank und alle v9.4.1-Snapshots bleiben erhalten. Die neue
Universe-Tabelle und alle benötigten Indizes werden automatisch ergänzt.

## Korrektur in Version 9.5.3

Version 9.5.3 ersetzt die bisherigen absoluten Markdown-Links durch interne
Streamlit-Seitenlinks. **Airport Research** öffnet dadurch zuverlässig die
Research-Seite im selben Browser-Tab und fällt auf Streamlit Cloud nicht mehr
auf das Trading Desk zurück. Der laufende Initial History Backfill beeinflusst
nur die Datenabdeckung, nicht die Navigation.

## Performance-Update in Version 9.5.4

- Airport Research lädt nur noch das ausgewählte Analysemodul, den gewählten
  Zeitraum und – bei gesetztem Filter – den relevanten Airport.
- Nicht benötigte Markt-, Strategie-, TAF- und Universe-Tabellen werden beim
  Öffnen von Airport Analysis nicht mehr geladen oder berechnet.
- Der historische Walk-forward-Vergleich verwendet dieselben Regeln wie zuvor,
  vermeidet aber die langsamen vollständigen DataFrame-Scans für jeden einzelnen
  Airport-Tag. Airport Analysis berechnet das Ensemble außerdem nur noch einmal.
- **Accuracy by timing** steht zusätzlich im Trading Desk und wird dort
  ausschließlich für den im Dropdown ausgewählten Airport angezeigt.
- Die in v9.5.3 zusätzlich eingebauten symbolbasierten Seitenlinks wurden entfernt.
  Der Seitenwechsel bleibt über Streamlits native Navigation im selben Browser-Tab.

Für das Update von v9.5.3 auf v9.5.4 ist kein erneuter Backfill und kein manueller
Collect-Workflow erforderlich. Nach dem Upload genügt ein Reboot der Streamlit-App.

## Neu in Version 10

- **Istanbul Airport (LTFM)** und **München (EDDM)** sind vollständige
  Trading-Airports. Forecasts, stündliche Modellpfade, Meteoblue, METAR, TAF,
  Polymarket-Preise und Live-Snapshots laufen durch dieselben Pfade wie bei den
  bisherigen vier Airports.
- Der Temperature Anchor verwendet nicht mehr nur die letzte METAR-Abweichung.
  Er vergleicht bis zu drei aufeinanderfolgende Beobachtungen mit dem stündlichen
  Modellpfad und verstärkt das Re-Anchoring, wenn ein warmer oder kalter Fehler
  wiederholt bestätigt wird.
- Der Anchor wird abhängig vom verbleibenden Heizfenster gewichtet. Drei
  konsistente METAR-Abweichungen können nicht mehr durch mehrere schwächere
  Gegensignale nahezu vollständig neutralisiert werden.
- Ein neues **Failed-Convection-Signal** erkennt vorsichtig, wenn im TAF erwartete
  Gewitter, Niederschläge oder BKN/OVC im kritischen Fenster in den jüngsten
  METARs nicht eintreten.
- Fallende Taupunkte werden als eigenes Dry-Mixing-Signal erfasst.
- Einzelne Modell-Ausreißer werden robust heruntergewichtet, bleiben aber in der
  Verteilung sichtbar. Das Dashboard zeigt den historischen Modell-Weight und den
  zusätzlichen Outlier-Multiplikator getrennt.
- Die **v10 Decision Engine** gibt pro Update **BET**, **WATCH** oder **NO BET**
  aus. BET setzt mindestens acht Prozentpunkte ausführbare Edge, Forecast
  Confidence von 65/100 und einen Spread von höchstens zwölf Prozentpunkten
  voraus. METAR pending, Peak locked und ein harter Markt-Modell-Konflikt sperren
  neue BET-Signale.
- Faire Wahrscheinlichkeit, YES-Ask, Edge und Veränderung seit dem letzten
  gespeicherten Snapshot werden direkt angezeigt.
- Der erste **Hedge Calculator** berechnet für eine vorhandene Position und einen
  zweiten ausgewählten Bucket den Einsatz, der die Bruttoauszahlung dieser beiden
  Ergebnisse ausgleicht. Andere Buckets bleiben ausdrücklich als ungesichertes
  Risiko sichtbar.
- Workflow **5 - Parallel shadow watcher and live decisions** sammelt nur während
  der airportabhängigen kritischen Zeitfenster zusätzliche METAR-, Markt-,
  Decision- und ausführbare Orderbuch-Snapshots.

### Update von v9.5.4 auf v10

1. Falls gerade ein GitHub-Backfill läuft, diesen zuerst fertig werden lassen.
2. Den gesamten Inhalt von `UPLOAD_TO_GITHUB` hochladen und vorhandene Dateien
   ersetzen.
3. Den grünen Test abwarten.
4. **2 - Collect current forecasts** einmal manuell starten.
5. **6 - Backfill Istanbul and Munich** einmal mit `365` Tagen starten. Dieser
   Workflow lädt nur die zwei neuen Trading-Airports und kann unabhängig von der
   App-Nutzung im Hintergrund laufen.
6. Streamlit über **Manage app → Reboot app** neu starten.

Workflow 5 läuft nach dem Upload automatisch. Die vorhandene Datenbank bleibt
erhalten; es ist kein vollständiger neuer 49-Airport-Backfill nötig.

## Neu in Version 10.2

- Der **Parallel Shadow Watcher** läuft im selben Workflow wie die bisherige
  Decision Engine automatisch alle zehn Minuten, aber nur innerhalb des
  jeweiligen kritischen Airport-Fensters.
- Er lädt die öffentliche CLOB-Orderbuchtiefe jedes YES-Buckets und simuliert
  einen sofort ausführbaren **$10-All-in-Paper-Kauf**. Der effektive Preis
  berücksichtigt mehrere Ask-Level, Slippage und die dynamische
  Weather-Taker-Gebühr
  `shares × 0.05 × price × (1 − price)`.
- Eine **SHADOW BET** benötigt nach Gebühren und Slippage noch mindestens fünf
  Prozentpunkte Edge, nachdem zusätzlich zwei Prozentpunkte Sicherheitsabschlag
  abgezogen wurden. Forecast Confidence unter 65, Spread über zwölf Punkte,
  METAR pending, unzureichende Tiefe, veraltetes Orderbuch, Peak Lock oder ein
  harter Markt-Modell-Konflikt verhindern ein Shadow-Bet-Signal.
- Es werden auch WATCH- und NO-BET-Prüfungen gespeichert. So kann später gemessen
  werden, ob eine Netto-Edge wirklich ausführbar war und wie lange sie bestand.
  Der Watcher besitzt keine Wallet-, Login- oder Orderfunktion und kann daher
  keine echte Wette platzieren.
- Der Trading Desk hat einen eigenen Reiter **Shadow watcher**. Strategy
  Performance wertet nach Marktauflösung den ersten gebühren- und
  tiefenbereinigten Shadow-Einstieg je Bucket separat aus.
- Vollständige METAR-Tage werden bereits am Folgetag als
  `metar-provisional`-Actual gelernt. Sobald das verzögerte Archiv verfügbar ist,
  ersetzt es diesen vorläufigen Wert automatisch.
- Das neue **Rapid Heat-Ramp Regime** erkennt schnelle Erwärmung gegenüber den
  letzten ein bis zwei Tagen. Es addiert keinen pauschalen Temperaturwert,
  sondern schwächt nur historisch positive Warmbias-Korrekturen ab, verbreitert
  die Bucket-Verteilung und senkt die Confidence.
- Bei Madrid und München wird ein kohärenter warmer Regionalmodell-Cluster
  während eines Heat Ramps getrennt von einem kälteren Globalmodell-Cluster
  behandelt. Bestätigt ein klarer TAF das Regime, erhalten AROME/AROME-HD,
  ARPEGE beziehungsweise ICON-EU konservativ mehr Gewicht.
- Der neue **Clear-sky override** greift live erst nach mindestens zwei klaren
  METARs. Er korrigiert vorsichtig eine modellierte Wolkenbremse; ein ebenfalls
  klarer TAF verstärkt das Signal.
- Rapid Heat Ramp, Regional Cluster und Clear-sky Override werden mit jedem
  Forecast-Snapshot gespeichert und können später getrennt gegen das tatsächliche
  Maximum geprüft werden.

### Update von v10.1 auf v10.2

1. Den gesamten Inhalt von `UPLOAD_TO_GITHUB` hochladen und vorhandene Dateien
   ersetzen.
2. Den grünen GitHub-Test abwarten.
3. **2 - Collect current forecasts** einmal manuell starten.
4. Streamlit über **Manage app → Reboot app** neu starten.

Workflow 5 startet den Shadow Watcher anschließend automatisch. Es ist kein
neuer Forecast-, Marktpreis- oder Airport-Backfill erforderlich.

## Neu in Version 10.1

- Airport Research zeigt bei München, Istanbul und anderen Airports ohne bereits
  abgerechnete Strategy-Performance-Daten nun eine verständliche Leermeldung,
  statt beim Airport-Filter mit einem `AttributeError` abzubrechen.
- Ein aufklappbarer Erklärbereich grenzt den Fixed-checkpoint
  Top-bucket-Benchmark, den Possible-edge Tracker und die historische
  Preissimulation samt unterschiedlicher Einstiegslogik voneinander ab.
- Für LTAC aktiviert ein beobachtetes Gewitterregime in den letzten 48 Stunden
  nun **Post-Convective Uncertainty**. Es verschiebt die Temperaturprognose
  ausdrücklich nicht, sondern verbreitert die Bucket-Verteilung bis maximal
  1,5-fach und senkt die Forecast Confidence.
- **Late Dry Mixing** ist ein eigenes positives Live-Signal, wenn das
  Modellmaximum früh erreicht wird, der Taupunkt deutlich fällt, CAVOK bzw.
  geringe Bewölkung anhält, der Wind schwach bleibt und noch Heizzeit vorhanden
  ist.
- Der Trading Desk warnt zusätzlich, wenn das beobachtete Maximum die
  Modellobergrenze mit mindestens zwei verbleibenden Stunden im konfigurierten
  Heizfenster erreicht.
- Das kritische Livefenster von Ankara endet nicht mehr um 16:30, sondern um
  **18:30 Uhr lokal beziehungsweise 17:30 Uhr österreichischer Sommerzeit**.
- Die METAR-Sammlung lädt für die sechs Trading-Airports jeweils 48 Stunden,
  damit vorangegangene Gewitter für die Regimeerkennung verfügbar bleiben.

Für dieses Update ist kein Backfill nötig. Nach dem Upload genügt ein Reboot der
Streamlit-App. Falls Workflow 6 nach dem v10.0.1-Fix noch nicht erfolgreich
durchgelaufen ist, kann er anschließend unverändert erneut gestartet werden.

## Korrektur in Version 9.5.2

Version 9.5.2 verschiebt das Streamlit-Startmodul `runtime_bootstrap` in den
installierten `src`-Projektbaum. Damit verwenden Streamlit und GitHub Actions
denselben Importpfad. Der Testlauf hängt nicht mehr von einer zusätzlichen neuen
Datei im Repository-Hauptverzeichnis ab.

## Korrektur in Version 9.5.1

Streamlit kann bei einem Update einzelne Python-Module der vorherigen Version bis
zum nächsten Prozessneustart im Arbeitsspeicher behalten. Dadurch konnte die neue
v9.5-App bereits geladen sein, während `weatherman.settings` noch aus v9.4.1
stammte. Der Start brach dann beim Import von `trading_airports` ab.

Version 9.5.1 erkennt und verwirft solche veralteten Weatherman-Module vor dem
Start. Die neuen Trading-, Research- und City-Mapping-Kataloge sind außerdem in
einem abwärtskompatiblen Modul gekapselt, das nur die bereits in v9.4.1 vorhandene
`airports()`-Funktion voraussetzt. Datenbank und gespeicherte Forecasts bleiben
unverändert.

## Wichtig zum Dashboard

Die GitHub-Workflows sammeln und speichern die Daten. Eine normale GitHub-Seite führt das
interaktive Streamlit-Dashboard nicht dauerhaft aus. Dafür braucht es später noch einen
kostenlosen oder kostenpflichtigen Hosting-Dienst, beispielsweise Streamlit Community
Cloud.

Das ist ein eigener nächster Schritt. Die Datensammlung auf GitHub funktioniert bereits
ohne lokale Installation.
