# Versions-Handoff – Weatherman v10.7.10

## Ausgangsbasis

- Öffentliche Version: v10.7.9.1
- Geprüfter Entwicklungsstand: `e845f55b3cb2cee8c7fec7b0e67ef6a4c45b8d8d`
- Research-Handoffs: 19. und 20. August 2026

## Produktiv behoben

### Stale-Source-Schutz

- Stale Modelle werden niemals als Champion-Input verwendet.
- Der frühere Rückfall auf alle Modelle bei weniger als zwei frischen Quellen ist entfernt.
- Null frische Modelle ergeben keinen Live-Champion.
- Ein frisches Modell bleibt eine diagnostische, handelsgesperrte Vorschau.
- Expected, available, fresh und used werden getrennt gespeichert.

### Verlustsichere Archivierung

- Schwellenbedingte Maintenance im schnellen Collector setzt `maintenance_ran=1`.
- SQLite und neue Archivpartitionen werden gemeinsam gestaged und committed.
- Verbleiben ungestagte Archivänderungen, bricht der Persistenzvorgang vor dem Commit ab.
- Die Datenbank wird weiterhin erst nach erfolgreicher Archiv- und SQLite-Prüfung ersetzt.

### Wiederherstellung 16.–17. August

- Quelle 16. August: Commit `cd912130803cf0d124eb1dcf8aef4dcf7d0db4b7`.
- Quelle 17. August: Commit `a7f796e9259e2a2864cb93a38e32a3377968d355`.
- Wiederhergestellt: 62.812 deduplizierte Zeilen in 26 UTC-Tagespartitionen.
- Verifiziertes Gesamtarchiv: 579.736 Zeilen in 688 Partitionen.
- Methode und Zeilenzahlen stehen in
  `artifacts/research/history-gap-recovery-v10710.json`.

### Meteoblue Free-Tier

- Kein neuer Key und keine kostenpflichtige Stufe erforderlich.
- Standardmäßig höchstens ein Versuch pro Airport und Lokaltag, frühestens ab 09:00.
- Erfolgreiche und fehlgeschlagene Versuche zählen persistent.
- 429-, Rate-Limit-, Quota- und Credit-Fehler erzeugen 24 Stunden Cooldown.
- Manuelle Streamlit-Refreshes respektieren denselben Schutz.
- Open-Meteo, METAR, TAF und Polymarket werden unabhängig aktualisiert.

## Research-only / nicht produktiv verändert

- Post-Peak Upper Tail.
- Munich Late Heating.
- Cloud-Clearance-/Post-Shower-Reheating.
- Airport-Biases, Champion-Gewichte und Regimekoeffizienten.
- TAF bleibt getrennte Guidance.
- Day-/Peak-Lock, Promotion-Gates und Wettlogik bleiben unverändert.

## Tests

- Vollständige `src`-Suite und mechanischer `build/lib`-Spiegel.
- Stale-Meteoblue-Fall mit 40 Stunden Alter.
- Null beziehungsweise nur ein frisches Modell.
- Persistentes Meteoblue-Tagesbudget und 429-Cooldown.
- Fast-Collector archiviert und committed denselben Zustand atomar.
- SQLite-Migration für `fresh_model_count`.
- Archiv-Manifest, Hashes und Roundtrips.

## Rollback

- Code-Rollback durch erneutes Hochladen von v10.7.9.1.
- `fresh_model_count` ist additiv und stört die vorige Version nicht.
- Wiederhergestellte immutable Archive müssen bei einem Code-Rollback nicht entfernt
  werden; sie enthalten ausschließlich deduplizierte historische Originalzeilen.

## Nächster Schritt

Nach produktiver Abnahme startet v10.8.0 als getrenntes Research Replay Lab:
30 Tage Madrid und München, danach Coverage-Entscheidung für sechs Airports/365 Tage.

