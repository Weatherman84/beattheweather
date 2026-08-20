# Upload-Anleitung v10.7.10

1. Das Delta-ZIP lokal entpacken.
2. Den Inhalt des Ordners `UPLOAD_TO_GITHUB` in das Repository hochladen und vorhandene
   Dateien ersetzen. Das Paket enthält weniger als 100 Dateien.
3. **Keine ältere `data/weatherman.db` hochladen.** Das Delta enthält absichtlich keine
   Produktionsdatenbank und überschreibt daher den laufenden Collector-Stand nicht.
4. Den automatischen GitHub-Test vollständig grün abwarten.
5. Workflow **8 - Daily archive verification and SQLite maintenance** einmal manuell
   starten und grün abwarten.
6. Workflow **5 - Consolidated ten-minute collector** einmal manuell starten und grün
   abwarten.
7. Streamlit unter **Manage app → Reboot app** genau einmal neu starten.
8. In der App prüfen:
   - Version 10.7.10;
   - Overview und Airport-Detail zeigen denselben aktuellen Champion;
   - stale Meteoblue steht auf excluded und niemals auf used;
   - bei weniger als zwei frischen Modellen bleibt Trading gesperrt;
   - Collector-/Coverage-Ansicht zeigt den neuen Lauf.

Ein Forecast-, METAR-, TAF- oder Markt-Backfill ist nicht erforderlich. Der historische
Repair für den 16. und 17. August ist bereits als komprimierte Tagesarchive im Delta
enthalten.

