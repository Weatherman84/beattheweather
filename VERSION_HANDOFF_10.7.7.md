# Version Handoff 10.7.7

## Release-Grenze

v10.7.7 verbessert Collector-Cadence, Laufmetriken, Checkpoint-Freshness, Actual- und
Probability-Lineage sowie die Vorbereitung des Historical Replay Labs. Produktive
Forecast- und Trading-Entscheidungsregeln bleiben unverändert.

## Ursache, Nutzen, Risiko und Aufwand

| Punkt | Ursache | Nutzen | Risiko | Aufwand |
|---|---|---|---|---|
| Collector-Fast-Path | Sequenzielle Providerreads, Retries und wiederholte Sonderreparatur verlängerten den Single-Writer-Job | Kürzere Laufzeit bei weiter seriellen DB-Writes | Provider-Teildefekte müssen sichtbar bleiben | hoch |
| Scheduler-Lineage | Ein Zeitstempel vermischte Cron-, Queue- und Laufzeitverzögerung | Tatsächliche Cadence wird messbar | Soll-Slot bleibt bei GitHub inferiert | mittel |
| Checkpoint-Freshness | `scheduled` sagte nichts über Quellenalter/Coverage | Kausale, aber alte Snapshots werden erkennbar | Schwellen könnten als Trading-Gate missverstanden werden | mittel |
| Actual-Qualität | Provisional-Werte durften keine finale Evaluation speisen | OOS/Kalibrierung basiert auf Settlement-Qualität | Legacy-Zeilen ohne Provenance brauchen Kompatibilität | mittel |
| Probability-Lineage | Nullable/vermischbare Raw- und Champion-Felder | Neue Shadow-Zeilen sind nachvollziehbar | Unvollständige Zeile wird bewusst nicht gespeichert | niedrig |
| Peak-Lock-Diagnostic | Einzelne Abendläufe blieben trotz Abkühlung aktiv | Historische Häufigkeit und False-Lock-Risiko werden messbar | Keine produktive Ableitung aus kleiner Stichprobe | mittel |
| Replay-Readiness | Providerdaten besitzen unterschiedliche Kausalität/Coverage | Pilot kann Leakage vermeiden | Bericht ist noch kein Replay | mittel |

## Implementiert

- Offset-Cron und weiterhin eine globale Single-Writer-Concurrency.
- Begrenzte Parallelität nur für Netzwerkreads; serielle Datenbankpersistenz.
- Provider-/Airport-Laufzeiten, Status, Versuche und Run-Cadence-Metriken.
- Checkpoint-Run/Available/Fetch, Quellenalter, Coverage, Freshness und Evidenz.
- Monotone Actual-Qualität und settlement-grade OOS-/Kalibrierungsfilter.
- Vollständigkeitsguard für neue Shadow-Probability-Lineage.
- Read-only Peak-Lock-Ablation.
- Read-only Provider-/Coverage-Matrix für Replay-Readiness.
- Regressionstests in `src` und identischem `build/lib`-Spiegel.

## Nicht übernommen

- keine Forecast-Koeffizienten, Gewichte oder Biasänderungen;
- keine Madrid-/München-Warmkorrektur und keine AROME-HD-Umgewichtung;
- keine Regime- oder Day-Lock-Schwellenänderung;
- keine Challenger-Promotion;
- keine Lockerung von Safety-, Kalibrierungs- oder Markt-Konflikt-Gates;
- kein vollständiger 365-Tage-Replay;
- keine automatische Produktionsänderung aus Research-Ergebnissen;
- keine parallelen SQLite-Writer.

## Testplan

- komplette Pytest-Suite mit `src` gegen eine temporäre SQLite-Datenbank;
- komplette Pytest-Suite mit `build/lib` gegen eine zweite temporäre SQLite-Datenbank;
- Ruff und `compileall`;
- Spiegelvergleich `src/weatherman` gegen `build/lib/weatherman`;
- Migration auf einer Datenbankkopie, danach SQLite-Integritätscheck und unveränderte
  Row Counts der bestehenden Kerntabellen;
- Research-Berichte auf einer Datenbankkopie, SHA-256 der DB vor/nach Ausführung gleich;
- Wheel- und Upload-ZIP-Prüfung inklusive Import von Version 10.7.7.

## Produktionsabnahme

- Workflow 5 manuell starten und grünen Abschluss prüfen.
- Neuer Lauf besitzt Soll/Event/Queue/Start/Ende und Providerzeiten.
- Provider-Teilfehler blockiert nicht den kompletten Lauf und ist sichtbar.
- Zwei Airports per Streamlit-Button aktualisieren; Modelle, METAR, TAF und Polymarket
  prüfen.
- Checkpoints zeigen Status, Freshness, Evidenz, Source Age und Coverage.
- Bestehende finale Actuals bleiben `stored-metar-station`.
- Workflow 8 ausführen, anschließend Streamlit neu booten.

## Verbleibende Grenze

GitHub Actions garantiert keinen Start alle zehn Minuten. Solange ein kompletter
Single-Writer-Lauf einschließlich Checkout, Installation und Git-Persistenz länger als
zehn Minuten dauert, kann derselbe Runner keine echte Zehn-Minuten-Cadence liefern. Die
neuen Metriken zeigen, ob der Fast-Path ausreicht. Falls nicht, benötigt die nächste
Architekturstufe einen von Git-Commits entkoppelten Datenspeicher oder getrennte
schreibkonfliktfreie Queues; das ist bewusst nicht Teil dieses sicheren Releases.

## Rollback

1. Vorheriges v10.7.6-Paket erneut vollständig hochladen.
2. Grünen Test abwarten.
3. Workflow 5 einmal manuell starten.
4. Keine Datenbankspalten löschen: die v10.7.7-Erweiterungen sind additiv und werden von
   v10.7.6 ignoriert.

## Replay-Empfehlung

Ein separater v10.8.0-Pilot über 30 Tage für LEMD und EDDM ist nach einer kurzen
produktiven v10.7.7-Beobachtung vertretbar. Die Pilotdatenbank muss physisch getrennt
sein; `historical-causal`, `reconstructed-research` und `unavailable` dürfen nicht
zusammen als gleichwertige Evidenz ausgewertet werden. Erst nach Pilotabnahme darf über
einen Jahres-Replay entschieden werden.
