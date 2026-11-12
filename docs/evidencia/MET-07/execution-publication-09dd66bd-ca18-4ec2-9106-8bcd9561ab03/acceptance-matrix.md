# MET-07: matriz de evidencia, impacto y límites

Este documento revisa **una ejecución real ya concluida** en eventos-development el 2026-11-12. Esta publicación solo lee archivos: no contacta Kubernetes/Azure, genera carga, reabre forwards ni repite capturas. Los hechos proceden del diario, respuestas de API, filas durables y señales exportadas. [Auditoría reproducible y mapa de UUID](artifact-audit-final.json).

## Fuentes y estado de la matriz

El [issue #27](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/27), consultado en lectura, define MET-07 y pide para P3-5 tasas de entrada/procesamiento y retraso/backlog al reducir capacidad. El [issue #50](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/50) separa P3-2 (2400 únicos a 20/s durante 120 s). El texto normativo literal de **§5.11, §5.13 y P3-4 no está disponible** en el repositorio ni en las fuentes localizadas; se solicitó al usuario. Las filas correspondientes trazan la demostración solicitada, sin inventar su redacción ni certificar conformidad literal. Ninguna fila cierra automáticamente un issue, revisión humana o defensa.

| Referencia | Resultado observado y evidencia | Estado y límites |
| --- | --- | --- |
| §5.11: demostración solicitada de degradación/recuperación | Hipótesis: sin worker el inbox acumula mientras la API sigue aceptando. Se observa 1→0→1, entrada ~2/s, procesamiento durable 0 durante parada, backlog máximo muestreado 437, firing y drenaje completo. [Diario](../power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/events.jsonl), [aceptación](../power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/acceptance.json). | Demostración funcional documentada con cronología, respuesta e impacto. Mapeo literal a §5.11 pendiente del texto normativo; no se afirma saturación física, HA o umbral de capacidad. |
| P3-5 según #27 | Base corta: entrada/procesamiento 1,986/1,986 lecturas/s. Parada sin worker hasta petición de restauración: 1,998/0; 434 recibidas, 0 procesadas en 217,171 s. Recuperación: 7 nuevas y 445 procesadas en 3,557 s, media de drenaje 125,113/s. Retraso durante: mediana 108,770 s, p95 209,301 s, máximo 219,904 s. [Cálculo/ventanas/filas](artifact-audit-final.json). | Evidencia cuantitativa real obtenida para esta carga y versión. No es solo un plan/dashboard. Base de 5,034 s y drenaje transitorio no acreditan capacidad sostenida ni toda la defensa. |
| Diagnóstico solicitado de §5.13 | Síntoma: crece el inbox y el retraso de procesamiento sin fallar la aceptación HTTP. Causa inducida: reducir el Deployment process a 0, con UID y cero Pods comprobados. API y BD siguieron aceptando 472 lecturas 202; después de restaurar se verifican las mismas 472 asociaciones. [Control](../power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/control-result.json), [filas durables](../power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/after-readings.json). | Mecanismo causal y diagnóstico funcional respaldados por intervención reversible, métricas, diario y logs/trazas. No diagnostica saturación de CPU, memoria ni BD; conformidad literal §5.13 pendiente. |
| Alerta probada | HighEventBacklog, expresión esc3_events_backlog_total > 100, duration=120; regla validada en cada snapshot. Se observan inactive, pending, firing y posterior inactive del target development. [Transiciones](../power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/measured-timeline.json), [diario](../power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/events.jsonl). | Firing real de Prometheus y resolución real probados. No se conserva entrega de email/webhook/Alertmanager ni capturas de paneles; no se atribuyen notificaciones externas. |
| P3-2 | Esta prueba produjo 472 únicos a ~2 intentos/s; no ejecutó el perfil 2400 a 20/s durante 120 s. | **No acreditado por esta ejecución.** Las pruebas locales históricas del generador no se presentan como esta carga Azure. |
| P3-4 | Se publican datos reales de métricas, logs y trazas de este incidente, con las limitaciones siguientes. | **No se atribuye cumplimiento automático.** Evaluación independiente y contraste con el texto normativo pendientes. |

## Cronología contrastada

| Hito | UTC del servidor | Base del dato |
| --- | --- | --- |
| Baseline | 21:30:34.250 | Snapshot Prometheus, backlog 0/inactive |
| Degradación: límite de fase | 21:31:23.430 | Límite during antes del patch; no timestamp de finalización del patch |
| Cero Pods comprobados | 21:31:26.923363 | Evento monotónico convertido mediante ancla Prometheus |
| Primera muestra pending | 21:33:05.125 | Snapshot, backlog 197 |
| **Firing** | **21:35:03.799** | Snapshot y firing_observed, backlog 437 |
| Solicitud de restauración | 21:35:04.094228 | Evento restore_requested, ancla + desplazamiento monotónico |
| **Worker Ready / réplica original 1** | **21:35:07.576204** | worker_ready después de kube.ready; confirmado por límite after 21:35:07.582 |
| Ledger drenado | 21:35:07.651 | 472 aceptadas = 472 procesadas, pending 0; gauge aún 437 por scrape |
| **Backlog Prometheus 0** | **21:35:09.794** | Primera muestra after con backlog 0 |
| **Alerta inactive** | **21:36:01.403** | Snapshot final del dispositivo: backlog/pending 0 |
| Estado final estructurado | 21:36:08.121707 | Deployment con UID original, réplicas=Ready=Available=1 |

Los segundos 21:35:03/07/09 y 21:36:01 se corresponden con los artefactos; se muestran decimales para evitar presentar el truncado a segundos como mayor precisión. El estado 1/1 de las 21:35:07 está respaldado por el control Ready, no por un JSON de Deployment inventado para ese instante. El JSON estructurado posterior queda identificado aparte.

## Tasas, retrasos y método

Los intervalos son [inicio, fin), con received_at/processed_at durables para contar lecturas y anclas del servidor para los límites. El auditor conserva por separado duración UTC y monotónica; una muestra de Prometheus se fecha con su server_utc, no con el instante algo posterior de escritura del diario.

| Ventana medida | Duración | Entrada | Procesamiento | Interpretación |
| --- | ---: | ---: | ---: | --- |
| Base activa 21:31:11.860–21:31:16.894 | 5,034 s | Delta durable 10: 1,986/s | Delta durable 10: 1,986/s | Comparación corta, sin calentamiento prolongado |
| Cero Pods confirmado–petición de restauración | 217,171 s | 434: 1,998/s | 0: 0/s | Ventana estable sin consumidor, antes de reintroducirlo |
| Petición de restauración–primera muestra durable after | 3,557 s | 7: 1,968/s | 445: 125,113/s | Media de drenaje con arranque; no rendimiento sostenido |

El productor se mantuvo hasta Ready. La ventana del guard contiene 451 intentos; entre la confirmación de cero Pods y Ready hay 441, pero ese segundo intervalo **incluye la reaparición y procesamiento antes de Ready**. Por eso la tasa 0 se mide hasta solicitar restauración, no se extiende artificialmente hasta Ready. No hubo intervalos de programación perdidos; el máximo hueco en la ventana de control fue 0,5012 s.

| Retraso received_at→processed_at | Lecturas por fase de recepción | Mediana | p95 por rango más próximo | Máximo |
| --- | ---: | ---: | ---: | ---: |
| Recibidas antes del límite during | 24 | 0,061574 s | 0,104871 s | 0,108507 s |
| Recibidas entre during y Ready | 448 | 108,769777 s | 209,300941 s | 219,903884 s |
| Total del incidente | 472 | 102,770977 s | 208,798534 s | 219,903884 s |

No hubo nuevas recepciones tras Ready: la fase after acredita drenaje y resolución, no una nueva distribución de carga sostenida. occurred_at=2040 es ficticio y no entra en los cálculos. El intervalo cliente desde el registro de inicio hasta el de resultado tuvo p95 0,015167 s y máximo 0,407223 s; incluye fsync previo al envío y lectura del cuerpo, **no es latencia HTTP pura**.

Las tasas de Prometheus son rate(...[1m]) y se conservan como evidencia distinta del ledger. Entrada during: mediana 2/s, rango 0,436–2/s por calentamiento. Procesamiento: **33 de 43 muestras during ausentes**; al desaparecer el target no se convierten en 0. En after hay cuatro muestras ausentes y 22 con 0: no capturan la ráfaga de drenaje observada en BD; el reinicio y el primer scrape del nuevo contador limitan la inferencia, sin afirmar que esa sea una causa demostrada por samples no exportados. No se deduce fallo de procesamiento de ese 0.

HTTP p95 de Prometheus during osciló entre 0,00475 y 0,019 s; after entre 0,00475 y 0,0055 s. La base tiene dos NaN y una sola muestra finita 0,0235 s; no permite un p95 base estable. La serie global 5xx está ausente en todas las muestras y no equivale a cero. **Las 472 respuestas propias sí son todas 202**, sin fallos de conexión.

## Causa, respuesta y recuperación

La intervención quitó temporalmente capacidad del proceso consumidor, manteniendo la API productora. El ledger sigue creciendo a ~2/s mientras no hay processed_at nuevos en la ventana sin worker; se acumula retraso y el gauge cruza el umbral. La latencia HTTP permanece baja porque 202 confirma persistencia, no procesamiento final. La continuidad exacta de UUIDs y el drenaje al reintroducir una réplica respaldan ese mecanismo causal.

Se esperó firing antes de la restauración normal. Solicitud→Ready: **3,482 s**; solicitud→primera muestra backlog 0: **5,719 s**; solicitud→inactive observado: **57,342 s** (duraciones del diario monotónico). De degradation_started a firing transcurrieron 220,392 s; incluye acumular >100, duración de la regla y muestreo/evaluación. La diferencia entre primeras muestras pending/firing no es el tiempo exacto de inicio del estado pending. Del backlog 0 muestreado al inactive hay 51,609 s; se conserva ese desfase, no se fuerza una resolución instantánea.

El guard operativo previo dio ACK y detectó lost-supervisor a los 30,322 s con worker 1/1. El guard propio del incidente dio otro ACK y acabó reason=finished/within_deadline=true; el supervisor restauró normalmente, sin takeover del watchdog. Se conservaron cuatro forwards hasta finalizar verificación y se cerraron después. Una sola degradación, sin reintento automático; ningún otro namespace, umbral o imagen cambió.

## Solicitudes inciertas y conservación exacta

El universo conciliado son los POST /v1/readings. El alta del dispositivo (HTTP 201) y los GET de control no forman parte de esos 472 intentos. [Registro explícito de incertidumbre](uncertain-requests.json).

[artifact-audit-final.json](artifact-audit-final.json) contiene 472 filas attempt/event_id/request_id/reading_id/status. Se contrastaron 472 inicios con 472 resultados; cero resultados huérfanos, inicios sin resultado, duplicados de diario o UUID, errores de conexión/cuerpo y resultados sin UUID. **uncertain_requests=[]** queda registrado explícitamente. No se asume que una solicitud sin respuesta fuese rechazada; el auditor la clasifica incierta y bloquea aceptación, como prueban sus regresiones.

Cada UUID 202 coincide exactamente con una fila durable del mismo dispositivo y event_id, con processed_at >= received_at. La lista coincide con acceptance.processed_ids; accepted=processed=472 y pending=duplicates=rejected=0 para el dispositivo. Se verificaron los 102 hashes exigidos y el inventario completo previo a esta publicación; el aborto anterior no se reescribió.

## Señales previas: qué falta y qué se puede concluir

[Revisión de cobertura](signal-coverage-review.json) evita confundir alcance temporal y conjunto de UUIDs. La consulta before usa una ventana ampliada 21:30:10.801–21:32:23.430 y devuelve trazas completas, no solo spans nacidos en la fase solicitada. Sus 144 UUID enlazados **no son 144 solicitudes previas**. Tiene correlación conjunta de logs API/worker/traza para 27 UUID y, dentro de ellos, **las 24 lecturas realmente recibidas antes de degradar (24/24)**.

Falta cobertura de todos los 472 ciclos en la consulta before (global complete=false), contexto continuo más largo de la línea base, un p95 inicial estable y series continuas del worker durante su ausencia. No hay capturas visuales de paneles, notificación externa entregada, datos de saturación de host ni una segunda carga sostenida postrecuperación. No se repite la prueba para producirlos.

Las consultas during y after enlazan **472/472 UUID** y conservan logs correlacionados y parentesco de spans API→worker, sin truncamiento ni límites alcanzados. Sus ventanas también se amplían para cubrir todo el ciclo durable: prueban recepción y procesamiento de los mismos eventos, **no cobertura continua ni exclusiva de cada fase**, ni 944 eventos distintos. Junto con el diario y los contadores, permiten concluir conservación de datos y recuperación funcional; no capacidad sostenida, HA, causalidad de CPU ni todos los requisitos P3.

## Validación de esta publicación

Los resultados actuales de suites se registran por separado en suite-results.json. Son fixtures/contratos offline y no una repetición de MET-07. npm ci, formato, Husky real, sintaxis y Gitleaks se documentan en publication-checks.json y secret-scan.json antes de crear el commit. No se usa HUSKY=0 ni --no-verify. No se ejecutan PostgreSQL, app/worker, image/container ni Terraform para cambios de herramientas/evidencia. CI, CodeRabbit y revisión humana del nuevo commit no se dan por aprobados localmente; no se integra ni cierra el PR/issue.
