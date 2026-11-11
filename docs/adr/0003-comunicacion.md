# ADR-0003 · HTTP/JSON con confirmación inmediata e I/O async

> La exclusión de 202 de esta decisión histórica aplica al contrato genérico
> `events`. ESC3 usa recepción durable 202 e inbox según [ADR-0005](0005-inbox-esc3.md).

- Estado: aceptada; adaptación Rust, 2026-11-07.
- Contexto: productores necesitan saber si sus datos están confirmados, duplicados o rechazados; analistas requieren datos confirmados.

HTTP REST/JSON en Axum; I/O PostgreSQL asíncrono con SQLx/Tokio. La petición espera el COMMIT: async no implica aceptación diferida. Errores semánticos estables, `X-Request-ID` y OpenAPI generado desde tipos/rutas.

Se descartan broker/202 (añade reconciliación y consistencia eventual) y gRPC (no requerido por los clientes). Cada llamada puede esperar DB y competir por el pool. Timeouts y backoff están acotados, pero no hay deadline HTTP global ni rate limiting interno: configurarlos en el proxy según el despliegue.

Las rutas/versiones y documentos JSON conservan el contrato del servicio anterior. Las escrituras no se reintentan automáticamente por ambigüedad de COMMIT ante cortes de red.
