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

## Wichtig zum Dashboard

Die GitHub-Workflows sammeln und speichern die Daten. Eine normale GitHub-Seite führt das
interaktive Streamlit-Dashboard nicht dauerhaft aus. Dafür braucht es später noch einen
kostenlosen oder kostenpflichtigen Hosting-Dienst, beispielsweise Streamlit Community
Cloud.

Das ist ein eigener nächster Schritt. Die Datensammlung auf GitHub funktioniert bereits
ohne lokale Installation.
