# ADR-0005 · Inbox PostgreSQL y procesador ESC3 independiente

- Estado: aceptada, documenta la implementación ESC3 actual, 2026-11-11.
- Complementa ADR-0001/0002/0003: sus contratos `events` son del flujo genérico,
  no deben interpretarse como descripción del flujo ESC3.
- Contexto: la recepción de dispositivos debe continuar con el procesador detenido,
  conservar pendientes y reintentos y permitir verificar contadores tras reinicios.

## Decisión

Un binario/imagen Rust, procesos `serve` y `process` separados; PostgreSQL 16
mantiene `devices`, `readings`, `reception_receipts` y `business_alerts`.
La API confirma 202 tras COMMIT de la lectura y su recibo. La unicidad
`(device_id,event_id)` devuelve 200 y el reading_id original en retransmisiones
válidas. Rechazos de validación guardan recibo y devuelven 422, sin crear lectura.

El worker bloquea lotes con `FOR UPDATE SKIP LOCKED` y confirma alertas y
`processed_at` juntos. Un crash revierte la transacción: otro intento puede
procesar el pendiente, sin efectos duplicados por `(reading_id,kind)`.
Los límites se copian al recibir; los agregados incluyen solo procesadas.

## Alternativas y consecuencias

- Broker externo: aporta herramientas de colas, pero añade operación y coordinación
  DB/broker; el inbox cubre este alcance con una autoridad transaccional.
- Procesar en la petición: simplifica el flujo, pero acopla disponibilidad y latencia
  de recepción a la capacidad de análisis. Se descarta para ESC3.
- Una unidad de entrega, **dos ciclos de vida**: la API y el worker escalan separados,
  compartiendo el cuello de botella PostgreSQL. Hay un pool por proceso/réplica.
- Aceptación no implica resultado inmediato: los clientes deben consultar estado,
  histórico o contadores. No hay garantía general de exactamente una ejecución.
- Inbox/recibos sin retención automática y disco local sin HA: requieren capacidad,
  respaldo y política de archivo para producción. Persistencia ante reinicio no
  equivale a supervivencia ante pérdida de VM.

Contrato y pruebas: [escenario](../escenario.md). Componentes/despliegue:
[COM-02](../arquitectura/despliegue.md).
