# MET-02 · Logs de recepción y procesamiento ESC3

Refs #22. PR dependiente del cambio de propagación MET-04; no cierra el requisito.

`Store::receive` y `reject` emiten `reading reception committed` **solo después
de confirmar la escritura**: `receipt_id`, `outcome`, motivo seguro cuando existe
y `reading_id` para aceptaciones/duplicados. Un rechazo no tiene lectura persistida:
no se inventa un reading_id; se registra `reading_id_present=false`, se omite el
campo y se correlaciona mediante `receipt_id` y el request/span HTTP.

`Store::process` emite `reading processing committed` por lectura únicamente tras
el COMMIT del lote, con `reading_id` y `outcome=processed`. Ambos registros incluyen
`trace_id`/`span_id` si hay contexto válido. No se registran claves, cuerpos, event_id
ni errores SQL. Las fallas de auth o DB no se presentan como recibos durables;
conservan el log HTTP de error existente. JSON continúa en stderr como antes.

## Verificación y consulta

La prueba PostgreSQL `api_context_survives_inbox_and_parents_worker_span` captura y
parsea JSON real: aceptación, duplicado, tres categorías de rechazo y procesamiento,
con IDs coincidentes, sin clave ni campo privado del cuerpo. Un pool cerrado no
produce registros de aceptación/rechazo confirmado.

Validación local: formato, Clippy con `-D warnings`, all-targets y rustdoc; 13
pruebas PostgreSQL 16 ejecutadas explícitamente y prueba del gauge de backlog.
CodeRabbit CLI requiere reautenticación; revisión solicitada en GitHub.

Sobre un archivo de logs JSON de API y worker (reemplazar UUID/trace):

```bash
jq -c 'select(.fields.reading_id == "UUID" or .fields.trace_id == "TRACE")' logs.jsonl
jq -c 'select(.fields.receipt_id == "UUID-RECIBO")' logs.jsonl
```

Pendiente: validar búsqueda y retención en el ambiente, unificar versión/ambiente
del esquema y aportar consulta real de defensa. Estos logs no sustituyen el ledger
ni garantizan entrega de logs ante crash justo después de COMMIT.
