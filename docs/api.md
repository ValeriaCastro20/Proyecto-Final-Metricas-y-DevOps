# API HTTP · Event Service en Rust

Base local: `http://127.0.0.1:8000`. JSON UTF-8. Contrato en `/openapi.json`,
generado desde las rutas/tipos de `src/api.rs`, `src/domain.rs` y `src/scenario/`.
`/docs` muestra ese JSON sin CDN: no es un Swagger UI interactivo.

**ESC3 usa `/v1/devices` y `/v1/readings`.** `/v1/events` es un contrato genérico
de compatibilidad: no alimenta el inbox, las alertas ni los contadores ESC3.
Esta guía describe código de main; la versión disponible en un ambiente depende
del digest desplegado. Entrega y controles: [flujo DevOps](devops.md).

## Autenticación

Enviar `X-API-Key`. `producer` permite ingesta, `analyst` permite consultas.
Las claves por fuente autorizan solo los dispositivos/fuentes asociados; no dan
alta de dispositivos ni cambian límites. Eso requiere el producer **global**.
Sin clave válida: 401; rol/fuente insuficiente: 403. Cabeceras API-key duplicadas
se rechazan. No enviar secretos en URLs, usar TLS fuera de loopback y no seguir
redirecciones con credenciales. Salud, contrato, visor y métricas internas no
requieren clave en la aplicación; eso no implica exposición pública de `/metrics`.

## API de mantenimiento · ESC3

### Dispositivo y lectura

`DeviceCreate` requiere `id`, `facility_id` y `limits`. Ambos identificadores son
ASCII, 1–64 caracteres, patrón `[A-Za-z0-9][A-Za-z0-9_-]*`. Los límites contienen
`temperature_min`, `temperature_max`, `humidity_min`, `humidity_max`, finitos y
con mínimo < máximo dentro de los rangos físicos. La respuesta `Device` devuelve
estos límites como campos planos, además de `id`, `facility_id` y `created_at`.

`ReadingCreate` requiere todos los campos siguientes; no admite campos adicionales:

```json
{
  "event_id": "e-001",
  "device_id": "sensor-demo",
  "occurred_at": "2026-11-11T12:00:00Z",
  "temperature": 35.0,
  "humidity": 45.0,
  "state": "running"
}
```

- `event_id`: 1–128 caracteres, sin NUL, único **por dispositivo**.
- `occurred_at`: RFC3339 con zona, normalizado a UTC; es el instante de generación.
- Temperatura entre **−80 y 150 °C**, humedad entre **0 y 100 %**, ambas finitas;
  `state`: `running`, `stopped` o `fault`. Rangos/estados declarados por el equipo.
- Superar un límite de negocio no rechaza la lectura: el worker genera la alerta.
  Los límites se guardan al recibir; cambiarlos no reinterpreta lecturas previas.

### Rutas ESC3

| Método y ruta | Rol | Respuesta / significado |
|---|---|---|
| `POST /v1/devices` | producer global | 201, dispositivo; ID repetido: 409 |
| `GET /v1/devices` | analyst | 200, arreglo paginado de dispositivos |
| `GET /v1/devices/{device}` | analyst | 200, dispositivo; inexistente: 404 |
| `PUT /v1/devices/{device}/limits` | producer global | 200, dispositivo con nuevos límites; cuerpo: `Limits` |
| `POST /v1/readings` | producer global o fuente autorizada | 202 aceptada, 200 duplicada, 422 rechazo durable; cuerpo de respuesta: `Receipt` |
| `GET /v1/receipts/{id}` | analyst | 200, recibo durable con metadatos; inexistente: 404 |
| `GET /v1/devices/{device}/readings` | analyst | 200, arreglo de lecturas aceptadas, incluidas pendientes |
| `GET /v1/devices/{device}/statistics` | analyst | 200, count y min/max/avg de temperatura/humedad **procesadas** |
| `GET /v1/devices/{device}/alerts` | analyst | 200, arreglo de alertas de negocio persistidas |
| `GET /v1/reception/counts` | analyst | 200, contadores consistentes, no paginados |
| `GET /v1/rejections` | analyst | 200, arreglo paginado de recibos rechazados |

No existe lote de lecturas ESC3: enviar una solicitud por lectura. El endpoint
genérico `/v1/events/batch` no es un sustituto.

### Aceptación, duplicados y rechazos

`POST /v1/readings` devuelve un recibo como este (UUIDs ilustrativos):

```json
{
  "id": "a3f003d8-2bea-45ec-ae94-0f8d8db22971",
  "reading_id": "f3be78d1-5042-4ec3-b9da-54cbce1ae949",
  "outcome": "accepted",
  "reason": null
}
```

| HTTP | outcome | Garantía |
|---|---|---|
| 202 | `accepted` | Lectura y recibo confirmados por COMMIT; **no significa procesamiento terminado** |
| 200 | `duplicate` | Recibo nuevo, mismo `reading_id`; no sobrescribe lectura ni crea trabajo adicional |
| 422 | `rejected` | Recibo durable con `reading_id=null` y motivo `invalid_format`, `invalid_fields` o `unknown_device` |

Se valida antes de deduplicar: una retransmisión inválida es rechazo. La clave de
deduplicación es `(device_id,event_id)`; una retransmisión válida no sustituye los
datos originales aunque cambien sus mediciones. Los fallos de autenticación,
autorización o tamaño HTTP no crean recibo de lectura. Una DB no disponible da 503
con el error común, no un recibo que afirme haber aceptado/rechazado durablemente.

Si se pierde la respuesta, consultar el recibo si se conoce su ID o retransmitir la
misma lectura con el mismo identificador. No interpretar un timeout o COMMIT
incierto como pérdida demostrada ni generar otro `event_id` automáticamente.

### Consultas y contadores

- Históricos, estadísticas y alertas requieren `from` y `to`, RFC3339 con zona,
  `from < to`, por generación y ventana UTC **[from,to)**. No por recepción.
- Sus listados admiten `limit` 1–1000 (100), `offset` 0–100000 (0). Las estadísticas
  validan esos parámetros, pero no limitan el cálculo con ellos. Sin muestras,
  `count=0` y min/max/avg son null.
- `/v1/devices` y `/v1/rejections` admiten `limit`, `offset` y filtro `device_id`.
  Rechazos se ordenan por `received_at,id`; no admiten filtro temporal.
- `/v1/reception/counts` admite `device_id`; también valida limit/offset, pero no
  pagina los contadores. Se leen en un único snapshot SQL:

```text
received = validated + rejected
validated = accepted + duplicates
accepted = processed + pending
received = processed + pending + duplicates + rejected
```

Lecturas se ordenan por `occurred_at,id` incluso con llegada fuera de orden;
`processed_at=null` indica pendiente. Un dispositivo inexistente da arreglos
vacíos en histórico/alertas y estadísticas sin muestras, no el 404 de detalle.
Un filtro por dispositivo excluye rechazos sin identificador seguro; sí cuentan
en el total global. Se rechazan query params desconocidos.

### Ejemplo mínimo ESC3

Con API, DB migrada y claves exportadas según el [README](../README.md#arranque-local):

```bash
BASE_URL=http://127.0.0.1:8000
# Identificador nuevo por ejecución; repetir la misma alta da 409.
DEVICE_ID="demo-$(date +%s)"
curl -i -H "X-API-Key: $EVENT_PRODUCER_KEY" -H 'Content-Type: application/json' \
  --data-binary @- "$BASE_URL/v1/devices" <<JSON
{"id":"$DEVICE_ID","facility_id":"instalacion-demo","limits":{"temperature_min":0,"temperature_max":30,"humidity_min":20,"humidity_max":80}}
JSON
curl -i -H "X-API-Key: $EVENT_PRODUCER_KEY" -H 'Content-Type: application/json' \
  --data-binary @- "$BASE_URL/v1/readings" <<JSON
{"device_id":"$DEVICE_ID","event_id":"e-001","occurred_at":"2026-11-11T12:00:00Z","temperature":35,"humidity":45,"state":"running"}
JSON
curl -G -H "X-API-Key: $EVENT_ANALYST_KEY" \
  --data-urlencode "device_id=$DEVICE_ID" "$BASE_URL/v1/reception/counts"
curl -G -H "X-API-Key: $EVENT_ANALYST_KEY" \
  --data-urlencode 'from=2026-11-11T00:00:00Z' \
  --data-urlencode 'to=2026-11-12T00:00:00Z' \
  "$BASE_URL/v1/devices/$DEVICE_ID/readings"
```

Repetir el segundo POST sin cambiar `DEVICE_ID`/`event_id` produce 200 y el mismo
`reading_id`. Ejecutar `cargo run --locked -- process` en otra terminal con el
mismo entorno para procesar y generar la alerta de temperatura alta. Consultar
`/statistics` y `/alerts` con esa misma ventana. Para carga y recuperación seguir
[escenario](escenario.md), no ejecutar degradaciones sobre producción.

## API genérica · compatibilidad

Las reglas 201/409 siguientes son de `/v1/events`, **no** de la recepción ESC3.

### Evento genérico

```json
{
  "source": "sensor-a",
  "external_id": "e-001",
  "type": "temperature",
  "occurred_at": "2026-10-21T12:00:00Z",
  "payload": {"value": 23.5}
}
```

- `source`, `type`: `[A-Za-z0-9][A-Za-z0-9_-]*`, 1–64 caracteres ASCII.
- `external_id`: cadena no vacía, máximo 128 caracteres Unicode.
- `occurred_at`: RFC3339 con zona, nunca timestamp numérico ni fecha sin offset. Respuestas normalizadas a UTC.
- `payload`: objeto JSON, máximo 16384 bytes al serializar compacto UTF-8. Se aceptan objetos/arreglos anidados, booleanos y null; no NaN ni Infinity.
- Los números JSON se conservan sin conversión silenciosa a float64 durante ingesta/lectura (`serde_json/arbitrary_precision`); aplican los límites de representación JSONB de PostgreSQL. Las estadísticas sí se devuelven como float64.
- Campos adicionales rechazados en eventos, envoltura de lote y query params.
- La respuesta añade `id` UUID v4 e `ingested_at` UTC. `(source, external_id)` es único; un conflicto no reemplaza el evento existente.

### Rutas genéricas y operativas

| Método y ruta | Rol | Respuesta exitosa |
|---|---|---|
| `POST /v1/events` | producer | 201, evento completo confirmado |
| `POST /v1/events/batch` | producer | 201, `{"inserted":2,"events":[...]}` |
| `GET /v1/events/{id}` | analyst | 200, evento; UUID inexistente: 404 |
| `GET /v1/events` | analyst | 200, `total`, `limit`, `offset`, `window`, `filters`, `items` |
| `GET /v1/analysis/counts` | analyst | 200, `total`, `group_by`, `window`, `buckets:[{key,count}]` |
| `GET /v1/analysis/timeseries` | analyst | 200, `total`, `bucket`, `window`, `filters`, `points:[{bucket_start,count}]` |
| `GET /v1/analysis/summary` | analyst | 200, resumen descrito abajo |
| `GET /health/live` | público | 200, `{"status":"alive"}` independiente de DB |
| `GET /health/ready` | público | 200, `{"status":"ready"}` tras `SELECT 1`; DB caída: 503 |
| `GET /openapi.json`, `GET /docs` | público | Contrato generado y visor |
| `GET /metrics` | sin clave, acceso interno | Texto Prometheus; si la consulta de pendientes configurada falla, 503 |

### Lotes

```bash
curl -H "X-API-Key: $EVENT_PRODUCER_KEY" -H 'Content-Type: application/json' \
  -d '{"events":[{"source":"sensor-a","external_id":"e-002","type":"temperature","occurred_at":"2026-10-21T12:05:00Z","payload":{"value":24}}]}' \
  http://127.0.0.1:8000/v1/events/batch
```

`events` contiene 1–100 elementos. Todos confirman juntos; duplicados internos o contra DB provocan 409 y rollback completo. Se conserva el orden de entrada en la respuesta. Se verifican todas las fuentes antes de escribir. Nunca se reintenta automáticamente una escritura: si se pierde la conexión durante COMMIT, verificar el resultado mediante consulta; reenviar puede devolver 409.

### Consultas

Todas las consultas de listado/análisis requieren `from` y `to`, RFC3339 con zona y `from < to`. Ventana semiabierta UTC `[from,to)`. Para offsets `+02:00`, usar `--data-urlencode` (no un `+` literal en URL).

| Ruta | Parámetros adicionales |
|---|---|
| `/v1/events` | `source`, `type` opcionales; `limit` 1–100 (50), `offset` 0–100000 (0) |
| `/v1/analysis/counts` | `group_by=type\|source` obligatorio; no admite filtros adicionales |
| `/v1/analysis/timeseries` | `source`, `type` opcionales; `bucket=minute\|hour\|day` (hour) |
| `/v1/analysis/summary` | `source`, `type` opcionales; `numeric_field` identificador simple (value) |

Series: máximo 7 días con `minute`, 90 con `hour`, 366 con `day`. Solo devuelve buckets con datos, truncados en UTC; no rellena ceros. Conteos y resúmenes no limitan el rango temporal: el timeout SQL limita cada sentencia, no el coste total de exploración. Listados se ordenan por `occurred_at ASC, id ASC`; conteos por clave ascendente.

```bash
curl -G -H "X-API-Key: $EVENT_ANALYST_KEY" \
  --data-urlencode 'from=2026-10-21T00:00:00Z' --data-urlencode 'to=2026-10-22T00:00:00Z' \
  --data-urlencode 'source=sensor-a' --data-urlencode 'limit=10' http://127.0.0.1:8000/v1/events
curl -G -H "X-API-Key: $EVENT_ANALYST_KEY" \
  --data-urlencode 'from=2026-10-21T00:00:00Z' --data-urlencode 'to=2026-10-22T00:00:00Z' \
  --data-urlencode 'bucket=hour' http://127.0.0.1:8000/v1/analysis/timeseries
curl -G -H "X-API-Key: $EVENT_ANALYST_KEY" \
  --data-urlencode 'from=2026-10-21T00:00:00Z' --data-urlencode 'to=2026-10-22T00:00:00Z' \
  --data-urlencode 'numeric_field=value' http://127.0.0.1:8000/v1/analysis/summary
```

Resumen: `total_events`, `unique_sources`, `unique_types`, `first_occurred_at`, `last_occurred_at`, `by_type`, `by_source`, `numeric_summary`, `window`, `filters`. `numeric_summary` contiene `field`, `samples`, `min`, `max`, `avg`: solo cuenta valores JSON numéricos cuya magnitud no supera `f64::MAX`, nunca booleanos ni cadenas numéricas. Valores mayores, como `1e400`, permanecen almacenados pero no participan en estadísticas. Sin muestras: `samples=0`, estadísticas null. Sin eventos: fechas null y agrupaciones vacías. Las estadísticas se agregan como numeric y se convierten a float64 en Rust, evitando errores SQL de desbordamiento; magnitudes extremadamente pequeñas pueden redondearse a cero. No están destinadas a cálculos monetarios de precisión arbitraria. Listado y resumen usan snapshots repetibles para coherencia entre sus consultas.

`external_id`, las cadenas del payload y sus claves no admiten U+0000 (NUL), que PostgreSQL no puede representar: se rechaza con 422 antes de acceder al almacenamiento.

## Errores y correlación

```json
{"error":{"code":"DUPLICATE","message":"Event already exists.","request_id":"req-123"}}
```

| HTTP | Código | Mensaje fijo |
|---|---|---|
| 401 | `UNAUTHENTICATED` | Authentication required. |
| 403 | `FORBIDDEN` | Access denied. |
| 404 | `NOT_FOUND` | Resource not found. |
| 405 | `INVALID_INPUT` | Invalid request. |
| 409 | `DUPLICATE` | Event already exists. |
| 422 | `INVALID_INPUT` | Invalid request input. |
| 503 | `DEPENDENCY_UNAVAILABLE` | Dependency unavailable. |
| 500 | `INTERNAL_ERROR` | Internal server error. |

Este sobre de error se usa en fallos comunes y en la API genérica. **Excepción:**
un rechazo registrado de `/v1/readings` devuelve `Receipt` con 422, no este sobre.
JSON/content-type inválidos dentro del límite de recepción ESC3 pueden generar ese
recibo; auth fallida o cuerpo mayor de 4 MiB no lo generan. Los errores comunes de
extracción (incluido tamaño) y query params se normalizan a 422. Métodos no
admitidos devuelven 405 y conservan `Allow`. No se reflejan valores de entrada ni
errores SQL. Si coinciden varios fallos, no se garantiza prioridad salvo que se
autentica antes de acceder al repositorio.

Todas las respuestas incluyen `X-Request-ID`. Se acepta una única cabecera con patrón `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`; de lo contrario se genera UUID v4. Los errores registran código, estado, plantilla de ruta e ID; nunca payload, claves, DSN ni URL con valores del cliente. TLS, rate limiting y límites de conexión del proxy deben configurarse en el despliegue.

Un `traceparent` W3C válido puede propagarse al span HTTP y, para lecturas nuevas,
guardarse en el inbox para el worker. La exportación requiere
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` explícito en ambos procesos. Logs JSON en
stderr incluyen receipt_id y reading_id cuando existe; con trazas activas añaden
trace_id/span_id. No se propagan baggage ni claves; IDs de dominio no son etiquetas
de métricas. Detalles y límites: [MET-02](evidencia/MET-02/index.md) y
[MET-04](evidencia/MET-04/index.md). `X-Request-ID` correlaciona HTTP, no reemplaza
el contexto durable ni implica que se exportó una traza.
