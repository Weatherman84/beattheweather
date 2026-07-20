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

Danach sammelt GitHub automatisch alle drei Stunden neue Vorhersagen und METAR-Daten.

## Woran erkennst du, dass es funktioniert?

- Der Workflow erhält ein grünes Häkchen.
- Auf der Startseite des Repositorys erscheint der Ordner `data`.
- Im Ordner `data` liegt anschließend die Datei `weatherman.db`.

Ein rotes Kreuz bedeutet, dass ein Fehler aufgetreten ist. Öffne in diesem Fall den
fehlgeschlagenen Workflow und kopiere die rote Fehlermeldung in den Chat.

## Enthaltene Flughäfen und Modelle

Das Projekt sammelt Daten für Madrid, Amsterdam, Warschau und Ankara. Verglichen werden
ECMWF, GFS, ICON, UKMO, ARPEGE, verfügbare AROME/HARMONIE-Modelle sowie optional
Meteoblue.

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

## Wichtig zum Dashboard

Die GitHub-Workflows sammeln und speichern die Daten. Eine normale GitHub-Seite führt das
interaktive Streamlit-Dashboard nicht dauerhaft aus. Dafür braucht es später noch einen
kostenlosen oder kostenpflichtigen Hosting-Dienst, beispielsweise Streamlit Community
Cloud.

Das ist ein eigener nächster Schritt. Die Datensammlung auf GitHub funktioniert bereits
ohne lokale Installation.
