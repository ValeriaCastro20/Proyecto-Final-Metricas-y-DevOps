# MET-04 · Propagación API → inbox → worker

Refs #24. Implementación ejecutable, no evidencia de despliegue ni cierre del requisito.

- `api::correlate` extrae un `traceparent` W3C válido (cabeceras repetidas se ignoran).
- La aceptación guarda el contexto del span HTTP junto con la lectura en la misma
  transacción, antes del 202. Un duplicado no reemplaza el contexto original.
- `Store::process` crea un span `process_reading` consumidor por lectura con el
  padre persistido, `reading_id`, duración y estado. Su vida incluye el COMMIT del
  lote; un error SQL o de COMMIT marca los spans afectados como ERROR. Un reintento
  puede crear otro span, pero no otra lectura ni otra alerta de negocio.
- No se guardan baggage, tracestate, credenciales ni el cuerpo en los atributos.
  Filas históricas, contexto inválido o telemetría deshabilitada no impiden procesar.
- Ambos procesos requieren `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` explícito. Los
  recursos distinguen `event-service-api` de `event-service-worker`.

## Verificación local

PostgreSQL 16 dedicado y prueba
`cargo test --locked --test postgres api_context -- --ignored --nocapture`:
verifica padre remoto → span HTTP → contexto durable → span consumidor desde otro
pool, conservación en duplicados y drenado con contexto ausente/inválido. Usa un
schema propio para evitar que workers de otras pruebas consuman su fixture.
El exportador de prueba inspecciona spans reales del SDK, no solo strings de logs.

Validación local del cambio: `cargo fmt --all -- --check`, Clippy con todos los
targets/features y `-D warnings`, `cargo test --locked --all-targets`, las 13 pruebas
PostgreSQL ignoradas (ejecutadas explícitamente, también en paralelo) y rustdoc con
`-D warnings`. CodeRabbit CLI no pudo revisar por `reauthentication_required`;
se solicita revisión en el PR, sin contar ese intento como aprobación.

## Pendiente para aceptación

Capturar una traza API/worker consultable en el backend del entorno de defensa,
correlacionarla con logs y métricas y verificar exportación/red para ambos procesos.
El SDK usa su muestreo por defecto ParentBased/AlwaysOn: un padre remoto no
muestreado puede ocultar errores posteriores. No hay política especial de errores,
exemplars ni retención acreditada; deben definirse y probarse antes de cerrar MET-04.
Los spans por lectura cubren la transacción compartida del lote, no son mediciones
aisladas de CPU por lectura. SQL conserva dos escrituras por lote (no por lectura),
sin aumentar los viajes a DB según el tamaño del lote. Repetir carga y medir latencia
en el entorno, sin asumir que mantiene el SLO.

## Revisión CodeRabbit

La revisión GitHub de `77bee5a` detectó dos problemas válidos: IDs W3C demasiado
cortos aceptados por el SDK y consultas secuenciales por lectura que podían agotar
las sondas. Se valida ancho/hex antes de extraer (regresión `00-1-1-00`) y se
restauran INSERT/UPDATE por lote en una única transacción, manteniendo spans por
lectura hasta el COMMIT y las sondas existentes para detectar bloqueos.
