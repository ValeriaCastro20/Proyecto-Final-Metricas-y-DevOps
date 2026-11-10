# MET-01: Indicadores y Objetivos de Nivel de Servicio (SLIs/SLOs)

## 1. Preguntas Operativas
1. **¿La velocidad de procesamiento sigue la de recepción?**
   * **Justificación:** Permite decidir si es necesario escalar horizontalmente el procesador (`PROCESSOR_BATCH_SIZE` o réplicas) ante ráfagas sostenidas para evitar que los eventos queden estancados en el inbox transaccional.
2. **¿Cuánto retraso y backlog produce una reducción de capacidad?**
   * **Justificación:** Permite evaluar la resiliencia del sistema ante caídas del procesador (interrupción inducida) y estimar el tiempo de recuperación (Time to Recovery) del backlog acumulado.
3. **¿Cuál es el impacto de la validación estructural en la tasa de ingesta?**
   * **Justificación:** Identifica si un dispositivo o sensor defectuoso está enviando payloads masivos con formatos inválidos (rechazos), lo que ayuda a decidir si bloquear credenciales a nivel de API Gateway o contactar al dueño del dispositivo.

## 2. Service Level Indicators (SLIs)
| Identificador | Nombre | Definición y Cálculo | Unidad | Fuente | Propósito |
|---|---|---|---|---|---|
| **SLI-01** | **Backlog de Procesamiento (Específico ESC3)** | Cantidad de eventos confirmados en base de datos cuyo campo `processed_at IS NULL`. | Eventos pendientes | PostgreSQL (`esc3_events_backlog_total`) | Medir el retraso acumulado del inbox. |
| **SLI-02** | **Latencia de Procesamiento de Lotes** | Tiempo que tarda el método `Store::process` en realizar el SELECT FOR UPDATE y generar las alertas. | Segundos | OpenTelemetry / Trazas (`esc3_processor_duration_seconds`) | Evaluar el rendimiento del worker asíncrono. |
| **SLI-03** | **Tasa de Éxito en Recepción (Ingesta)** | `(Peticiones HTTP 202 Accepted + 200 OK) / Total de peticiones a /v1/readings` | Porcentaje (%) | Métricas Axum HTTP (`http_requests_total`) | Garantizar que el servicio acepta lecturas correctamente. |

## 3. Service Level Objectives (SLOs) y Presupuesto de Error
* **SLO-01 (Basado en SLI-03): Tasa de Éxito de Ingesta**
  * **Objetivo:** El 99.9% de las peticiones a `/v1/readings` deben resultar en `202 Accepted` o `200 OK` (duplicados válidos) evaluado en una ventana continua de 24 horas.
  * **Justificación:** Los dispositivos IoT no suelen tener gran capacidad de almacenamiento local; rechazos prolongados significan pérdida definitiva de telemetría.
  * **Presupuesto de error:** 0.1% de peticiones fallidas permitidas en 24 horas.

* **SLO-02 (Basado en SLI-02): Latencia de Procesamiento**
  * **Objetivo:** El 95% de los lotes procesados por el worker deben tomar menos de `0.5` segundos evaluado en una ventana móvil de 1 hora.
  * **Justificación:** Garantizar que las alertas de negocio (temperatura/humedad fuera de límites) se generen de manera casi inmediata para que el equipo de mantenimiento reaccione a tiempo.
  * **Presupuesto de error:** 5% de los lotes pueden exceder los 0.5 segundos en casos de alta contención de base de datos.