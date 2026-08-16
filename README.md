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

In v10.7.8 ist die speicherintensive **Airport Research**-Navigation im
Produktionsbetrieb deaktiviert. Die sechs Trading-Airports und ihre kompakte
Forecast Ladder History liegen vollständig im Trading Desk. Breites Research und
Historical Replay werden getrennt von Streamlit ausgeführt.

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

Danach übernimmt Workflow 5 als einziger geplanter Datenbank-Writer alle zehn Minuten
das Journaling. Er sammelt METAR und TAF für alle Trading-Airports, reconciliert die
festen Checkpoints und schreibt die Live-Entscheidungsstände. Fällige Modelle werden
über denselben kontrollierten Pfad aktualisiert. Workflow 2 bleibt der manuelle
Vollabruf; Workflow 4 ist nur noch ein manueller Fallback.

Wenn du auf Version 10.7.8 aktualisierst, warte den grünen Test ab und starte danach
einmal **5 - Consolidated ten-minute collector**. Der erste Lauf ergänzt ausschließlich
neue Metadaten-Spalten und lässt die vorhandenen Tabellenzeilen unverändert. Starte
anschließend einmal **8 - Daily archive verification and SQLite maintenance** und boote
Streamlit neu. Workflow 1 und Workflow 7 sind für dieses Update nicht erforderlich.

Der Streamlit-Button **Refresh live trading data** aktualisiert für den ausgewählten
Airport und Zieltag alle unmittelbar entscheidungsrelevanten Daten: konfigurierte
Tagesmodelle und Hourly-Pfade, Meteoblue, METAR, TAF und Polymarket. Die Provider laufen
parallel mit begrenzten Timeouts; historische Backfills, Reanalysis und mehrtägige
Marktschleifen bleiben ausgeschlossen. Der Button startet keinen GitHub-Workflow.
Persistentes Journaling bleibt Aufgabe des kontrollierten GitHub-Collectors.

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

### Korrektur in Version 10.2.1

- Workflow 5 lädt von 06:00 Uhr Flughafenzeit bis zum Ende des kritischen Fensters
  automatisch fällige Modellvorhersagen nach. Der Shadow Watcher rechnet dadurch nicht
  mehr nur mit dem letzten dreistündlichen Forecast-Snapshot.
- Open-Meteo-Modelle werden spätestens nach 30 Minuten erneut abgefragt; meteoblue
  spätestens nach 60 Minuten, um API-Credits kontrolliert zu verwenden.
- Jeder Modellabruf zeigt sein tatsächliches Alter und ob er in den Live-Konsens
  eingegangen ist.
- Modelle mit einem Abrufalter über 90 Minuten werden aus einem ausreichend großen
  frischen Konsens entfernt. Sind weniger als zwei frische Modelle vorhanden, bleiben
  Forecast und Diagnose sichtbar, aber `BET` und `SHADOW BET` werden hart gesperrt.
- Madrids neues **Persistent-Hot-Regime** erkennt die Fortsetzung einer etablierten
  Hitzephase auch dann, wenn der heutige Rohforecast nicht noch weiter über das
  gestrige Maximum steigt. Wiederholte warme Modellfehler, ein sehr heißer Vortag
  sowie TX-/Clear-sky-Unterstützung schwächen in diesem Regime eine kalte
  Biaskorrektur ab und verbreitern den oberen Tail.
- AROME und AROME-HD werden bei Madrid nur innerhalb dieses bestätigten Regimes
  stärker gewichtet. Außerhalb davon bleibt ihre normale historische
  Biaskorrektur aktiv.
- Münchens **Phase-vs.-Amplitude-Erkennung** passt die jüngsten METARs parallel als
  zeitlich vorgezogene Modellkurve und als vertikal verschobenen Temperaturpfad an.
  Erklärt eine Zeitverschiebung den Morgen besser, wird nicht mehr der gesamte
  frühe Wärmevorsprung auf das Tagesmaximum übertragen.
- Amsterdams **Maritime-Advection-Override** erkennt den Wechsel in einen stärker
  werdenden West-/Nordwestsektor zusammen mit einem Temperaturplateau oder Rückgang.
  Positive Heizfaktoren und die verbleibende Erwärmung werden dann begrenzt.
- Istanbuls **Maritime Low-Range Regime** dämpft Anchor-, Heating-Rate- und
  Dryness-Aufschläge bei anhaltend starkem Seewind, kleiner Tagesamplitude und
  frühem Plateau. In diesem stabilen Regime wird die Bucket-Verteilung vorsichtig
  enger.
- Mehrere positive Bucket-Edges desselben Marktes werden zusätzlich als ein
  **Event-level Basket** bewertet: gemeinsame Wahrscheinlichkeit, kombinierte
  Kosten, Netto-Edge und ROI bei nur einer möglichen Auszahlung. `Most likely
  bucket excluded` und ein ausgelassener mittlerer Bucket blockieren ein
  BET-/SHADOW-BASKET-Signal.
- Strategy Performance zählt Basket-Ergebnisse nach unabhängigen abgerechneten
  Airport-Tagen statt nach wiederholten Snapshots. Ankara erhält aufgrund des
  27-°C-Treffers ausdrücklich keine pauschale Temperatur-Aufwärtskorrektur.
- Für jeden aktiven v10.2-/v10.2.1-Faktor wird derselbe Informationsstand parallel
  als **Champion** und als Challenger ohne genau diesen Faktor gespeichert.
  Airport Research vergleicht anschließend MAE, RMSE, Bias, exakten Bucket-Treffer,
  Brier Score, Log Loss, Kalibrierungsfehler, hohe/niedrige Confidence sowie
  Entry-Anzahl, Netto-Edge, Trefferquote, P/L und ROI.
- Die Evidenzstufen werden sichtbar getrennt: unter 10 aktiven Tagen nur
  Einzelfälle, 10–29 erste Tendenz, 30–59 brauchbare Evidenz und ab 60 Tagen
  deutlich belastbarer. Diese parallelen Varianten sammeln erst ab Installation
  vorwärts Daten und werden nicht rückwirkend rekonstruiert.

### Neu in Version 10.3.0 · Regime Memory

- Der Trading Desk zeigt Regime bereits als **PREDICTED**, **WATCH**,
  **CONFIRMED** oder **REJECTED** und erklärt Signale dafür und dagegen.
- Die erklärbare Analogsuche vergleicht Windrichtung/-stärke, Taupunkt und
  Trockenheit, Bewölkung, Erwärmungsrate, Strahlung, verbleibende Modellerwärmung,
  TAF-Einfluss, Zeit bis zum Peak und vorhandene Regimezustände.
- Ein Analogtag darf nur vor dem aktuellen Target-Tag liegen. Pro historischem
  Tag wird der Snapshot mit möglichst gleichem Informationsstand gewählt; das
  spätere Tagesergebnis wird ausschließlich zur nachträglichen Bewertung benutzt.
- Die ähnlichsten Tage werden mit Datum, Ähnlichkeit, damaligem Forecast,
  tatsächlichem Maximum, Residual und den wichtigsten Übereinstimmungen angezeigt.
- Der aus Analogtagen abgeleitete Temperaturimpuls wird robust geschrumpft und
  auf ±1,0 °C begrenzt. Er startet ausschließlich als **Analog Memory Challenger**
  und verändert weder Live-Forecast noch BET-Signal.
- Der Promotion-Gate zählt nur sequenzielle, später abgerechnete OOS-Tage. Vor
  30 Tagen ist eine Promotion technisch gesperrt. Danach müssen zusätzlich MAE,
  Brier Score, exakter Bucket und Bias die Sicherheitsgrenzen bestehen.
- Auch ein bestandenes Gate setzt den Faktor nur auf **ELIGIBLE FOR REVIEW**.
  Der Champion wird erst nach dem ausdrücklichen Schalter
  `REGIME_MEMORY_ALLOW_PROMOTED=true` beeinflusst; Standard bleibt `false`.
- Kandidaten wie **Wind Shift / Air-mass Change** und **Convective Peak Timing**
  werden früh sichtbar und gespeichert, bleiben aber Challenger-only. Damit
  führen einzelne Überraschungen in Madrid, Ankara, Warschau oder München nicht
  automatisch zu dauerhaften Airport-Regeln.
- Workflow 2 und Workflow 5 melden zusätzlich `regime_memory_snapshots`. Die
  Datenbanktabelle wird beim ersten Start automatisch angelegt; kein Backfill ist
  erforderlich und bestehende Daten bleiben erhalten.

Für das Update den gesamten Inhalt von `UPLOAD_TO_GITHUB` hochladen, den grünen Test
abwarten, **2 - Collect current forecasts** einmal manuell starten und Streamlit über
**Manage app → Reboot app** neu starten. Kein Backfill erforderlich.

### Speicher- und Trading-Desk-Hotfix 10.7.8

- Archivpartitionen werden bereits während des Dekomprimierens nach Airport und
  Zeitgrenzen gefiltert. Der reproduzierbare ausgewählte-Airport-Messlauf sank damit
  von rund 777 MB auf 186 MB Peak-RSS; die gleichzeitig gehaltenen Frames sanken von
  29,5 MB auf 4,9 MB.
- Hourly-Pfade, Markt-, Signal-, Shadow-, Basket- und Regime-Ansichten laden im Trading
  Desk nur den ausgewählten Airport und den tatsächlich benötigten Zieltag. Die
  90-Tage-Kalibrierung, vollständigen Actuals, Regime-Memory- und OOS-Daten bleiben
  erhalten; die Modelllogik wird nicht durch kurzes Abschneiden der Historie verändert.
- Airport Research ist aus der produktiven Navigation entfernt und als leichte
  Offline-Hinweisseite abgesichert. Replay und breite Research-Abfragen laufen nicht
  bei normalen Streamlit-Reruns.
- Forecast Ladder History zeigt je Airport und Tag finale Actuals, D-1, D0@06, D0@10
  und den ersten Live-Stand mit Raw/Bias/METAR/Champion, signierten Fehlern,
  Evidenz/Freshness/Quellalter sowie Bias/MAE/N. Zeitraum, reguläre OOS-Evidenz und
  rekonstruierte Tage sind filterbar.
- Checkpoint-Provenance trennt `expected`, alle kausal `available` und tatsächlich
  `used by Champion`. Fremdmodelle können Coverage nicht mehr über 100 % treiben und
  verschlechtern nicht mehr die Freshness der erwarteten Modellmenge.
- Der Cadence-Bericht zeigt Median/P95-Laufzeit, Trigger- und Queue-Verzögerung. Bei der
  aktuellen Messung sind kurze Ausführungszeiten und praktisch keine Concurrency-Queue
  sichtbar; die fehlende Cadence entsteht an der GitHub-Schedule-Dispatch-Grenze. GitHub
  veröffentlicht keine Ursache für nicht erzeugte Cron-Events.

Es gibt keine produktive Forecast-, Bias-, Gewichts-, Regime-, Day-Lock-, TAF-,
Promotion- oder Trading-Gate-Änderung. Der 30-Tage-Replay-Pilot bleibt ein separater
zweiter Schritt. Details und Rollback stehen in `VERSION_HANDOFF_10.7.8.md`.

### Stabilitäts- und Research-Update 10.7.7

- Workflow 5 bleibt der einzige geplante Datenbank-Writer. Providerabrufe laufen jetzt
  mit begrenzter Parallelität und kurzen Live-Timeouts; alle SQLite-Schreibvorgänge bleiben
  seriell. Die einmalige Madrid-TAF-Reparatur läuft nicht mehr bei jedem Collector-Start.
- Der Cron liegt auf `:07/:17/:27/:37/:47/:57`, um die Lastspitze zur vollen Stunde zu
  vermeiden. Das ist eine Entlastung, aber keine Zehn-Minuten-Garantie von GitHub Actions.
- Jeder neue Lauf trennt Soll-Slot, Event-Erstellung, Queue-Start, Python-Start und Ende.
  Provider- und Airport-Laufzeiten, Retries, Status und fehlende Slots werden im
  Coverage-Bericht ausgewiesen.
- Neue feste Checkpoints speichern verwendeten Forecast-Lauf, Verfügbarkeits- und
  Abrufzeit, konservatives Quellalter, Coverage, Freshness und Evidenzklasse. `scheduled`,
  `reconstructed-causal` und `unavailable` bleiben eindeutig getrennt; historische
  Verfügbarkeit richtet sich weiterhin nach `available_at`.
- Finale Stations-Actuals können nicht durch provisorische oder Archivwerte ersetzt
  werden. Provisorische Actuals zählen nicht für OOS-Promotionen. Raw- und
  Champion-Wahrscheinlichkeit müssen bei neuen Shadow-Zeilen vollständig getrennt sein.
- Peak-Lock-Ablation und Replay-Readiness sind reine Research-Berichte. Sie schreiben
  weder Produktionsdaten noch OOS-Zähler, Promotionen oder Engine-Konfiguration.

Für die beiden Research-Berichte sind optional diese rein lesenden Befehle verfügbar:

```bash
python -m weatherman.cli research-peak-lock
python -m weatherman.cli replay-readiness
```

Es gibt keine produktive Forecast-, Bias-, Gewichts-, Regime-, Day-Lock- oder
Trading-Gate-Änderung. Details, Tests und Rollback stehen in
`VERSION_HANDOFF_10.7.7.md`.

### Korrektur in Version 10.7.4 · finale Actuals, echte 10-Minuten-Cadence und Lineage

- Finale `stored-metar-station`-Tagesmaxima sind jetzt qualitätsgeschützt. Ein rollendes
  `metar-provisional` kann einen bereits finalen Wert weder überschreiben noch absenken.
  Bei jedem Collector-Lauf werden die letzten sieben abgeschlossenen Lokaltage aus dem
  vorhandenen METAR-Archiv erneut geprüft und bei Bedarf selbstheilend repariert.
- Der zehnminütige Collector führt nur noch den zeitkritischen Sammelpfad und einen
  schnellen Coverage-Check aus. Vollständige Archivvalidierung, Retention und SQLite-
  Maintenance laufen einmal täglich in Workflow 8. Historische Gaps bleiben sichtbar,
  werden aber nicht mehr als aktueller Ausfall ausgegeben.
- Shadow Research trennt jetzt `Raw model probability` und `Champion probability`.
  Jede Zeile zeigt Zieltag, tatsächliche lokale Capture-Zeit, Forecast-Snapshot,
  Information Set, ausführbaren Preis, Kosten, Netto-Gap und Blocker. Edge und Trading
  bleiben ausdrücklich Research-only.
- Forecast-Snapshots journalisieren den Pre-TAF- und Champion-Modal-Bucket sowie einen
  TAF-Modal-Bucket-Flip. D-2, D-1, D0 morning und D0 live werden getrennt gespeichert.
- Ein neuer Madrid-Phase-/CAVOK-/Radiation-Guard wird ausschließlich als Challenger
  mitgeloggt. Er ändert weder Champion noch produktiven Anchor.
- Tests mit temporären oder In-Memory-Datenbanken lesen nicht mehr versehentlich das
  lokale Produktionsarchiv. Der explizite Archivpfad bleibt vollständig unterstützt.
- Champion-Gewichte, Biaswerte, Madrids produktiver Anchor, AROME-Gewichtung,
  Persistent-Hot/Day-Lock, feste Uplifts und das 30-OOS-Gate bleiben unverändert.

Für das Update den gesamten Inhalt hochladen, den grünen Test abwarten, Workflow 5 und
danach Workflow 8 je einmal manuell starten und Streamlit neu booten. Workflow 1 und 7
sind nicht erneut erforderlich. Die Prüfpunkte stehen in `VERSION_HANDOFF_10.7.4.md`.

### Neu in Version 10.7.3 · Stage-1 Reliability und eindeutige Live-Anzeige

- Die aktive SQLite-Datei hält standardmäßig nur noch drei Tage Live-Daten. Alte
  append-only Tabellen werden zuerst auf einer Datenbankkopie in verifizierte,
  deterministische Tagespartitionen verschoben und erst nach Row-count-, Zeitbereich-,
  Schema-, Schlüssel-, Hash- und Roundtrip-Prüfung aus der Kopie entfernt.
- Trading Desk, Airport Research, Accuracy und TAF-Auswertung lesen über eine gemeinsame
  deduplizierende `archive + live`-Schicht. Live-Zeilen gewinnen bei einem Überlapp;
  bekannte Zeitpunkte und Backfills bleiben kausal getrennt.
- Workflow 5 ist der einzige geplante zehnminütige Collector. Jeder Lauf protokolliert
  Sollzeit, Start/Ende, Quellenstatus, Datenalter, Zeilen, Fehlergrund und Persistenzstatus.
  Die App zeigt Coverage-, Latenz-, Checkpoint- und Archivwarnungen sichtbar an.
- Jede offizielle TAF-Revision bleibt anhand ihres Content-Hashes unveränderlich erhalten.
  Der bekannte Madrid-Lauf `LEMD 101100Z ... TX38/1016Z` kann gezielt nachgeladen werden;
  seine spätere Abrufzeit darf frühere Weatherman-Checkpoints nicht umschreiben.
- Ein einmal gesetzter terminaler Peak-/Day-Lock bleibt am selben Flughafen-Lokaldatum
  monoton. Der EPWA-Nachtverlauf ist als Regressionstest abgedeckt.
- In **Moisture, cloud & radiation** stehen beobachteter Taupunkt und
  Temperatur–Taupunkt-Spread jetzt getrennt. `Champion expected maximum`, Zentrum vor
  Bucket-Konditionierung, finaler Verteilungsmittelwert und Modal-Bucket werden nicht mehr
  miteinander vermischt. Die Bucket-Spalte heißt eindeutig
  `Uncalibrated Champion probability`.
- Der einmalige Workflow **7 - Recover Stage-1 gaps (10/11 August)** klassifiziert jedes
  Ergebnis als Provider-Historie, kausale Rekonstruktion oder nicht wiederherstellbare
  ursprüngliche Live-Lücke.
- Madrids Anchor, Champion-Gewichte und Biaswerte, allgemeine Day-Lock-Schwellen,
  30-OOS-Tage-Promotion-Gate, Challenger-Promotion sowie Edge-/Wettlogik sind unverändert.

Für das Update den gesamten Inhalt hochladen, den grünen Test abwarten, Workflow 7 einmal
starten, danach Workflow 5 einmal manuell als Collector-Smoke-Test ausführen und Streamlit
neu booten. Workflow 1 ist nicht erneut erforderlich. Die produktiven 24-Stunden- und
7-Tage-Prüfpunkte stehen in `VERSION_HANDOFF_10.7.3.md`.

### Neu in Version 10.7.2 · zuverlässige Checkpoints und Post-Peak-Journaling

- D-1@20, D0@06 und D0@10 werden am exakten lokalen Cut-off gespeichert.
- Verpasste Checkpoints werden bis zu 48 Stunden später ausschließlich aus Daten
  rekonstruiert, deren Verfügbarkeit vor dem Cut-off belegt ist.
- Jeder Checkpoint speichert Quelle, Modelllauf, Verfügbarkeits- und Fetch-Zeit,
  Datenalter sowie Rekonstruktionsstatus; die Vollständigkeit ist in Trading Desk
  und Airport Research sichtbar.
- Der zehnminütige Live-Workflow reconciliert zuerst feste Checkpoints. Workflow 4
  bleibt als manueller Fallback und konkurriert nicht mehr als eigener Zeitplan um
  den Datenbank-Writer.
- Jeder neue spätere METAR schreibt auch außerhalb des Tradingfensters einen neuen
  Forecast-, Varianten- und Regime-Snapshot bis zum konfigurierten Tagesende;
  identische Reports werden nicht doppelt journalisiert.
- Research-only: kombinierte Wind-/Maritime-Ablation für Amsterdam,
  Post-Peak-Upper-Tail-Challenger sowie getrennte Raw-/Weight-/Bias-Diagnostik für
  München und Istanbul. Keine dieser Varianten verändert den Champion.
- Madrids Anchor, Champion-Regimegewichte, Promotion-Gates und Wettlogik bleiben
  unverändert.

### Neu in Version 10.7.1 · Amsterdam-Regime-Fix

- Post-Convective Uncertainty und Rapid Heat Ramp werden wieder als voneinander
  unabhängige Regimezustände ausgewertet.
- Amsterdam kann dadurch auch bei aktiver Konvektionsunsicherheit ohne Heat-Ramp
  fehlerfrei dargestellt werden.
- Rapid Heat Ramp wird umgekehrt auch ohne gleichzeitige Konvektionsunsicherheit
  korrekt im Regime Memory angezeigt.
- Zwei Regressionstests sichern beide Pfade dauerhaft ab. Kein Backfill erforderlich.

### Neu in Version 10.7.0 · globale kontinuierliche Regimes und Anchor-OOS-Lernen

- Alle sechs Trading-Airports verwenden dieselbe Regime-Architektur. Rapid Heat Ramp,
  Persistent Hot, Phase-vs.-Amplitude und beobachtete Konvektionsunsicherheit werden an
  jedem Checkpoint als kontinuierliche Evidenz von 0–100 % berechnet. Airport-spezifische
  Schwellenwerte bleiben erhalten.
- Maritime Regimes werden nur dort als anwendbar markiert, wo ein fachlich definierter
  Seewindsektor vorhanden ist. Fehlende/stale Daten, Day Lock und strenge Richtungs-Gates
  bleiben binäre Sicherheitsbedingungen.
- Regimewirkungen auf Bias, Modellgewichte, Center, Spread und Confidence wachsen
  proportional zur Evidenz. Dadurch entsteht kein plötzlicher voller Regimesprung beim
  ersten Journal-Checkpoint.
- Der Trading Desk zeigt für jedes Regime explizit Anwendbarkeit, Evidenzstärke, Status
  und mögliche Champion-Rolle – auch bei 0 % Evidenz.
- Ein neuer **Airport Anchor Transfer Challenger** lernt ausschließlich aus früheren
  abgeschlossenen Airport-Tagen, wie viel eines METAR-/Modellpfad-Residuals bis zum
  Tagesmaximum bestehen bleibt. Pro Tag zählt höchstens ein vergleichbarer Checkpoint;
  Abstand zum Peak und Residual-Persistenz werden berücksichtigt.
- Der gelernte Anchor wird stark zum konservativen peakabhängigen Standard geschrumpft.
  Er bleibt zunächst Research-only und darf erst nach mindestens 30 echten OOS-Tagen
  samt MAE-, Brier-, Exact-Bucket-, Bias- und Recent-Performance-Gates automatisch in
  den Champion einfließen. Dieselben Gates sorgen für den automatischen Rollback.
- **Accuracy by timing** enthält einen strikt gepaarten Vergleich derselben Stationstage:
  D-1@20:00, D0@10:00 vor Live-Faktoren, D0@10:00 nur mit Anchor und vollständiger
  D0-Nowcast. Damit ist direkt messbar, ob der Morning Anchor oder ein anderer Live-Faktor
  D0 gegenüber D-1 verbessert oder verschlechtert.
- Die bestehenden D-1-METAR-Prioritäten, Modelllauf-Provenienz und Stundenarchive aus
  v10.6.0/v10.5.2 bleiben unverändert erhalten. Kein Backfill ist erforderlich.

Für das Update den gesamten Inhalt hochladen, den grünen Test abwarten, Workflow 2 einmal
starten und Streamlit anschließend neu booten.

### Neu in Version 10.6.0 · belastbare D-1- und Nowcast-Diagnostik

- **Advanced Diagnostics → Model maxima** zeigt für jedes Modell immer den lokalen
  Modelllauf, die lokale Provider-Verfügbarkeit und den tatsächlichen Abrufzeitpunkt.
  Damit sind unterschiedliche Anbieterstände und verspätete Abrufe direkt sichtbar.
- Die Open-Meteo-Modellmetadaten werden separat geladen. Ein Abrufzeitpunkt wird nicht
  mehr ersatzweise als Modelllauf ausgegeben; unbestätigte Herkunft bleibt ausdrücklich
  gekennzeichnet.
- Die D-1-Auswertung verwendet je Modell und Zieltag einen festen Informationsstand bis
  20:00 Uhr lokaler Zeit. Spätere D0-Läufe können die gemessene D-1-Güte nicht mehr
  nachträglich verfälschen.
- Vollständige Flughafen-METAR-Tagesmaxima werden aus den gespeicherten Beobachtungen
  automatisch rekonstruiert und dauerhaft gegenüber gridded Open-Meteo-Reanalysen
  bevorzugt. Sobald mindestens fünf Stationstage vorliegen, kalibrieren sie D-1-Bias
  und Modellgewichte; kleine Stichproben werden stark gegen null geschrumpft.
- Der frühe Temperature Anchor behandelt eine morgendliche Abweichung zuerst als
  mögliche Phasenverschiebung des Erwärmungspfads. Mehr als sechs Stunden vor dem Peak
  wirken nur 12 %, vier bis sechs Stunden 20 %, zwei bis vier Stunden 38 % und erst
  näher am Peak 62 % des persistenten Residuals auf das Tagesmaximum.
- `Persistent Hot` ist kein binärer Sprung mehr. Vortagshitze, Forecast-Fortsetzung,
  wiederholter Stationsbias, TAF und klare Bedingungen ergeben einen kontinuierlichen
  Evidenzwert; Bias-, Spread- und Regionalgewicht wachsen graduell mit der Evidenz.
- Ein zusätzlicher früher Regime-Memory-Checkpoint läuft um 06:00 Uhr lokal. Die UI
  bezeichnet die erste gespeicherte Bewertung nun korrekt als Journal-Checkpoint und
  nicht als ersten technisch möglichen Erkennungszeitpunkt.
- Eine neue Explainability-Ansicht listet offen, was in den Champion einfließt und was
  nur Research-/Archivmaterial ist. Die vollständigen Archive bleiben für Replay und
  Challenger-Tests erhalten, wirken aber nicht ungeprüft direkt auf den Live-Nowcast.

Kein Backfill erforderlich. Beim nächsten Collector-Lauf werden bereits gespeicherte
vollständige METAR-Tage automatisch als stationsbasierte Actuals wiederhergestellt.

### Korrektur in Version 10.5.2 · verlustfreies Stundenarchiv

- Die durch den ersten v10.5.1-Lauf entfernten Stundenpfade wurden aus der letzten
  vollständigen Git-Version wiederhergestellt: 144.215 Zeilen vom 19. Juli bis
  3. August 2026, verteilt auf 16 deduplizierte Tagesarchive.
- Die Archive enthalten Temperatur, Taupunkt, Bewölkung, Windgeschwindigkeit und
  -richtung, Strahlung sowie 850-hPa-Temperatur für jeden gespeicherten Modellpfad.
- Vor jeder künftigen 7-Tage-Bereinigung werden auslaufende Live-Zeilen atomar in
  `data/hourly_archive` geschrieben, erneut eingelesen und geprüft. Erst danach darf
  SQLite sie löschen. Ein beschädigtes Archiv stoppt die Bereinigung.
- `load_hourly_history` verbindet Archiv und Live-Datenbank automatisch und entfernt
  Überschneidungen über Airport, Modell, Lauf- und Gültigkeitszeit. Die Nowcast-Forschung
  sieht dadurch eine durchgehende Historie, während SQLite klein bleibt.
- Ein deterministisches Manifest protokolliert je Tagesdatei Zeilenzahl, Zeitraum,
  Dateigröße und SHA-256-Prüfsumme. Jeder Datenbank-Workflow validiert es automatisch.
- Der bestehende Analog-Memory-Challenger darf nach mindestens 30 echten OOS-Tagen
  automatisch zum Forecast-Champion beitragen, aber nur wenn MAE, Brier Score, exakter
  Bucket und Bias die Gates bestehen und auch die letzten zehn Tage stabil bleiben.
  Verschlechtert sich dieses jüngste Fenster, erfolgt der Rollback automatisch.
- Die Edge-Engine bleibt davon vollständig getrennt und weiterhin standardmäßig
  `RESEARCH ONLY`; eine Forecast-Promotion aktiviert keine Wetten.

Für dieses Update ist weder ein Backfill noch eine manuelle Wiederherstellung oder
Promotion nötig. Den gesamten Inhalt hochladen, den grünen Test abwarten, Workflow 2
einmal starten und danach die Streamlit-App neu booten.

### Korrektur in Version 10.5.1 · GitHub-Datenbanklimit

- Rohe stündliche Modellpfade werden rollierend auf die letzten sieben UTC-Lauftage
  begrenzt. Historische Tagesforecasts, Actuals, METARs, Marktpreise, Signal- und
  Strategy-Historie sowie Forecast-/Challenger-Snapshots bleiben vollständig erhalten.
- Vier redundante Einzelindizes der Stundenprognosen werden entfernt. Der vorhandene
  zusammengesetzte Unique-Index deckt die tatsächlich verwendeten Airport-Abfragen und
  Upserts bereits ab.
- Nach einer notwendigen Bereinigung wird SQLite mit `VACUUM` kompakt geschrieben.
- Vor jedem Datenbank-Commit greift eine 95-MiB-Sicherheitsgrenze, damit GitHub keinen
  unpushbaren Commit über seinem harten 100-MiB-Limit erhält.
- Ein Push-Fehler wird nur noch dann als Race behandelt, wenn `main` wirklich parallel
  weitergelaufen ist. Größen-, Netzwerk- oder Berechtigungsfehler starten den teuren
  Collector nicht mehr fälschlich ein zweites Mal.

Für das Update den gesamten Inhalt hochladen. Danach **2 - Collect current forecasts**
einmal manuell starten; dieser erste Lauf bereinigt und verkleinert die bestehende
Datenbank automatisch. Ein neuer Backfill ist nicht nötig.

### Neu in Version 10.5.0 · Kalibrierungsbremse und Tagesanalyse 3. August

- Die Edge-Engine ist standardmäßig **RESEARCH ONLY**. `EDGE_RECOMMENDATIONS_ENABLED`
  bleibt auf `false`, bis eine Out-of-sample-Kalibrierung der Modellwahrscheinlichkeiten
  bestanden ist. Rohe Modellwahrscheinlichkeit und Modell–Markt-Abstand werden nicht mehr
  als `fair probability` beziehungsweise `executable edge` bezeichnet.
- Nicht wahrscheinlichste Polymarket-Buckets, YES-Asks bis einschließlich 5 Cent und
  Modell–Markt-Abstände ab 15 Prozentpunkten sind hart blockiert. Große Abstände heißen
  **Market-model conflict**, nicht „besonders attraktive Edge“.
- `Best actionable edge` berücksichtigt nur tatsächlich freigegebene Zeilen. Sind alle
  Zeilen blockiert oder Research-only, erscheint **No actionable edge**.
- `Most likely exact temperature` und `Most likely Polymarket bucket` werden getrennt
  angezeigt. Ein offener Rand-Bucket kann mehrere Einzeltemperaturen summieren und daher
  wahrscheinlicher sein als der modalste einzelne Gradwert.
- Im Historical Analog Challenger heißt `Forecast` nun **Historical Champion**.
- Madrid verwendet `Persistent Hot` nur noch mit einem vollständigen, frischen Vortag.
  Ein deutlich kühlerer neuer Modellkonsens ist eine Pflichtbremse. Fehlt `daily_actuals`,
  rekonstruiert der Nowcast einen ausreichend vollständigen Vortageshöchstwert aus bereits
  gespeicherten METARs. Eine langsame, aber modellkonforme Erwärmung wird nicht künstlich
  abgestraft; eine echte Abweichung vom Stundenpfad bleibt maßgeblich.
- Amsterdam, Warschau und München erhalten airport-spezifische Obergrenzen für positive
  Live-Aufschläge. Negative Kühlungsinformationen bleiben dabei unverändert erhalten.
- München erhält einen **Recent Warm-Bias Challenger**. Er benötigt mindestens drei warme
  stationsspezifische Restfehler sowie klares TAF, warme 850-hPa-Luft, hohe Strahlung und
  fehlende Konvektion. Er bleibt Research-only und verändert den Champion nicht.

Kein Backfill erforderlich. Nach dem Upload den grünen Test abwarten, Workflow 2 einmal
manuell starten und Streamlit über **Manage app → Reboot app** neu starten.

### Neu in Version 10.4.1 · Safety Guards aus der Tagesanalyse

- Workflow 5 sammelt die METARs aller Trading-Airports nach Ende des Tradingfensters
  weiter bis **21:35 Uhr lokal**. Dieser METAR-only-Zweig lädt keine Marktpreise und
  erzeugt keine neuen Trades; er aktualisiert jedoch das Tagesmaximum und den
  aktuellen METAR-Actual-Stand.
- Der **Pre-METAR Guard** beginnt nun sieben Minuten vor jedem konfigurierten
  Routinebericht und bleibt aktiv, bis der Bericht tatsächlich eingetroffen ist.
  Währenddessen sind BET und SHADOW BET hart gesperrt.
- Schließt ein positiver Edge-Basket den wahrscheinlichsten Bucket oder einen
  inneren Bucket aus, blockiert der **Basket Integrity Guard** nun auch sämtliche
  zugehörigen Einzelwetten. Sie werden weiterhin für die Diagnose gespeichert,
  aber ausdrücklich als `NO BET`.
- München erhält einen **Cloud-Clearance Reheating Challenger** auch ohne vorherigen
  Regen. BKN/OVC → Aufklaren muss mit verbleibender Modellerwärmung, Strahlung und
  Peakzeit zusammenpassen. Der Challenger verändert den Champion nicht.
- Amsterdam begrenzt die gemeinsame positive Wirkung überlappender Signale aus
  klarem Himmel, Trockenheit, Strahlung und Late Dry Mixing auf **+0,35 °C**. Die
  einzelnen Beiträge bleiben nachvollziehbar, werden aber proportional gedämpft.
- Münchens **Phase vs. Amplitude** verändert das Forecastzentrum erst nach stärkerer
  Bestätigung. Bei einem vorläufigen Phase-Fit bleiben Zentrum und Champion-Anker
  erhalten; stattdessen steigen Spread und Unsicherheit und die Confidence sinkt.

Kein Backfill erforderlich. Nach dem Upload den grünen Test abwarten, Workflow 2
einmal manuell starten und Streamlit über **Manage app → Reboot app** neu starten.

### Neu in Version 10.4.0 · aufgeräumter Live Forecast

- Der Live Forecast folgt nun drei klaren Ebenen: **Trading Cockpit**, **Forecast
  Drivers** und standardmäßig eingeklappte technische Diagnostik.
- Ganz oben stehen nur Recommendation, ausgewählter Bucket, Weatherman-
  Wahrscheinlichkeit, YES-Ask, ausführbare Edge, Confidence und der wichtigste
  Blocker. Die vollständige Entscheidungsbegründung ist aufklappbar.
- Die eindeutige Forecast-Kette lautet **Weighted models → Bias / regime base →
  Live weather adjusted → Champion forecast**. `Champion forecast` ist der aktuelle
  finale Forecast inklusive TAF und nicht das spätere Outcome.
- Nach Tagesabschluss erscheint das tatsächliche Maximum separat als **Outcome**
  mit Gewinner-Bucket und Champion-Fehler.
- Weatherman- und Marktwerte stehen in einer gemeinsamen, auf die fünf wichtigsten
  Buckets reduzierten Tabelle. Die komplette Verteilung bleibt aufklappbar.
- Die neue zentrale Tabelle **Forecast Drivers** bündelt Modelle/Bias, METAR-Pfad,
  Feuchte/Wolken, Wind, TAF, aktive Live-Regime, Future Outlook, historische
  Analog-Challenger und Tagesgrenzen samt konkreter Wirkung.
- `Learned Analog Pattern` wird nicht länger wie ein aktives Live-Regime präsentiert.
  Es heißt nun **Historical Analog Challenger · research only** und zeigt ausdrücklich
  `Live +0.00 °C`, solange es nicht nach OOS-Prüfung freigegeben wurde.
- Die frühere Heat-Spike-Tabelle und die lange Stored-Feature-Liste sind aus der
  normalen Trading-Ansicht verschwunden. Beide bleiben ausschließlich unter
  **Advanced diagnostics** erhalten.
- TAF-Timing erkennt nun ausdrücklich die zukünftige Abfolge **Schauer/Regen endet →
  Wolken brechen auf**. Stimmen zusätzlich verankerte Modellerwärmung, künftige
  Strahlung und Zeit bis zum Peak, wird ein **Post-Rain Reheating Challenger**
  gespeichert. Er ist zunächst research-only und verändert den Champion nicht.
- Alle datenbankschreibenden Workflows checken beim tatsächlichen Start den neuesten
  `main`-Stand aus. Ändert sich `main` dennoch während eines Laufs, wird der Collector
  automatisch auf der neuesten SQLite-Datenbank erneut ausgeführt; binäre Datenbanken
  werden nicht mehr per `git pull --rebase` zusammengeführt.

Für das Update ist kein Backfill nötig. Nach dem Upload den grünen Test abwarten,
**2 - Collect current forecasts** einmal manuell starten und Streamlit über
**Manage app → Reboot app** neu starten.

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
