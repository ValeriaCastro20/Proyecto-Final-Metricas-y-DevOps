# MET-07: índice de la única ejecución real

**Ejecución real del 2026-11-12, recuperación funcional verificada.** Entrada al incidente 21:31:10 UTC; firing 21:35:03, worker Ready/1 réplica 21:35:07, backlog 0 a las 21:35:09 e inactive a las 21:36:01. 472 respuestas 202 y 472 UUID procesados; ninguna solicitud incierta. No hubo reintento automático.

Este es el índice vigente de la ejecución. El [index.md original](index.md) y los informes de preparación/aborto se conservan como documentos históricos con sus hashes, sin reescribir su estado observado entonces. No deben leerse como el estado posterior de esta corrida.

| Evidencia | Enlace |
| --- | --- |
| Matriz §5.11/P3-5/diagnóstico §5.13/alerta, tasas, retrasos y límites | [Matriz y análisis](execution-publication-09dd66bd-ca18-4ec2-9106-8bcd9561ab03/acceptance-matrix.md) |
| Cronología exacta, 472 correspondencias, incertidumbre y tasas reproducibles | [Auditoría offline](execution-publication-09dd66bd-ca18-4ec2-9106-8bcd9561ab03/artifact-audit-final.json) |
| Registro de solicitudes inciertas (cero) | [Conciliación](execution-publication-09dd66bd-ca18-4ec2-9106-8bcd9561ab03/uncertain-requests.json) |
| Cobertura de señales previa real 24/24 y distinción del global 144/472 | [Análisis de cobertura](execution-publication-09dd66bd-ca18-4ec2-9106-8bcd9561ab03/signal-coverage-review.json) |
| Diario real por intento y snapshot | [events.jsonl](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/events.jsonl) |
| Filas durables y aceptación del supervisor | [Filas](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/after-readings.json), [aceptación](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/acceptance.json) |
| Fuentes exactas, exit 0 y controles/guard | [Dispatch](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/dispatch-result.json), [ejecución](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/), [informe original de la corrida](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/incident-review.md) |
| Matriz temporal cruda y resultado independiente anterior | [Muestras](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/measured-timeline.json), [verificación](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/real-incident-validation.json) |
| Logs/trazas por consulta de fase | [before](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/signals-before.json), [during](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/signals-during.json), [after](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/signals-after.json) |
| Confirmación administrativa, sin atribuir consultas ARM | [Procedencia](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/administrator-confirmation.json) |
| Aborto anterior conservado sin carga/degradación | [Informe](operational-window-78d46aef-6fa2-4d7e-8bad-248ccf966b5a/operational-review.md), [archivos](operational-window-78d46aef-6fa2-4d7e-8bad-248ccf966b5a/execution/) |
| 102 hashes e inventario anterior a publicar | [Conservación](execution-publication-09dd66bd-ca18-4ec2-9106-8bcd9561ab03/preserved-evidence-sha256.json) |
| Suites offline separadas | [Resultados](execution-publication-09dd66bd-ca18-4ec2-9106-8bcd9561ab03/suite-results.json) |
| Verificaciones de publicación y escaneo | [Checks](execution-publication-09dd66bd-ca18-4ec2-9106-8bcd9561ab03/publication-checks.json), [Gitleaks](execution-publication-09dd66bd-ca18-4ec2-9106-8bcd9561ab03/secret-scan.json) |
| Lista exacta publicada | [Archivos](execution-publication-09dd66bd-ca18-4ec2-9106-8bcd9561ab03/published-files.txt) |

El [contraste con el PDF oficial](contraste-pdf-revision.md) incorpora el texto y la evaluación del revisor que consultó el documento: §5.11 (p. 6) y P3-5 (p. 10) cuentan con evidencia suficiente según esa revisión; §5.13 (p. 7) recibe evidencia de su componente de diagnóstico. La sección completa incluye otras pruebas. **P3-2 y P3-4 no se acreditan automáticamente**. El issue #27 y sus requisitos de revisión/defensa no se cierran con esta revisión documental.

Reproducción segura: python -B scripts/audit_met07_execution.py <directorio execution guardado> <archivo JSON nuevo>. Ese auditor solo lee archivos locales y crea una salida nueva. **No ejecutar los lanzadores operativos, el worker ni los despachadores SSH para revisar o publicar estos artefactos.**

Los JSON grandes de logs/trazas pueden superar la vista previa de GitHub. Usar Raw/Download o leerlos tras clonar; no hace falta ejecutar la aplicación ni el incidente para inspeccionarlos.
