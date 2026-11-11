# Auditoría ESC3 · 2026-11-11

Base revisada: `main` en `7a9cb21`; cambios posteriores separados por issue.
Alcance: código, migraciones, pruebas, manifiestos y requisitos de issues del repo.
No hay PDF versionado: esta auditoría **no certifica** conformidad con un PDF no
disponible, ni inspecciona el clúster en vivo.

## Hallazgos contrastados

| Hallazgo recibido | Estado comprobado / decisión |
|---|---|
| MET-07: distinguir implementación de despliegue | Ya corregido en `docs/evidencia/MET-07/index.md`; no duplicar cambio. Gauge en `src/api.rs`, prueba ignorada en `tests/metrics.rs`, regla en `kubernetes/observability/k8-prometheus.yaml`. |
| MET-07: carga hasta finalizar T4 e intervalos sin solicitudes | Ya documentado en T1/T4; el generador Python instrumentado sigue **pendiente**, no se presenta como disponible. |
| MET-07: intentos, errores de conexión y reading_id separados | T1 ya exige JSONL por intento y aclara que `scenario_load` no basta; falta implementar/validar ese generador. |
| MET-07: timeout y restauración en todos los caminos | T4 ya fija 10 min desde T2, limpieza ante fallo/cancelación y réplicas originales con namespace/UID. Es un procedimiento, no una ejecución comprobada. |
| MET-07: esperar firing antes de recuperar normalmente | Ya explícito en T4; al vencer plazo o fallar se recupera por seguridad sin declarar éxito. |
| Traza API → worker | Válido: main solo instrumentaba HTTP. PR #81 añade contexto durable y spans consumidores; prueba real SDK/PostgreSQL. Falta traza consultable en defensa. |
| Logs de recepción con IDs | Válido: main no registraba cada recibo. PR #82 añade logs post-COMMIT con receipt_id y reading_id cuando existe; rechazos sin lectura no pueden tener reading_id. Depende de #81. |
| Diagramas y “no hay cola/202”, “Azure pendiente” | Válido: este cambio COM-02 actualiza contexto, módulos, despliegue y ADR. Se distingue despliegue histórico DEV-09 del estado actual no observado. |

## Cobertura funcional existente (no rehacer la API)

`docs/escenario.md` define el contrato ESC3-01…10; `src/scenario/{mod,http,store}.rs`
lo implementa con `migrations/2026110803_scenario3.sql`:

- Dispositivos/instalaciones/límites; lecturas tipadas, UTC y validación estricta.
- Recibos durables de rechazo; 202 después de COMMIT y 200 idempotente.
- Históricos por dispositivo/ventana, unicidad concurrente, eventos fuera de orden.
- Agregados y alertas de negocio solo de procesadas, límites por recepción.
- Ledger y contadores consistentes, inbox durable, recuperación con worker separado.
- Generador Rust burst/extra/sustained/custom y pruebas de 1.000 válidos, duplicados,
  tardíos, rechazos, agregados, alertas y recuperación en `tests/scenario3/mod.rs`.

La verificación local de los cambios de código ejecutó formato, Clippy estricto,
all-targets, rustdoc, PostgreSQL 16 dedicado (`--test postgres -- --ignored
--nocapture`) y el test ignorado del gauge. No se ejecutaron en esta auditoría
los perfiles sostenidos completos, `verify_system`, escaneos de imagen ni carga Azure;
la evidencia histórica de esas pruebas se conserva sin presentarla como nueva.

## Lo que sigue faltando

1. Integrar y desplegar cambios aprobados de #81/#82; verificar migración y versión
   real de API/worker antes de afirmar propagación en Azure.
2. Preparar el generador por intento y ejecutar T0–T5 de MET-07 en entorno aislado
   autorizado, con recuperación garantizada y evidencia real. El documento sigue
   siendo **plan no ejecutado**, no aceptación.
3. Capturas/consultas de trazas API-worker, búsqueda de logs, política de muestreo y
   retención y correlación con métricas en defensa; verificar alertas/dashboards.
4. Contrastar COM-02 con digest/recursos actuales; la evidencia DEV-09 de 2026-11-09
   no acredita automáticamente production ni la revisión nueva.
5. Enlazar evidencia accesible al evaluador y conseguir CI, CodeRabbit y revisión
   humana del último estado. Los issues ESC3 abiertos no significan por sí solos
   falta de código, ni esta auditoría autoriza cerrarlos sin sus criterios completos.

No se hizo apply, escalado, reinicio ni experimento de fallo sobre Azure.
