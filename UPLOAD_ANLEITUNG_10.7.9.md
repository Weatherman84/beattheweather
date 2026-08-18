# Upload-Anleitung v10.7.9

## Empfohlen: schlankes Delta-Paket

Das Delta enthält nur neue oder gegenüber v10.7.8 geänderte Dateien und bleibt unter
dem GitHub-Webupload-Limit von 100 Dateien.

1. ZIP lokal entpacken.
2. Den Inhalt des Ordners `UPLOAD_TO_GITHUB` in das bestehende Repository ziehen.
3. Vorhandene Dateien ersetzen und den Upload committen.
4. Den grünen Test abwarten.
5. Workflow 8, danach Workflow 5 jeweils einmal manuell starten.
6. Streamlit einmal neu booten.

## Fallback

Das Full-Paket ist nur erforderlich, wenn das bestehende Repository unvollständig ist.
Es enthält mehr als 100 Dateien und muss daher gegebenenfalls in mehreren
GitHub-Webupload-Schritten hochgeladen werden.

Ein Forecast-, METAR-, TAF- oder Historical-Replay-Backfill ist nicht erforderlich.
