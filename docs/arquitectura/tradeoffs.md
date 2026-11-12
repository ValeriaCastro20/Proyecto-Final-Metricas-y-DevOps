# Trade-offs · Rust / Escenario 3 / COM-06

| Eje | Decisión y alternativa | Coste/riesgo y revisión |
|---|---|---|
| Plataforma de ejecución | Implementación íntegramente Rust con Axum/Tokio/SQLx; tipos estáticos, I/O asíncrono y distribución como binario | Compilación y mantenimiento más exigentes. Latencia p95, throughput, CPU, RSS y coste deben evaluarse con la misma carga antes de establecer mejoras cuantitativas. |
| Consistencia | 201 solo tras COMMIT, lote ACID y unicidad en PostgreSQL; sin cola | DB caída implica 503. Desacoplar solo cuando requisitos de ingestión/disponibilidad lo justifiquen; no se inventa un umbral de escrituras sin medición. |
| Lecturas | SQL bajo demanda; snapshots repetibles para listado/resumen | Agregados amplios pueden ser caros; índices no garantizan milisegundos sobre millones de filas. Medir EXPLAIN ANALYZE antes de vistas materializadas, particiones o motor columnar. |
| Disponibilidad | API sin estado + una DB con volumen; no HA | Punto único de fallo. Si SLA/RTO exige continuidad, evaluar réplica y backup/restore probado. Un volumen no es un backup. |
| Complejidad | Monolito modular, Repository port y DI explícita; sin microservicios ni framework DI | Se escala ingesta/análisis juntos. Separar solo por ciclos de entrega o perfiles de carga demostrados. |
| Concurrencia | I/O async y pool máximo 10, sin bloquear hilos en backoff | El pool puede saturarse; ajustar con métricas y capacidad PostgreSQL. Rust no elimina límites de disco/red/DB. |
| Seguridad | API keys con RBAC y alcance por fuente; sin IdP externo | Rotación manual/reinicio. OIDC si aparecen usuarios humanos/federación; rate limiting y TLS en proxy. |
| Coste | Límite de US$100 de consumo agregado de la suscripción; VM/K3s de un nodo, presupuesto mensual con alertas y desasignación programada | Hay estimaciones, controles y cargos históricos documentados en [costos](../infra/costos.md) y [DEV-14](../evidencia/DEV-14/index.md), no solo un objetivo pendiente. El presupuesto mensual no controla por sí solo el acumulado; disco e IP siguen cobrando al desasignar. Menor RSS no demuestra ahorro sin redimensionamiento medido. |
| Migraciones | SQLx embebido, ejecución explícita antes del deploy | Mantener checksums; adopción conservadora del esquema antiguo. Backup y ensayo obligatorio antes de transición con datos reales. |

El registro de costos del **2026-11-08** documenta US$2.21 acumulados desde el
inicio del proyecto (2026-10-20), incluyendo otros recursos de la suscripción.
Es un corte histórico, **no el gasto ni el crédito disponible actuales**; se debe
actualizar antes de la defensa. Las alertas notifican, no detienen el consumo.

El servicio, sus pruebas y las herramientas de verificación están implementados en Rust; no existe un runtime de aplicación secundario. El esquema relacional y el contrato HTTP permanecen estables. La decisión de plataforma, sus límites y los criterios de aceptación se detallan en [ADR-0004](../adr/0004-rust.md).
