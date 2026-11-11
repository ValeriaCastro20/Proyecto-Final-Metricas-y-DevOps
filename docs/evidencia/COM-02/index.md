# COM-02 · Límites y arquitectura · Rust

[Issue #2](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/2). Criterio: responsabilidades y decisiones verificables en código.

- [Contexto](../../arquitectura/contexto.md), [módulos](../../arquitectura/contenedores.md), [despliegue](../../arquitectura/despliegue.md).
- ADRs [0001](../../adr/0001-descomposicion.md), [0002](../../adr/0002-almacenamiento.md), [0003](../../adr/0003-comunicacion.md), [0004 Rust](../../adr/0004-rust.md).
- `src/service.rs` depende del puerto `src/repository.rs`; `src/postgres.rs` implementa SQLx. `src/main.rs` construye e inyecta dependencias. `tests/service.rs` verifica autorización sin tocar el repositorio.

Reproducir: `cargo test --locked --test service`, `cargo doc --locked --no-deps`.
La existencia del Dockerfile no acredita despliegue ni revisión independiente.
La sección DEV-09 de 2026-11-09 sí documenta un despliegue histórico de development;
no certifica el estado actual. Documentación exportada en artefacto CI
`rust-api-and-code-docs`.

## Actualización ESC3 · 2026-11-11

Contexto, módulos y despliegue distinguen API y worker independientes, inbox
PostgreSQL, recibos, alertas y aceptación 202. [ADR-0005](../../adr/0005-inbox-esc3.md)
acota los ADR históricos del contrato genérico. El diagrama de despliegue se
contrasta con `kubernetes/resources.json`, renderer y manifiestos de observabilidad,
y enlaza la evidencia histórica [DEV-09](../DEV-09/index.md), sin afirmar una
inspección actual ni despliegue de los cambios MET-02/MET-04.

[Auditoría y pendientes](../ESC3/auditoria-2026-11-11.md): los cinco comentarios
MET-07 ya estaban resueltos; no se rehacen. La API ESC3 funcional existe; falta
aceptación integrada, no crear otra API ni un broker.

Verificación local de esta revisión: tres diagramas renderizados correctamente con
Mermaid CLI 12.2.0 y Chromium, enlaces Markdown locales resueltos, `git diff --check`,
formato Rust, dos pruebas de service, 11 contratos del renderer y cuatro contratos
de observabilidad aprobados. SVG de validación en `/tmp/opencode/com02-*-1.svg`
(locales, no evidencia remota). No se ejecutó despliegue ni Terraform.

## Verificación local del contenedor · 2026-11-07

Se construyó con Podman el Dockerfile de la versión inicial del PR (`8aaab61`): imagen `localhost/pfmdo-rust-review:latest`, ID `f329f5b235d988764cfaa8b8daff1706c205fa43390b7e24ef80688ad24c44ba`, tamaño local 93,962,548 bytes y usuario `10001:10001`. Se ejecutó el binario release del contenedor: exportó OpenAPI válido, atendió liveness con 200 y readiness con 503 sin DB, incluyendo error seguro y Request-ID. Es una prueba local, no publicación de imagen ni despliegue cloud; las revisiones posteriores se verifican de nuevo en CI.
