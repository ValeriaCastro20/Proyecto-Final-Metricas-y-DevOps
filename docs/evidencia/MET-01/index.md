# MET-01: Indicadores y Objetivos de Nivel de Servicio (SLIs/SLOs)

## 1. Preguntas Operativas
1. **¿La velocidad de procesamiento sigue la de recepción?**
   * **Justificación:** Permite decidir si es necesario escalar horizontalmente el procesador (`PROCESSOR_BATCH_SIZE` o réplicas) ante ráfagas sostenidas para evitar que los eventos queden estancados en el inbox transaccional.
2. **¿Cuánto retraso y backlog produce una reducción de capacidad?**
   * **Justificación:** Permite evaluar la resiliencia del sistema ante caídas del procesador (interrupción inducida) y estimar el tiempo de recuperación (Time to Recovery) del backlog acumulado.
3. **¿Cuál es el impacto de la validación estructural en la tasa de ingesta?**
   * **Justificación:** Identifica si un dispositivo o sensor defectuoso está enviando payloads masivos con formatos inválidos (rechazos), lo que ayuda a decidir si bloquear credenciales a nivel de API Gateway o contactar al dueño del dispositivo.

## 2. Service Level Indicators (SLIs)

Las tres métricas siguientes son propuestas y aún no están implementadas en este repositorio. Sus nombres representan instrumentación pendiente; los SLOs tampoco cuentan todavía con verificación operativa.

| Identificador | Nombre | Definición y Cálculo | Unidad | Fuente | Propósito |
|---|---|---|---|---|---|
| **SLI-01** | **Backlog de Procesamiento (Específico ESC3)** | Cantidad de eventos confirmados en base de datos cuyo campo `processed_at IS NULL`. | Eventos pendientes | PostgreSQL (`esc3_events_backlog_total`) | Medir el retraso acumulado del inbox. |
| **SLI-02** | **Latencia de Procesamiento de Lotes** | Tiempo que tarda el método `Store::process` en realizar el SELECT FOR UPDATE y generar las alertas. | Segundos | OpenTelemetry / Trazas (`esc3_processor_duration_seconds`) | Evaluar el rendimiento del worker asíncrono. |
| **SLI-03** | **Tasa de Éxito en Recepción (Ingesta)** | `100 × (Peticiones HTTP 202 Accepted + 200 OK) / Total de peticiones a /v1/readings`, en una ventana móvil de 24 horas; complementar con el desglose de rechazos indicado abajo. | Porcentaje (%) | Métricas Axum HTTP propuestas (`http_requests_total`) y ledger existente (`reception_receipts`). | Evaluar la aceptación de lecturas y distinguir las causas de rechazo para responder la pregunta 3. |

Para responder la pregunta 3, contar los recibos con `outcome = 'rejected'` en la misma ventana de 24 horas, agrupados por `reason` y `device_id`. Los motivos estructurales son `invalid_format` e `invalid_fields`; `unknown_device` se informa por separado. Si no se pudo recuperar un identificador válido, agrupar `device_id IS NULL` como «sin dispositivo identificable», sin atribuirlo a un sensor. El porcentaje global de rechazo estructural es `100 × recibos con esos dos motivos / total de peticiones a /v1/readings` en esa ventana. El detalle por dispositivo se obtiene del ledger (o de `/v1/rejections`, paginando), no de etiquetas de métricas de alta cardinalidad. Los fallos de autenticación/autorización (`401`/`403`) se contabilizan por separado en HTTP: ocurren antes de crear el recibo y no deben clasificarse como rechazos estructurales. Si no hay peticiones en la ventana, la tasa se informa como N/A.

## 3. Service Level Objectives (SLOs) y Presupuesto de Error
* **SLO-01 (Basado en SLI-03): Tasa de Éxito de Ingesta**
  * **Objetivo:** El 99.9% de las peticiones a `/v1/readings` deben resultar en `202 Accepted` o `200 OK` (duplicados válidos) evaluado en una ventana continua de 24 horas.
  * **Justificación:** Los dispositivos IoT no suelen tener gran capacidad de almacenamiento local; rechazos prolongados significan pérdida definitiva de telemetría.
  * **Presupuesto de error:** 0.1% de peticiones fallidas permitidas en 24 horas.

* **SLO-02 (Basado en SLI-02): Latencia de Procesamiento**
  * **Objetivo:** El 95% de los lotes procesados por el worker deben tomar menos de `0.5` segundos evaluado en una ventana móvil de 1 hora.
  * **Justificación:** Evaluar el rendimiento de ejecución de los lotes y detectar contención de base de datos. Este objetivo no mide la espera en el inbox ni garantiza alertas casi inmediatas: puede cumplirse aunque haya backlog o el worker haya estado detenido. La latencia desde recepción hasta procesamiento y la detección de pendientes vencidos requieren un indicador y un objetivo adicionales, fuera del alcance de esta propuesta.
  * **Presupuesto de error:** 5% de los lotes pueden tardar 0.5 segundos o más en casos de alta contención de base de datos.
