# Proyecto Final — Métricas y DevOps · Rust

Plataforma de **ingesta y análisis de eventos (Escenario 3, COM-01…06)** implementada íntegramente en **Rust**, con **Axum, Tokio, SQLx y PostgreSQL 16**. Un binario con API y procesador independiente, inbox durable y persistencia transaccional.

- Repositorio: <https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps>
- **Escenario 3 específico:** dispositivos por instalación, lecturas tipadas, rechazos auditables, alertas configurables, contadores consistentes, backlog y generador reproducible. [Contrato, pruebas y comandos](docs/escenario.md).
- La API genérica `/v1/events` se conserva por compatibilidad y no alimenta el procesamiento ni los contadores ESC3. Para el escenario usar `/v1/readings` y `/v1/devices`.
- ESC3: aceptación durable 202, duplicado válido 200 con reading_id original y rechazo registrado 422; el worker procesa por separado.
- Históricos por generación UTC `[from,to)`, estadísticas de procesadas y límites de negocio por dispositivo.
- Compatibilidad genérica adicional: lotes atómicos de 1–100 `/v1/events`, deduplicación `(source,external_id)` y análisis de JSONB; **no son lecturas ESC3**.
- API keys con RBAC (`producer`, `analyst`), restricciones por fuente, errores seguros y `X-Request-ID`.
- Pool asíncrono acotado, timeouts, reintentos de lectura y apagado ordenado SIGINT/SIGTERM.

## Arranque local

Requiere Rust (la versión está fijada en `rust-toolchain.toml`), Docker Compose o Podman Compose, `openssl` y `curl`. Cargo descarga las dependencias fijadas en `Cargo.lock`. La aplicación **no carga `.env` automáticamente**.

```bash
cargo build --locked

# Solo la primera vez: no sobrescribir un .env existente.
test ! -e .env && cat > .env <<EOF
POSTGRES_USER=events
POSTGRES_DB=events_test
POSTGRES_PORT=15433
POSTGRES_PASSWORD=$(openssl rand -hex 16)
EVENT_PRODUCER_KEY=$(openssl rand -hex 16)
EVENT_ANALYST_KEY=$(openssl rand -hex 16)
EVENT_PRODUCER_SOURCE_KEYS=sensor-a:$(openssl rand -hex 16),sensor-b:$(openssl rand -hex 16)
EOF
chmod 600 .env
set -a; . ./.env; set +a
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}"
export TEST_DATABASE_URL="$DATABASE_URL"

docker compose up -d --wait postgres
cargo run --locked -- migrate
cargo run --locked -- serve
# En otra terminal con el mismo entorno: procesador ESC3 independiente.
# cargo run --locked -- process
```

API en `http://127.0.0.1:8000`. Para Podman, sustituir `docker compose` por el proveedor Compose instalado. Si no admite `--wait`, esperar con `pg_isready` antes de migrar. Las credenciales deben estar disponibles también al ejecutar comandos en otra terminal. Usar contraseñas URL-encoded si contienen caracteres reservados; los secretos hexadecimales del ejemplo no los necesitan.

```bash
curl -i http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
curl -i -H "X-API-Key: $EVENT_PRODUCER_KEY" -H 'Content-Type: application/json' \
  -d '{"id":"sensor-demo","facility_id":"instalacion-demo","limits":{"temperature_min":0,"temperature_max":30,"humidity_min":20,"humidity_max":80}}' \
  http://127.0.0.1:8000/v1/devices
curl -i -H "X-API-Key: $EVENT_PRODUCER_KEY" -H 'Content-Type: application/json' \
  -d '{"device_id":"sensor-demo","event_id":"e-001","occurred_at":"2026-11-11T12:00:00Z","temperature":35,"humidity":45,"state":"running"}' \
  http://127.0.0.1:8000/v1/readings
curl -G -H "X-API-Key: $EVENT_ANALYST_KEY" \
  --data-urlencode 'device_id=sensor-demo' http://127.0.0.1:8000/v1/reception/counts
```

Datos ficticios: repetir el alta devuelve 409; repetir la lectura válida devuelve
200 y su reading_id original. Sin worker la lectura queda pendiente. Ejemplos de
históricos, estadísticas, alertas y API genérica en la [guía API](docs/api.md).

## API y documentación del código

- [Guía de API, contratos, ejemplos y errores](docs/api.md).
- `/openapi.json`: OpenAPI generado por Utoipa desde rutas y tipos Rust.
- `/docs`: visor local sin dependencias CDN.
- `cargo run --locked -- openapi > openapi.json`: exportar el contrato sin base de datos.
- `cargo doc --locked --no-deps --open`: documentación Rust de módulos y contratos.
- [Arquitectura y guía de contribución](docs/desarrollo.md), [matriz regla → prueba](docs/escenario.md).
- [Runbook operativo y controles de entrega](docs/operaciones.md).
- [Flujo DevOps actual: PR → CI → GHCR → aprobación → K3s](docs/devops.md), además de Terraform, drift y operación de VM.

## Calidad y pruebas

```bash
cargo fmt --all -- --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked --all-targets
RUSTDOCFLAGS='-D warnings' cargo doc --locked --no-deps

# Obligatorio para aceptación: PostgreSQL activo y TEST_DATABASE_URL definido.
# Debe nombrar una BD test_* o *_test; DATABASE_URL, si existe, debe coincidir.
cargo test --locked --test postgres -- --ignored --nocapture
cargo test --locked --test metrics -- --ignored --nocapture
```

Las pruebas PostgreSQL están marcadas `ignored` para separar unitarias de integración, **no para omitirlas en CI**: el job `postgres` las ejecuta explícitamente y falla si falta la base. Cada prueba usa fuentes únicas; no se truncan tablas ni se elimina información ajena.

Experimento real de recuperación y durabilidad, contra **otro puerto libre y una base de prueba dedicada**:

```bash
export POSTGRES_USER=events POSTGRES_DB=events_test POSTGRES_PORT=15434
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}"
cargo build --locked --bin event-service
cargo run --locked --example verify_system
# Con Podman: CONTAINER_ENGINE=podman cargo run --locked --example verify_system
```

El experimento crea su propio contenedor/volumen: comprueba `200 → 503 → 200` en el mismo proceso API y después reinicia API + PostgreSQL para comparar el evento completo. Al salir detiene el contenedor, **conservando contenedor y volumen**; imprime sus nombres para limpieza manual. Logs en `artifacts/system-api.log`. No ejecutarlo contra producción.

## Contenedor

```bash
docker compose --profile app build api
docker compose up -d --wait postgres
docker compose --profile app run --rm api migrate
docker compose --profile app up -d api
```

Imagen multi-stage sobre distroless, sin shell, con usuario no root, puerto 8000 y migraciones SQL embebidas. No incluir secretos en la imagen. Compose usa la red interna para PostgreSQL. El mismo ejecutable admite `serve`, `process` y `drain`; el procesador debe ejecutarse por separado. Verificación local: `bash scripts/verify-image.sh <imagen>` y `bash scripts/scan-secrets.sh` ([DEV-02](docs/evidencia/DEV-02/index.md)). **Infraestructura Azure/K3s y Terraform** incorporada en el [PR #40](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/40): [guía](docs/infra/README.md). Las imágenes se publican en GHCR desde `main` y desde tags `vX.Y.Z` ([DEV-04](docs/evidencia/DEV-04/index.md)); la entrega controlada está en [DEV-05](docs/evidencia/DEV-05/index.md) y la observabilidad corresponde a D. El Dockerfile no acredita un despliegue en la nube.

## Configuración

| Variable | Predeterminado / contrato |
|---|---|
| `DATABASE_URL` | `postgresql://user:password@host:5432/database`; sin valor, liveness funciona y datos/readiness devuelven 503 |
| `EVENT_PRODUCER_KEY`, `EVENT_ANALYST_KEY` | Obligatorias para rutas protegidas; distintas y no vacías |
| `EVENT_PRODUCER_SOURCE_KEYS` | Opcional: `sensor-a:clave,sensor-b:otra`; una clave puede habilitar varias fuentes |
| `BIND_ADDR` | `127.0.0.1:8000` (contenedor: `0.0.0.0:8000`) |
| `DB_CONNECT_TIMEOUT_SECONDS` | 3; rango 1–60; acota adquisición/conexión del pool |
| `DB_STATEMENT_TIMEOUT_MS` | 5000; rango 100–60000; por sentencia |
| `DB_READ_MAX_RETRIES` | 1; rango 0–5; nunca reintenta escrituras |
| `DB_READ_RETRY_BACKOFF_MS` | 50; rango 0–2000; backoff exponencial asíncrono |
| `RUST_LOG` | `event_service=info,sqlx=off`; no activar logs de SQL en entornos con datos sensibles |
| `PROCESSOR_BATCH_SIZE` | 100; rango 1–1000, para process/drain |
| `PROCESSOR_POLL_MS` | 100; rango 1–60000, espera entre lotes; process reintenta DB transitoria con backoff acotado |
| `WORKER_METRICS_ADDR` | `0.0.0.0:9000`; listener `/metrics` de process, no de drain |
| `WORKER_HEALTH_DIR` | Opcional en local; directorio escribible de heartbeats para las probes exec en K3s |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Sin valor: no exporta trazas. URL completa explícita por ambiente/proceso; no basta el endpoint genérico OTLP |

Las opciones numéricas inválidas de DB usan su predeterminado; los valores inválidos
de batch/poll del procesador terminan con error. Las claves ambiguas o mal formadas
**fallan cerrado**. La configuración se lee al iniciar: para rotar secretos hay que
reiniciar el proceso. Cuerpo HTTP máximo: 4 MiB; el límite de payload de 16 KiB es
del contrato genérico, no un campo de las lecturas ESC3.

## Migración desde la versión Python

Ver [ADR-0004](docs/adr/0004-rust.md) y [persistencia](docs/arquitectura/persistencia.md). Cambiar DSN `postgresql+psycopg://` a `postgresql://`. SQLx conserva tabla, índices y datos del esquema anterior; usa `_sqlx_migrations` y deja `alembic_version` intacta. Hacer backup y verificar compatibilidad en una copia antes de migrar una base existente. No ejecutar ambos gestores de migraciones a la vez.

## Backlog del curso

Los **27 requisitos comunes** se siguen en sus issues originales, junto con los
issues específicos ESC3 y tareas operativas. Una migración de lenguaje no cierra
automáticamente requisitos DevOps ni de observabilidad.

| Grupo | Requisitos e issues |
|---|---|
| **3.1 Aplicación y arquitectura** | COM-01 funciones [#1](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/1), COM-02 límites [#2](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/2), COM-03 persistencia [#3](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/3), COM-04 errores [#4](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/4), COM-05 acceso [#5](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/5), COM-06 trade-offs [#6](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/6) |
| **3.2 DevOps** | DEV-01 versionamiento #7; DEV-02 contenedores #8; DEV-03 CI #9; DEV-04 publicación #10; DEV-05 entrega controlada #11; DEV-06 Terraform Azure #12; DEV-07 estado remoto #13; DEV-08 validación Terraform #14; DEV-09 K3s #15; DEV-10 secretos #16; DEV-11 probes/recursos #17; DEV-12 rollback #18; DEV-13 reconstrucción #19; DEV-14 máximo US$100 acumulados #20 |
| **3.3 Métricas y observabilidad** | MET-01 indicadores #21; MET-02 logs #22; MET-03 métricas #23; MET-04 OpenTelemetry #24; MET-05 dashboards #25; MET-06 alertas #26; MET-07 degradación inducida #27 |

Consultar cada issue en el [backlog canónico](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues). [Evidencias COM](docs/evidencia/README.md) · [contexto](docs/arquitectura/contexto.md) · [módulos](docs/arquitectura/contenedores.md) · [despliegue](docs/arquitectura/despliegue.md) · [errores](docs/arquitectura/errores.md) · [acceso](docs/arquitectura/acceso.md) · [trade-offs](docs/arquitectura/tradeoffs.md).
