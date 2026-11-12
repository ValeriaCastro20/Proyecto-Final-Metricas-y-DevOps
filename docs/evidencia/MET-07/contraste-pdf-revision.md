# MET-07: contraste con el PDF oficial y revisión independiente

Fuente de ejecución: commit `dfced229d829f39f828dc762c0fbf4e8829cb6de`. Revisión de archivos exportados, sin carga ni Kubernetes/Azure. El autor del parche `met07-contraste-pdf.patch` (commit de origen declarado `07a18d5`) informa haber consultado `Proyecto de Cátedra.pdf`, SHA-256 declarado `9fbd3ed7782725dce2d4a8736bcd8f04fa01b50f442cdbb630176bfd48d88fdb`. Las citas y páginas físicas proceden de ese revisor. En esta incorporación Windows no se ha localizado ni abierto ese PDF; no se afirma una nueva comprobación de su hash.

Este documento complementa [execution-index.md](execution-index.md). Los documentos originales de publicación registran que su autor no tenía el texto normativo en aquella sesión; ese pendiente se resuelve aquí. No se reescriben los JSON de fuentes, los informes originales ni las capturas para alterar su procedencia.

## Texto normativo y evaluación

### Apartado 5.11, página 6

> Se genera al menos una degradación controlada y reversible. La evidencia contiene línea de tiempo, síntoma, señal de detección, hipótesis, logs, métricas o trazas pertinentes, mecanismo causal, respuesta operativa y validación de la recuperación. Un dashboard sin análisis no satisface esta condición.

| Criterio literal | Evidencia de esta ejecución | Evaluación |
| --- | --- | --- |
| Degradación controlada y reversible | Contexto default/namespace eventos-development; UID original; cambio de una réplica a cero, cero Pods y recuperación a una réplica | Respaldado por control y diario, no solo por un plan |
| Línea de tiempo | Firing 21:35:03.799 UTC; Ready 21:35:07.576; backlog cero 21:35:09.794; inactive 21:36:01.403 | Ratificada por los eventos y muestras exportadas |
| Síntoma y detección | Backlog máximo muestreado 437 y alerta HighEventBacklog; recepción sostenida con procesamiento detenido | Respaldado por gauge y ledger; un máximo muestreado no es necesariamente el máximo instantáneo |
| Hipótesis y mecanismo causal | Retirar el consumidor permite acumular trabajo persistido; reintroducirlo permite drenar | Contraste antes/durante/después con reducción conocida y reversible de capacidad |
| Señales pertinentes | Métricas de Prometheus, logs API/worker y trazas padre/hijo ligadas a UUID/request_id | Correlación comprobada para las 472 lecturas en la consulta de ciclo completo |
| Respuesta y recuperación | Restauración después del firing; 472 respuestas 202 y 472 UUID procesados, backlog cero e inactive | Recuperación funcional comprobada; no se deduce únicamente de Ready |

**Conclusión de revisión:** la evidencia disponible cubre los elementos exigidos por 5.11 para esta ejecución. Esto no equivale a aprobación docente, revisión de PR ni cierre de issue.

### Escenario 3, P3-5, página 10

> Cuantificar tasa de entrada, tasa de procesamiento y retraso, e investigar una degradación provocada por reducción temporal de capacidad.

Se cuantifica una base corta de 5,034 s con entrada/procesamiento 1,986/1,986 lecturas/s. En la ventana estable desde cero Pods hasta la petición de restauración se reciben 434 y se procesan cero en 217,171 s: entrada 1,998/s, procesamiento 0/s, calculados con timestamps durables. El intervalo posterior hasta la primera muestra durable after registra 445 procesadas en 3,557 s; 125,113/s es una media transitoria de drenaje, no una capacidad sostenida.

Las 448 lecturas recibidas entre el límite during y Ready tienen retraso received_at→processed_at mediano de 108,770 s, p95 209,301 s y máximo 219,904 s. El máximo backlog muestreado es 437. La matriz original conserva ventanas, método, datos y limitaciones.

**Conclusión de revisión:** P3-5 cuenta con evidencia cuantitativa y análisis de la reducción de capacidad para esta carga/version. No se convierte esa observación en una prueba de saturación del host ni de capacidad máxima.

### Apartado 5.13, página 7

El requisito pertinente es:

> inducir y diagnosticar un fallo controlado con logs, métricas y trazas

La reducción deliberada de capacidad y su diagnóstico están respaldados por intervención, métricas, diario, logs y trazas correlacionadas. El diagnóstico diferencia persistencia HTTP 202 de procesamiento posterior. La posterior coincidencia de UUIDs y el drenaje tras restaurar apoyan la causa inducida.

**Conclusión de revisión:** se aporta evidencia del componente de diagnóstico de fallos de 5.13. La sección completa exige además pruebas automáticas, identificar versión/código, plan de infraestructura revisable, recuperación de despliegue defectuoso y documentación de apagado/eliminación. No se declara satisfecha toda 5.13 mediante MET-07.

### Anexo II 7.2, puntos 6–9, página 15

- Se mantienen ocho paneles funcionales de MET-05, superiores al mínimo de seis. La prueba de MET-07 no aporta nuevas capturas de Grafana; el PDF no exige una captura distinta de cada panel por cada fase del incidente.
- Hay dos reglas configuradas y una, HighEventBacklog, con firing y posterior normalidad observados. Su umbral >100 durante 120 s no se modificó. La transición de estado en Prometheus no acredita entrega de notificaciones externas.
- El experimento conserva hipótesis, procedimiento, señales, mitigación, comparación y límites. Antes y después se comparan con métodos y ventanas explícitos.
- Los manifiestos, JSON, herramientas y evidencia están versionados. La guía de despliegue preparada separadamente sigue pendiente de incorporarse al repositorio de entrega; no se afirma un redespliegue nuevo.

## Cobertura temporal de señales

La consulta before amplía sus límites y devuelve trazas completas. Su referencia global es el conjunto de 472 lecturas; no se debe interpretar su complete=false como ausencia de las lecturas recibidas antes de degradar. La verificación independiente enlaza simultáneamente logs API, logs worker y trazas padre/hijo de 27 UUID en esa consulta, incluidos los **24 de 24 realmente recibidos antes de la degradación**.

Las consultas during y after enlazan los 472 UUID en sus ventanas ampliadas de ciclo de vida. No significa que los 472 spans worker se ejecutaran mientras no existía worker, ni que cada consulta cubra continuamente cada instante. La interpretación se apoya en timestamps durables y límites solicitados/exportados.

Se conservan limitaciones reales: base corta, p95 inicial poco estable, series del worker ausentes mientras no hay target, series que no capturan el drenaje tras reiniciar el contador, ausencia de captura visual nueva y de evidencia de notificación. Son límites del análisis; no justifican rellenar métricas con cero ni repetir el incidente para mejorar la presentación.

## Comprobaciones informadas por el revisor del parche

- Se reprodujo el auditor offline y sus 10 pruebas de regresión.
- Se escribió una comprobación independiente de la correspondencia intento/event_id/request_id/dispositivo/UUID/fila durable y de logs/trazas padre-hijo: 472 coincidencias, cero errores de conexión registrados y ninguna solicitud sin respuesta.
- Los 102 hashes anteriores se verificaron: 98 coinciden byte a byte; cuatro corresponden a CRLF del checkout Windows y coinciden con esa representación. No hay discrepancias sin explicar ni se reescribieron los manifiestos.
- El auditor confirma las horas, el orden firing→restauración→Ready→backlog cero→inactive, regla y duración originales, y estado final Ready/Available=1. Esto acredita el estado capturado, no una consulta del clúster en tiempo presente.
- El revisor del parche informó que el endpoint check-runs del SHA consultado no devolvía checks. No se atribuye CI remoto aprobado a las suites offline ni a esta revisión.

Fuentes principales: [matriz original](execution-publication-09dd66bd-ca18-4ec2-9106-8bcd9561ab03/acceptance-matrix.md), [diario](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/events.jsonl), [filas](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/after-readings.json), [señales after](power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/signals-after.json).

## Requisitos que no se transfieren automáticamente

P3-2 exige 20 eventos/s durante dos minutos; esta ejecución a aproximadamente 2/s no la acredita. P3-4 exige detener un componente de procesamiento cuando existan eventos pendientes: no se acredita esa precondición automáticamente a partir del baseline cero de MET-07. Su evaluación requiere evidencia propia.

El issue #27 tampoco se cierra automáticamente: la preparación, ejecución, revisión humana/CodeRabbit, CI y defensa son estados diferentes. El PR #94 continúa abierto con otra rama; no se creó un PR duplicado ni se modificó desde esta revisión.

## Alcance de esta incorporación Windows

Se incorporan las conclusiones normativas como revisión aportada por su autor, manteniendo la procedencia de las citas. Las verificaciones locales de integridad y del auditor se registran por separado en [incorporacion-parche-pdf.md](incorporacion-parche-pdf.md). No se transfieren aprobaciones de CI, CodeRabbit o revisión humana. La incorporación al PR #94 requiere coordinación con su autor; este commit solo se publicará en feat/met-07-preparacion, sin otro PR para #27.
