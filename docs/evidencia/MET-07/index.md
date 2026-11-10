# MET-07: Análisis de Degradación Inducida y Recuperación

## 1. Hipótesis
Si se reduce a cero la capacidad del componente procesador (`process`) mientras el sistema recibe una carga sostenida de eventos, el servicio de ingesta (`serve`) seguirá aceptando peticiones y devolviendo `202 Accepted` sin interrupción (debido al diseño de inbox transaccional). Sin embargo, el indicador de backlog (`esc3_events_backlog_total`) crecerá de forma lineal, lo que eventualmente disparará la alerta `HighEventBacklog`. Al restaurar el procesador, el backlog debe drenarse sin pérdida de datos.

## 2. Procedimiento y Secuencia Temporal
* **T0 (Estado Normal):** El sistema opera con normalidad. API y Procesador activos. `esc3_events_backlog_total` se mantiene cercano a 0.
* **T1 (Inyección de Carga):** Se inicia el script `scenario_load.rs` generando 20 eventos por segundo durante 2 minutos.
* **T2 (Degradación Inducida):** Se detiene intencionalmente el despliegue del componente `process` en Kubernetes.
* **T3 (Detección - Síntoma Operativo):** 
  * La latencia de ingesta HTTP (`http_request_duration_seconds`) se mantiene estable (rápida).
  * El contador de eventos aceptados (`esc3_events_received_total`) sube a ritmo constante.
  * El `esc3_events_backlog_total` cruza el umbral de 100. Tras 2 minutos, Prometheus dispara la regla de alerta `HighEventBacklog` con severidad *critical*.
* **T4 (Respuesta/Recuperación):** Se vuelve a aplicar el manifiesto para levantar el componente `process`.
* **T5 (Resolución):** El procesador arranca, consume lotes de la base de datos (observable mediante los picos en `esc3_processor_duration_seconds`) y el backlog disminuye a 0. La alerta se resuelve automáticamente en Grafana.

## 3. Interpretación de Señales Correlacionadas (Logs y Trazas)
Al analizar OpenTelemetry (Jaeger) durante el incidente, se observan _spans_ huérfanos de la ruta `/v1/readings` (ingesta completada) que no tienen su contraparte de procesamiento asíncrono. Los logs estructurados no muestran errores `500` ni fallos de base de datos durante `T2-T4`, lo que demuestra que la falla del procesador está correctamente aislada de la API. 

## 4. Limitaciones del Experimento
Este experimento valida el desacoplamiento lógico entre la recepción y el procesamiento, pero asume que la base de datos (PostgreSQL) y el ancho de banda de red tienen capacidad infinita. Si el apagón del procesador se prolonga demasiado, el disco de la base de datos podría llenarse, provocando eventualmente una falla en cascada que sí afectaría la ingesta.