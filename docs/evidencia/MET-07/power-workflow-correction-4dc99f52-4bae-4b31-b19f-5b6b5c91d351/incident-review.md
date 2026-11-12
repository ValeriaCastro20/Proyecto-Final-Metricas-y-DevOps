# MET-07 ? Ejecución real única con firing, recuperación y resolución

**Resultado funcional satisfactorio, exit 0.** El nuevo preflight fue solicitado explícitamente por el usuario tras el aborto anterior. Hubo **una sola entrada al incidente, una degradación y una restauración normal**, sin reintento automático. El aborto de las 21:00:04 y toda su evidencia permanecen intactos; no se confunden con esta prueba real.

## Clasificación corregida y precondiciones reales

La actividad de energía se consultó exclusivamente en /repos/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/workflows/411281561/runs con paginación, HTTP 200, identificador de workflow validado, IDs únicos y cobertura completa de total_count. Las cuatro admisiones registraron **6 runs completados, 0 pendientes/activos**, una página completa. No se consultó el inventario general ni se dedujo actividad de energía de CI Rust.

Las admisiones fueron a las 21:30:32.706, 21:30:35.228, 21:31:07.720 y 21:31:21.920 UTC. La primera disponía de 5367,293 s antes de las 23:00; la última de 5318,079 s. El reloj de la VM y el margen estricto >1200 s se comprobaron de nuevo antes de degradar. Todas estuvieron dentro de la ventana aceptada 21:00–23:00 UTC.

Pasaron contexto default/namespace eventos-development, UID/réplica/generación/selector/propietarios/HPA/permisos, Scheduled Events HTTP 200 sin eventos, inventario estricto de timers y apagado local, endpoints autenticados y baseline cero/inactive. La ausencia de automatizaciones externas conserva procedencia **user_relayed_administrator**, con azure_schedules_verified=false y arm_query_performed=false; no se presenta como una consulta ARM propia.

Los followers de API y worker recibieron JSON real y se comprobaron de nuevo antes de armar el guard del incidente. Sus registros históricos iniciales solo acreditan transporte; la evidencia de la ventana procede de lecturas nuevas y se filtra por UUID/dispositivo/tiempos del servidor.

El **guard operativo original**, con su backend real, emitió ACK correcto con UID/GID 1000 y run/UID del Deployment coincidentes. En la prueba previa, con worker aún 1/1, detectó lost-supervisor a los **30,322 s**, dentro del plazo; luego se refrescaron precondiciones y baseline. El guard del incidente dio otro ACK propio antes del patch. La restauración del incidente la solicitó el supervisor tras observar firing; el guard terminó con reason=finished y within_deadline=true. No hubo toma de control por watchdog durante el incidente.

## Cronología real, UTC del servidor

| Momento | Observación |
| --- | --- |
| 21:30:34.250 | Baseline: backlog 0, alerta inactive |
| 21:31:10.000 | Entrada única al incidente; registro del dispositivo sintético |
| 21:31:23.430 | Límite de fase during, inmediatamente antes de solicitar la degradación |
| 21:33:05.125 | Primera muestra pending; backlog observado 197 |
| **21:35:03.799** | **Firing real; backlog observado 437** |
| 21:35:07.582 | Límite de fase after, tras verificar worker Ready |
| 21:35:07.651 | Los 472 aceptados ya constaban procesados; pending durable 0, gauge Prometheus aún 437 |
| **21:35:09.794** | **Primera muestra Prometheus de backlog 0 después de restaurar** |
| **21:36:01.403** | **Alerta inactive, backlog 0 y pending 0** |
| 21:36:08.121 | Worker final con UID original, réplicas=Ready=Available=1 |

Las fechas explícitas de firing y muestras proceden de Prometheus time(); las duraciones de control usan el reloj monotónico compartido de la VM. El intervalo entre solicitud de restauración y Ready fue **3,482 s**; de degradation_started a Ready, **224,141 s**, por debajo del límite de 600 s. El máximo de backlog **observado en las muestras** fue 437; no se afirma que sea el pico exacto entre scrapes.

La regla permaneció **esc3_events_backlog_total > 100 durante 120 s**. Pending y firing se observaron en muestras reales distintas. El retorno a inactive ocurrió después del drenaje; no se interpretó el desfase de scrape/evaluación como backlog durable. No se alteraron umbrales, imágenes, límites ni reglas.

## Carga y conservación de UUIDs

- **472 intentos, 472 respuestas HTTP 202**, cero errores de conexión, sin resultados inciertos ni reenvíos.
- **472 UUID únicos aceptados y 472 filas durables procesadas**, con correspondencia exacta dispositivo/event_id/reading_id y processed_at >= received_at. Los conjuntos coinciden con acceptance.processed_ids; received=accepted=processed=472, duplicates=rejected=pending=0 en el dispositivo del incidente.
- Productor configurado a **2 intentos/s**, continuo hasta Ready. Se registraron **451 intentos en la ventana de control** que empieza al armar el guard, antes del patch. Por separado, hubo **441 intentos entre confirmar cero Pods y verificar Ready**, durante 220.652 s. Esta distinción evita atribuir toda la ventana del guard a ausencia física de Pods.
- Cero intervalos de programación perdidos; máximo intervalo sin petición en la ventana de control: **0,5012 s**.
- occurred_at de 2040 es ficticio y no se utiliza para medir el incidente; se usan recepción/procesamiento durables de 2026 y anclas del servidor.

La verificación independiente de los archivos repitió asociaciones y conjuntos de UUID, tiempos durables, estados del guard, cronología de restauración y ventana. No volvió a ejecutar carga ni el incidente. [real-incident-validation.json](real-incident-validation.json) y [load-window-analysis.json](load-window-analysis.json).

## Forwards, métricas y señales

Los cuatro forwards se abrieron en la VM antes de la primera admisión y permanecieron bajo supervisión durante las peticiones, degradación, restauración, UUIDs y señales. Se cerraron **después** de la última verificación; all_stopped=true. No se dependió de forwards diagnósticos anteriores ni de túneles locales de Windows.

Se conservan tasas de entrada/procesamiento, backlog, p95 HTTP y serie 5xx en las muestras originales y [measured-timeline.json](measured-timeline.json). Las series ausentes y NaN se mantienen; las respuestas propias 202 no se presentan como demostración de ausencia global de 5xx.

| Consulta de ciclo de vida | UUID enlazados | Cobertura declarada |
| --- | ---: | --- |
| before | 144/472 | complete=false |
| during | 472/472 | complete=true |
| after | 472/472 | complete=true |

Las consultas Jaeger fueron HTTP 200, sin límites alcanzados ni streams truncados. Se conservaron logs y trazas correlacionados con lectura/request_id y spans API-worker. **No se suman** UUID/trazas entre fases ni registros duplicados de logs. El alcance es accepted_reading_lifecycle_not_continuous_phase_coverage; la consulta before no demuestra cobertura completa de los 472 ciclos y no se presenta como tal. Los archivos se identifican REAL_READ_ONLY_SIGNAL_OBSERVATION: son observaciones reales, no fixtures.

## Archivos y límites de aceptación

- [execution/preflight-1.json](execution/preflight-1.json) hasta preflight-4.json: controles reales, endpoint exacto, margen y procedencia administrativa.
- [execution/watchdog-probe/](execution/watchdog-probe/) y [execution/incident/guard-ready.json](execution/incident/guard-ready.json): prueba operativa y ACK del incidente.
- [execution/incident/events.jsonl](execution/incident/events.jsonl): diario durable antes/durante/después, por intento y snapshot.
- [execution/incident/after-readings.json](execution/incident/after-readings.json): filas durables y UUIDs.
- [execution/incident/acceptance.json](execution/incident/acceptance.json): aceptación funcional y alcance de señales.
- [execution/incident/signals-after.json](execution/incident/signals-after.json), signals-before.json y signals-during.json: observación de señales por fase.
- [execution/final-worker.json](execution/final-worker.json), [execution/result.json](execution/result.json), [dispatch-result.json](dispatch-result.json): cierre satisfactorio y fuentes exactas.

Las pruebas offline se documentan aparte en correction-review.md y sus JSON por suite: launch 14 final, operate 14, preparation 28, hardening 11, signals 10, OS watchdog 4. El fallo inicial del fixture de paginación y su repetición se conservan sin sumarlos. El resultado real no se deduce de esas pruebas.

Se verificaron nuevamente **102 hashes anteriores**, incluido el aborto original, sin cambios. No se modificaron otros namespaces ni #94; no hubo commits, push, nuevos PRs, integración ni cierre de issues. La evidencia y el código corregido quedan locales y en su copia privada remota para revisión. Esta prueba demuestra degradación/recuperación funcional observada; no acredita saturación física, HA ni conformidad literal con secciones normativas no disponibles.
