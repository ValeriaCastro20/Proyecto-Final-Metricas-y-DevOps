# Desarrollo y arquitectura del código Rust

## Dependencias y límites

```text
main (composition root) ── configura Settings, pool y EventService
api (Axum) ── autentica, extrae DTO, genera OpenAPI, normaliza errores
scenario::http → scenario::store ── API ESC3 / inbox, recibos y consultas
process / drain → scenario::store ── worker ESC3 en otro proceso
service → repository::EventRepository → postgres ── API genérica /v1/events
domain / scenario ── DTO, validación y respuestas de sus respectivos contratos
auth / config / error ── políticas y soporte transversal
telemetry ── contexto W3C HTTP → inbox → worker, exportación opcional
```

**ESC3:** `serve` comparte un pool entre salud, API genérica y `scenario::http`.
Confirma lectura y recibo antes del 202, no procesa el backlog. `process`/`drain`
usan otro pool/proceso: locks SKIP LOCKED, alertas y marcador de procesamiento en
una transacción por lote; spans por lectura cubren esa transacción compartida.
No hay broker externo ni procesamiento implícito dentro de `serve`.

**Patrones empleados, con propósito** (Service/Repository describen el camino
genérico, no deben atribuirse a las rutas ESC3):
- **Repository + inversión de dependencias:** `EventService` recibe `Arc<dyn EventRepository>`; las pruebas sustituyen PostgreSQL sin modificar casos de uso. No añadimos una interfaz por cada clase.
- **Service Layer:** un lugar para autorización, validación y deduplicación intra-lote. Acceso directo a casos de uso no permite saltarse RBAC.
- **Dependency Injection / Composition Root:** `main.rs` decide adaptadores, configuración y pools; no hay contenedor DI ni estado de negocio global mutable. El recorder de métricas y proveedor de telemetría sí se inicializan a nivel de proceso.
- **Unit of Work / RAII:** transacción SQLx por lote; rollback explícito en fallo de inserción y rollback al liberar transacciones no confirmadas. Listado/resumen leen un snapshot `REPEATABLE READ READ ONLY`.
- **DTO y enums:** contratos Serde/Utoipa, `Dimension` y `Bucket` evitan strings arbitrarios como identificadores SQL.

Los contratos de `domain.rs` comparten metadatos de serialización, persistencia y OpenAPI para mantener una única definición verificable. Esta decisión reduce conversiones entre DTO equivalentes, a cambio de acoplar esos tipos a Serde, SQLx y Utoipa. Los casos de uso se mantienen independientes del adaptador concreto de persistencia. `error.rs` centraliza la semántica y traducción HTTP; separar modelos adicionales cuando sus invariantes o ciclos de evolución diverjan.

## Reglas de mantenimiento

1. En ESC3, cambiar tipos/reglas en `scenario/mod.rs`, HTTP en `scenario/http.rs` y persistencia/procesamiento en `scenario/store.rs`. Para el contrato genérico, usar `domain.rs`/`service.rs`. Mantener autorización y validación antes de persistir.
2. Parametrizar todo dato SQL; solo interpolar nombres constantes provenientes de enums.
3. Nunca `unwrap`/`expect` en producción; Clippy los prohíbe. Las pruebas pueden usarlos para aserciones.
4. No imprimir excepciones de drivers, secretos o datos recibidos. `Settings` no implementa `Debug` ni `Serialize`.
5. Mantener módulos cohesivos; no agregar factories, singletons o microservicios sin un problema concreto.
6. Una vez aplicada una migración, no editar su contenido: añadir otra SQL versionada. SQLx comprueba checksums y serializa migraciones con lock.
7. Cambiar contrato junto con anotaciones Utoipa, guía API, matriz de reglas y pruebas.

## Pruebas

| Archivo | Responsabilidad |
|---|---|
| `tests/domain.rs` | Fechas, identificadores, tamaño UTF-8, lotes y límites de consulta |
| `tests/auth.rs` | RBAC, fuentes, configuración ambigua y límites de configuración |
| `tests/service.rs` | Permisos antes de acceder al repositorio y recuperación con doble de prueba |
| `tests/http.rs` | Contrato HTTP, errores, extracción, request IDs y OpenAPI |
| `tests/postgres.rs` | Persistencia real, concurrencia, rollback, filtros, agregados y migraciones |
| `tests/scenario_domain.rs`, `tests/scenario3/` | Rangos/contratos ESC3; aceptación, recuperación y trazabilidad. `scenario3/` pertenece al target `postgres`, no es un target independiente |
| `tests/metrics.rs` | Recorder/labels HTTP; gauge de backlog y latencia de lotes con PostgreSQL (test ignored explícito) |
| `tests/telemetry.rs` | Exportación OTLP opcional en procesos reales; `scenario3/telemetry.rs` verifica inbox, spans y logs JSON con DB |
| `examples/verify_system.rs` | Experimento real con procesos y contenedor propios; no un mock |

`cargo test --locked --all-targets` ejecuta las pruebas sin DB y compila el experimento.
Con PostgreSQL 16 y `TEST_DATABASE_URL`, ejecutar explícitamente ambos targets:

```bash
cargo test --locked --test postgres -- --ignored --nocapture
cargo test --locked --test metrics -- --ignored --nocapture
```

Faltar configuración es un error. La BD debe nombrarse `test_*` o `*_test`;
`DATABASE_URL`, si existe, debe coincidir. Las pruebas aíslan fuentes/dispositivos
o schema de telemetría; un fallo antes de limpiar puede dejar datos de diagnóstico.
No usar una base compartida de producción.

## Herramientas y CI

### Hooks locales

Con Node.js y npm instalados, ejecutar `npm ci` después de clonar para instalar
Husky y activar los hooks de Git. El hook `pre-commit` ejecuta
`cargo fmt --all -- --check`; si falla, corregir con `cargo fmt --all` y volver
a intentar el commit. No modifica archivos automáticamente ni necesita una DB.
Node.js se usa solo para herramientas de desarrollo, no para la aplicación.
Los hooks locales no sustituyen las validaciones de CI.

Rust fijado por `rust-toolchain.toml`, dependencias por `Cargo.lock`. Ejecutar fmt, Clippy con `-D warnings`, pruebas y rustdoc siguiendo el README. El workflow `acceptance.yml` separa calidad, PostgreSQL/experimentos, escaneo de secretos y build y verificación del contenedor no-root ([DEV-03](evidencia/DEV-03/index.md)). Publica el contrato, rustdoc y resultados de aceptación como artefactos. No publica imágenes en un registro ni aplica infraestructura cloud automáticamente.

`cargo run --locked -- openapi` no necesita DB. `cargo doc --locked --no-deps` documenta los módulos públicos. Consultas SQL dinámicas se verifican contra PostgreSQL en integración, no mediante conexión a DB durante compilación.

La publicación, entrega por digest, aprobación de production, rollback y Terraform
están descritos en el [flujo DevOps](devops.md). Son workflows separados de
acceptance: merge/publicación no implican despliegue automático de la aplicación.
