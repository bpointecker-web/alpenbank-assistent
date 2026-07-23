# Retrieval-Evaluation: naiv vs. Hybrid+Reranking

Golden-Set: 6 Fragen mit bekanntem Ziel-Dokument (siehe `eval/golden_set.py`). Metrik: Hit-Rate@5 (Anteil Fragen, bei denen das richtige Dokument unter den Top-5 Quellen ist) und MRR (Mean Reciprocal Rank, 1,0 = richtiges Dokument immer auf Platz 1). Beide Pipelines laufen gegen denselben Index – einziger Unterschied ist die Retrieval-Methode.

| Pipeline | Hit-Rate@5 | MRR |
|---|---|---|
| naiv (Dense-only) | 100% | 1.000 |
| Hybrid + Reranking | 100% | 0.875 |

## Details pro Frage

| Frage | Erwartete Quelle | naiv Treffer? | naiv RR | Hybrid+Rerank Treffer? | Hybrid+Rerank RR |
|---|---|---|---|---|---|
| Welche Hotelkategorie darf ich bei Dienstreisen buchen? | reisekostenrichtlinie.txt | ✅ | 1.00 | ✅ | 1.00 |
| Wie ist die Regel für Überstunden? | arbeitszeitrichtlinie.txt | ✅ | 1.00 | ✅ | 1.00 |
| Was muss ich bei der Passwortwahl beachten? | it_sicherheitsrichtlinie.txt | ✅ | 1.00 | ✅ | 1.00 |
| Warum ist der Aufwand von Kostenstelle 4711 gestiegen? | kostenstellenhandbuch.txt | ✅ | 1.00 | ✅ | 0.25 |
| Wie hoch waren die Reisekosten 2025 und welche Regeln gelten dafür? | reisekostenrichtlinie.txt | ✅ | 1.00 | ✅ | 1.00 |
| Wie lange werden Kundendaten nach Ende der Geschäftsbeziehung aufbewahrt? | datenschutzrichtlinie.pdf | ✅ | 1.00 | ✅ | 1.00 |

## Hinweis zur Aussagekraft

Golden-Set mit 6 Fragen ist bewusst klein (6 Dokumente Corpus) – ein einzelner Ausreißer verschiebt den Mittelwert spürbar. Auf diesem winzigen, thematisch klar getrennten Corpus liefert bereits naives Dense-Retrieval nahezu perfekte Ergebnisse; der publizierte Vorteil von Hybrid-Search + Reranking (15–40 % laut Literatur, siehe Projekt-Review) zeigt sich empirisch erst bei größeren, mehrdeutigeren Corpora mit vielen Near-Miss-Kandidaten – nicht notwendigerweise auf sechs klar unterscheidbaren Dokumenten. Diese Auswertung beweist also nicht 'Hybrid+Reranking ist hier besser', sondern macht Retrieval-Qualität überhaupt erstmals messbar und zeigt ehrlich, wo die Methode bei diesem Corpus (noch) keinen Unterschied macht bzw. auf einer Einzelfrage sogar schwächer abschneidet.
