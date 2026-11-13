# MET-01: indicadores, ventanas y presupuestos de error

Refs #21. Catálogo revisado contra `main` e8b20c9. Esta revisión propone SLO-01 v2; no acredita una ventana completa ni cambia alertas, métricas, imágenes o despliegues.

## Preguntas operativas y decisiones

1. **¿El procesamiento sigue a la recepción?** Comparar backlog y tasas reales de recepción/procesamiento. Si crece el inbox, investigar salud del worker y contención de PostgreSQL antes de proponer capacidad. Cambiar réplicas o batch requiere autorización y una medición de capacidad; no se ejecuta aquí.
2. **¿Qué retraso deja una reducción de capacidad?** Backlog y duración de lote describen acumulación y trabajo activo, respectivamente. La espera de cada lectura se obtiene de `received_at` a `processed_at`, no del histograma de lote. Analizar capturas existentes para distinguir espera de ejecución; no repetir un incidente para completar este catálogo.
3. **¿La validación explica los rechazos o está fallando el servicio?** Separar aceptación de negocio (200/202), rechazos estructurales del ledger y respuestas técnicas. Un 422 puede ser una validación correcta; un 202 no demuestra que el worker terminó correctamente. Revisar datos del productor ante rechazos y servicio/BD ante 5xx.

## Contrato común de medición

Las ventanas son móviles, terminadas en un instante `t` registrado en UTC. Para conteos exactos del ledger se usa `[t-W,t)` por `received_at`; la observación de Prometheus usa su selección de rango `(t-W,t]` y `increase`, que estima incrementos y extrapola a los bordes. No se mezclan esos conteos como si fueran idénticos. Registrar fuente, intervalo, job, instance, reinicios y cobertura. Estas consultas se ejecutan sobre el Prometheus de `eventos-development`, cuyos jobs `event-service` y `event-service-worker` apuntan solo a ese namespace; no existe una etiqueta `namespace` de aplicación que se pueda inventar en los selectores. No combinar muestras de otros ambientes.

Antes de declarar cumplimiento, se necesita cobertura de toda la ventana: scrapes esperados de 5 s, targets, huecos y resets. `up=1` actual y una respuesta exitosa de PromQL no prueban esa cobertura. `increase` contempla resets visibles, pero no recupera eventos anteriores al primer scrape de una réplica ni eventos perdidos entre scrapes. Un target inaccesible o huecos de captura son **datos desconocidos**, no cero ni cumplimiento. No descartar selectivamente minutos sin datos para mejorar el resultado. Ausencia de serie, valor NaN, denominador cero o cobertura incompleta: **N/A para el objetivo completo**, conservando por separado lo que sí se observó. No usar `or vector(0)` ni completar buckets ausentes con cero.

## SLIs: población, cálculo y exclusiones

| SLI | Población y unidad / numerador y denominador | Ventana y fuente | Exclusiones y datos ausentes | Decisión |
| --- | --- | --- | --- | --- |
| **SLI-01: backlog ESC3** | Cantidad de lecturas confirmadas en PostgreSQL con `processed_at IS NULL`. Unidad: lecturas pendientes; no hay denominador. | Snapshot en cada scrape de `/metrics` de API: `esc3_events_backlog_total`. Para tendencia: últimos 5 min, manteniendo timestamps de cada muestra. La BD es la fuente del conteo. | Excluye rechazos y duplicados sin nueva lectura; incluye todas las pendientes del namespace, aunque sean anteriores a la ventana. Un fallo de BD hace fallar el scrape: no usar el último valor como si fuera actual ni interpretar ausencia como inbox vacío. | Investigar acumulación y velocidad de drenaje; no mide edad de la lectura más antigua. |
| **SLI-02: duración de lotes no vacíos** | Una observación por lote exitoso con `changed > 0`, no una por lectura. Buenas: observaciones **≤0,5 s**; N: observaciones `_count`. Duración en segundos y porcentaje de lotes buenos. | Ventana móvil de **1 h**. `esc3_processor_duration_seconds_bucket{le="0.5"}` y `_count` del worker. Inicio antes de abrir transacción, fin tras UPDATE y COMMIT: incluye espera por conexión, transacción y generación de alertas. | Excluye polls vacíos, lotes con error/rollback, sleep entre polls y espera previa de la lectura en el inbox. Worker detenido no genera muestras. Sin deltas de bucket/count de 1 h, N=0 o datos incompletos: N/A; no atribuir duración cero. | Evaluar ejecución de lotes y contención, no disponibilidad extremo a extremo. |
| **SLI-03: aceptación 200/202 (negocio, descriptivo)** | Respuestas completadas de `/v1/readings` que atraviesan el middleware instrumentado. Buenas de negocio: status 200 o 202; N: todas las respuestas instrumentadas de esa ruta, incluidos 4xx/5xx. `100 × buenas/N`. | Ventana móvil de **24 h**; `http_requests_total` con `route="/v1/readings"` y `status`. | Excluye otras rutas, `/metrics`, probes y solicitudes que no producen respuesta instrumentada. 200 incluye retransmisión válida, no una nueva lectura. 401/403 no son rechazos estructurales; 422 puede ser correcto. Ausencia o N=0: N/A. | Describir aceptación y mezcla de solicitudes. Se conserva; ya no define el SLO técnico propuesto. |
| **SLI-04: respuestas técnicamente aceptables (propuesta SLO-01 v2)** | Misma población de respuestas completadas e instrumentadas de `/v1/readings`. Buenas técnicas: **cualquier 2xx o 4xx**; N: todas las respuestas completadas instrumentadas, incluyendo 3xx/5xx. `100 × buenas/N`. | Ventana móvil de **24 h**; `http_requests_total`, etiquetas existentes `route` y `status`. | Excluye otras rutas y fallos antes de respuesta/middleware, DNS/TLS/red, timeouts/cancelaciones sin registro. Un 4xx cuenta técnicamente bueno aun si es funcionalmente incorrecto. Ausencia o N=0: N/A. | Distinguir fallos técnicos observables en respuestas de aceptación de negocio. No sustituye una sonda externa. |

El contador HTTP se incrementa después de `next.run` en [src/api.rs](../../../src/api.rs); no acredita recepción de todos los intentos de clientes ni entrega efectiva de todos los bytes. El histograma se observa solo tras un lote no vacío exitoso en [src/scenario/store.rs](../../../src/scenario/store.rs). Los buckets se definen en [src/main.rs](../../../src/main.rs), incluido 0.5. Véase el [contrato ESC3](../../escenario.md).

### Desglose de rechazos estructurales

Sobre `reception_receipts`, en la misma ventana UTC de 24 h por `received_at`, contar `outcome='rejected'` agrupado por `reason` y `device_id`. Separar `invalid_format` e `invalid_fields` de `unknown_device`; `device_id IS NULL` significa «sin dispositivo identificable», sin atribuirlo a un sensor. Para una proporción reproducible del ledger, el denominador es el total de **recibos** de esa ventana; no mezclar recibos por recepción con respuestas HTTP por finalización como si sus bordes y población fueran iguales. Excluye fallos de autenticación/autorización, requests demasiado grandes y fallos de BD sin recibo durable. Si faltan páginas, acceso o cobertura: N/A. Con cero recibos: N/A, no 0%.

`/v1/rejections` pagina por `received_at,id` ascendente, `limit` 1–1000 y `offset` hasta 100000; no filtra tiempo. Si esos límites no permiten cubrir toda la ventana, se requiere una consulta autorizada al ledger con ese filtro temporal. Una página parcial no representa el total. No añadir device_id como etiqueta métrica de alta cardinalidad ni consultar credenciales para esta evaluación offline.

## Consultas sobre métricas existentes

No se crean recording rules. `N` y `buenas` abajo son nombres de resultados para el cálculo offline, no nuevas series de Prometheus. Ejecutar cada consulta al mismo `t` y guardar resultado y cobertura.

```promql
# SLI-01: snapshot y máximo observado en 5 minutos (el máximo no rellena huecos).
esc3_events_backlog_total{job="event-service"}
max_over_time(esc3_events_backlog_total{job="event-service"}[5m])

# SLI-03: aceptación de negocio en 24 h.
100 * sum(increase(http_requests_total{job="event-service",route="/v1/readings",status=~"200|202"}[24h]))
  / sum(increase(http_requests_total{job="event-service",route="/v1/readings"}[24h]))

# SLO-01 v2, N: todas las respuestas completadas instrumentadas en 24 h.
sum(increase(http_requests_total{job="event-service",route="/v1/readings"}[24h]))
# SLO-01 v2, buenas: 2xx o 4xx; 3xx y 5xx quedan fuera.
sum(increase(http_requests_total{job="event-service",route="/v1/readings",status=~"2..|4.."}[24h]))
# SLI-04: porcentaje técnico observado.
100 * sum(increase(http_requests_total{job="event-service",route="/v1/readings",status=~"2..|4.."}[24h]))
  / sum(increase(http_requests_total{job="event-service",route="/v1/readings"}[24h]))

# SLO-02, N: cantidad de lotes no vacíos exitosos, no lecturas.
sum(increase(esc3_processor_duration_seconds_count{job="event-service-worker"}[1h]))
# SLO-02, buenas: bucket acumulativo inclusivo <= 0.5 s.
sum(increase(esc3_processor_duration_seconds_bucket{job="event-service-worker",le="0.5"}[1h]))
# SLI-02: porcentaje de lotes buenos en 1 h; no usar una media para sustituirlo.
100 * sum(increase(esc3_processor_duration_seconds_bucket{job="event-service-worker",le="0.5"}[1h]))
  / sum(increase(esc3_processor_duration_seconds_count{job="event-service-worker"}[1h]))
```

Una serie seleccionada ausente no se convierte en cero, aunque existan otras series del job. Evaluar también `up{job=~"event-service|event-service-worker"}`, huecos históricos y resets. Contadores acumulados sin sus deltas no permiten atribuir el resultado a 24 h o 1 h. El histograma permite contar exactamente respecto al bucket inclusivo; un `histogram_quantile` estimado sirve como gráfico, no reemplaza ese cociente para el presupuesto.

## Objetivos propuestos y presupuesto

### SLO-01 v2 — disponibilidad técnica de respuestas completadas

**Propuesta explícita:** al menos **99,9%** de las respuestas completadas e instrumentadas de `/v1/readings` deben estar en **2xx o 4xx**, en una ventana móvil de **24 h** (SLI-04). Se conserva 99,9% como objetivo propuesto de baja frecuencia de fallos técnicos; no es una capacidad validada ni un compromiso externo probado.

**Cambia el significado del SLO-01 anterior**, que exigía 200/202 y mezclaba rechazo de negocio con fallo técnico. Por ejemplo, 100 respuestas 422 producirían aceptación de negocio 0% y disponibilidad técnica de respuestas 100%. Eso no demuestra validación correcta, corrección semántica, entrega durable ni disponibilidad extremo a extremo: puede cumplirse con credenciales inválidas, con el worker detenido o con intentos de red no observados. La aceptación 200/202 permanece como indicador descriptivo SLI-03. La v2 requiere revisión del equipo; no reinterpreta retroactivamente el objetivo anterior ni se da por aprobada por este documento.

### SLO-02 — ejecución de lotes

Al menos **95%** de los lotes no vacíos exitosos deben tardar **≤0,5 s** en una ventana móvil de **1 h** (SLI-02). Se conserva el objetivo; se corrige su frontera para coincidir con el bucket inclusivo `le="0.5"`. Un lote de exactamente 0,5 s es bueno; los malos duran **>0,5 s**. El 5% de margen admite contención puntual de PostgreSQL; no garantiza tiempo máximo de una lectura ni detección de pendientes. Lotes fallidos y períodos sin lotes requieren análisis separado, no se cuentan como lotes rápidos. La media de 1 min de la alerta no es equivalente al porcentaje de 1 h.

### Cálculo reproducible para ambos objetivos

Con población válida y cubierta, `N > 0`, `0 ≤ buenas ≤ N` y objetivo expresado como fracción:

```text
malas = N − buenas
permitido = N × (1 − objetivo)
consumo = 100 × malas / permitido
```

SLO-01 v2: objetivo 0,999; permitido `N × 0,001`. SLO-02: objetivo 0,95; permitido `N × 0,05`. El saldo es `permitido − malas`; consumo >100% agota el presupuesto. Es un presupuesto de eventos, no minutos de caída. Puede ser fraccionario: no redondear 0,472 a un fallo permitido ni redondear hacia arriba el límite de lotes. Con N=0, ausencia, cobertura incompleta o valores no finitos, reportar N/A del objetivo completo; nunca 0% de consumo por falta de datos.

## Evaluación offline de la captura real MET-07

Se releyó exclusivamente el diario real [events.jsonl](../MET-07/power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/events.jsonl), conciliado con [la auditoría publicada](../MET-07/execution-publication-09dd66bd-ca18-4ec2-9106-8bcd9561ab03/artifact-audit-final.json). No se ejecutaron carga, SSH ni incidentes nuevos. Reproducción: `node docs/evidencia/MET-01/evaluate-capture.cjs`. [Resultado derivado con hash de fuente](capture-evaluation.json).

| Medida en la captura | Resultado |
| --- | --- |
| Intentos y respuestas conciliados | 472 intentos, 472 respuestas 202, cero fallos HTTP observados y cero errores de conexión |
| Aceptación descriptiva SLI-03 | 472 / 472 = 100% en esta captura |
| SLO-01 v2, presupuesto **parcial** | N=472, buenas=472, malas=0; permitido=472 × 0,001 = **0,472**; consumo=100 × 0 / 0,472 = **0%** |
| Evaluación completa de SLO-01 v2 | **Pendiente / N/A**: captura corta, no una ventana cubierta de 24 h ni todos los intentos posibles |
| Evaluación completa de SLO-02 | **Pendiente / N/A**: faltan deltas de bucket `le="0.5"` y `_count` que cubran una hora; no deducirlos de 472 lecturas procesadas ni de una media |

El 100% observado durante el incidente puede coexistir con backlog y retraso alto: precisamente muestra la limitación del indicador de respuestas. Estos resultados no declaran cumplimiento de 24 h, no prueban semántica ni disponibilidad extremo a extremo y no sustituyen la revisión de MET-07.

## Verificación de esta corrección

`npm ci` con Node 22.15.0 instaló Husky (`core.hooksPath=.husky/_`). `cargo fmt --all -- --check` pasó con Rust 1.97.1. Se verificó la sintaxis Node del evaluador, se ejecutó sobre los archivos locales y pasó `git diff --check`. Salidas: [corrections-validation.txt](corrections-validation.txt). Gitleaks 8.28.0 nativo, verificado con checksum oficial, examinó todo el historial Git (`--log-opts=--all`) y este directorio con `--redact`, sin hallazgos ni nuevas excepciones: [secret-scan.json](secret-scan.json). El wrapper Docker no se ejecutó porque el daemon local devolvió HTTP 500; se utilizó el mismo scanner nativo.

No se ejecutaron despliegues, reinicios, carga, SSH ni consultas a la aplicación. No se ejecutó cargo test/clippy por tratarse de documentación y cálculo offline sin cambios Rust; formato y Husky no sustituyen los checks de CI ni revisión CodeRabbit/humana antes de integrar. Esta corrección usa `Refs` y no cierra automáticamente el issue.
