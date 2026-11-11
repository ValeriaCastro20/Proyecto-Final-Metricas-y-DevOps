# MET-03 · Corrección del PR 78

Avance parcial de #23: métricas de aplicación y consumidores de desarrollo.
No acredita métricas de infraestructura, correlación con recursos, dashboards,
series del ambiente de defensa ni cumplimiento de SLOs.

## Hallazgos contrastados

- Restaurado el CLI base (`serve`, `migrate`, `process`, `drain`, `openapi`,
  `worker-health`), sus cinco pruebas, reintentos, probes y apagado ordenado.
  La telemetría se inicializa antes del despacho y se vacía tras su resultado.
- `Cargo.lock` actualizado para las seis dependencias. El exporter usa Axum,
  sin las features de listener/push gateway que añadían OpenSSL dinámico a la
  imagen distroless. Se conservan las versiones de `metrics` de este PR.
- `/metrics` usa el handle del recorder global; las macros usan handles de
  `metrics` 0.22. El future HTTP usa `Instrument`, sin un guard entre awaits.
- `reject` persiste `rejected` y su motivo; los contadores se emiten solo después
  de una escritura confirmada, incluidos `accepted` y `duplicate` tras COMMIT.
- Se elimina `counters(None)` del procesamiento. La API consulta únicamente
  pendientes en cada scrape: detecta backlog con el worker detenido y devuelve
  503 si no puede leer la BD, sin anunciar un valor anterior como actual.
- El worker `process` sirve `/metrics` en `WORKER_METRICS_ADDR`
  (`0.0.0.0:9000` por defecto). `drain` no necesita listener. Prometheus consulta
  API:8000 y worker:9000 mediante Services y permisos de red explícitos.
- Grafana anónimo es Viewer, no Admin. Las tres imágenes tienen versión fija;
  los contenedores son no-root, sin escalada/capabilities y con raíz read-only.
  Grafana y Prometheus tienen `emptyDir` para sus datos (no son persistentes).
- SLI-02 conserva nombre y definición, corrigiendo solo su fuente a Prometheus.

No se aplica literalmente la nota de SLI-01 sobre un gauge actualizado por
`Store::process`: esa implementación se reemplazó por lectura desde la API para
no congelar el valor al caer el worker. Tampoco se usa `runAsNonRoot: false` en
Jaeger: el objetivo de seguridad requiere `true`, con UID 10001.
La ruta `/metrics` de la API ya existía: se conserva, corrigiendo su recorder.

## Reproducción local

```sh
npm ci
cargo fmt --all -- --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked --all-targets
RUSTDOCFLAGS='-D warnings' cargo doc --locked --no-deps
# PostgreSQL 16 dedicado, TEST_DATABASE_URL exportada, sin DATABASE_URL distinta:
cargo test --locked --test postgres -- --ignored --nocapture
cargo test --locked --test metrics -- --ignored --nocapture
python3 -m unittest discover -s scripts/tests -p test_k8s_render.py -v
kubeconform -strict -summary -kubernetes-version 1.35.0 kubernetes/observability
docker build -t localhost/event-service:pr78-review .
```

Las pruebas de métricas comprueban recorder global, labels de rutas acotados,
recibos y motivos persistidos, los tres outcomes, backlog sin worker y error de
scrape al cerrar la conexión. Las pruebas PostgreSQL existentes conservan la
aceptación ESC3 con 1.000 lecturas, duplicados y recuperación del worker.

Resultados locales:

- Formato, Clippy con `-D warnings` y rustdoc con `-D warnings`: OK.
- `cargo test --locked --all-targets`: 26 pruebas OK; 13 pruebas de BD omitidas
  por diseño y ejecutadas explícitamente a continuación.
- PostgreSQL 16, target `postgres`: 12/12 OK; target `metrics` con `--ignored`:
  1/1 OK, usando una BD efímera dedicada `test_pr78`.
- Contratos offline Kubernetes: 10/10 OK. Kubeconform 0.8.0 con checksum del
  workflow, schemas 1.35: 11/11 recursos de observabilidad válidos.
- Smoke de procesos reales: API `/metrics` HTTP 200 con backlog; worker
  `/metrics` HTTP 200 con `esc3_processor_duration_seconds_bucket`; ambos
  terminaron con código 0 tras SIGTERM. Buckets configurados incluyen 0.5 s.
- `promtool check config`: configuración válida y dos reglas válidas.
  Prometheus v3.2.1 se ejecutó no-root/read-only y recolectó ambos endpoints:
  2/2 targets UP. Las consultas de backlog y duración devolvieron series
  ([resultado](prometheus-smoke.json)). Para este smoke local se sustituyeron
  únicamente los targets DNS de Kubernetes por los puertos loopback efímeros;
  no acredita resolución DNS ni NetworkPolicy en un cluster.
- `cargo run --locked -- openapi`: JSON válido con `/v1/readings`, sin BD.

Jaeger `1.68.0` se inició localmente con `--read-only --user 10001:10001
--cap-drop ALL --security-opt no-new-privileges`: `/api/services` respondió 200
y OTLP HTTP `/v1/traces` aceptó una petición. La compatibilidad read-only se
validó antes de activarla en el manifiesto. Esta imagen v1 está fuera de soporte;
migrar a Jaeger v2 requiere un cambio de configuración separado.

CodeRabbit local: `coderabbit review --agent` no pudo autenticar la sesión o
el acceso al proveedor Git. No se cuenta como revisión completada.
Terraform y despliegue Azure/Kubernetes: N/A, no se modifica infraestructura
Terraform ni se dispone de una ejecución autorizada en el ambiente.

## Segunda revisión del PR 78

Los tres hallazgos seguían vigentes y se corrigieron:

- Añadidas políticas recíprocas de ingreso/egreso para OTLP HTTP, usando los
  selectores reales de `event-service` y del Service `jaeger-collector`, solo
  TCP 4318 y en el mismo namespace de desarrollo.
- El Ingress de producción deja de usar `/` como prefijo global. Solo enruta
  `/v1` y las rutas exactas de salud, documentación y OpenAPI. `/metrics` queda
  fuera del Ingress; el Service y el handler interno no cambian. No se añade
  caché porque el bloqueo se resuelve en el Ingress.
- OTLP 0.15, `exporter/http/mod.rs`, `resolve_endpoint`, añade `/v1/traces` a la
  URL base configurada. Se elimina ese sufijo de `with_endpoint`, conservando
  el host y puerto, para no generar `/v1/traces/v1/traces`.

Validación local: 11/11 contratos del renderer (incluida exclusión pública de
`/metrics` y preservación de rutas API), 13/13 recursos de observabilidad y
3/3 recursos de Ingress/NetworkPolicy renderizados válidos con Kubeconform 1.35
(Issuer excluido por ser CRD). Se verificaron los selectores recíprocos y el
puerto de ambas políticas contra el Service. Formato y Clippy: OK; 26 pruebas
Rust sin BD: OK; rustdoc: OK. La prueba de métricas confirma que el acceso
interno sigue usando el recorder global. No se reejecutó aceptación de BD
local en esta revisión: no cambia SQL ni procesamiento. No se desplegó en cluster;
la validación estática no demuestra el enforcement de NetworkPolicy/Ingress.

## Ciclo de revisión manual y corrección

La revisión manual de `ca6663f` confirmó tres pendientes: conectividad
Grafana→Prometheus bloqueada por default-deny, prueba PostgreSQL de métricas
omitida por CI y YAML de observabilidad fuera del alcance de Kubeconform en CI.

Correcciones:

- Políticas recíprocas Grafana→Prometheus solo TCP 9090, sin abrir otros peers.
- El job `postgres` ejecuta también el target `metrics` con `--ignored` y guarda
  `artifacts/metrics.txt`; reutiliza su BD dedicada y falla ante errores.
- El job `manifests` valida el directorio de observabilidad y el Ingress público
  renderizado (Issuer excluido por ser CRD). Usa `bash`/`pipefail` explícitos para
  no ocultar fallos del renderer detrás de las tuberías.
- `scripts/test-observability.py` añade tres contratos de conectividad y Services
  con labels reales, casos permitidos/denegados y dependencia PyYAML 6.0.3 fijada
  en CI. Es un modelo acotado a los selectores usados aquí, no un test de CNI.

Segunda pasada: sin nuevos defectos bloqueantes detectados en el diff revisado.
Se retiró en memoria cada permiso nuevo por separado y ambos controles negativos
detectaron el bloqueo, sin editar los manifiestos para realizar esa prueba.

Validación local del ciclo:

- 23/23 pruebas Python existentes y 3/3 contratos nuevos: OK.
- Comandos exactos del paso de esquemas del workflow: 52/52 recursos válidos,
  incluidos 15 de observabilidad y 3 de Ingress/NetworkPolicy.
- Comandos exactos del paso de aceptación PostgreSQL del workflow: 12/12 pruebas
  PostgreSQL y 1/1 regresión de métricas con BD dedicada: OK.
- La revisión completa previa ejecutó además las 26 pruebas Rust sin BD,
  Clippy, rustdoc, OpenAPI, recuperación real, cardinalidad HTTP, trazas reales
  en Jaeger, pruebas positivas/negativas de alertas e inicialización/privilegios
  PostgreSQL: OK. El código Rust y el lockfile no cambian en este ciclo.
- Imagen `localhost/event-service:pr78-manual`: compilación release `--locked`,
  hardening y `scripts/verify-image.sh`: OK; SBOM generados en `artifacts/image/`.
  Trivy: 0 HIGH/CRITICAL en crates, 0 CRITICAL en imagen. Reportó una HIGH en
  `libssl3` de la base distroless heredada de main (CVE-2026-84782); no se declara
  la imagen libre de vulnerabilidades. Actualizar esa base queda separado de
  este cambio de métricas; el gate existente bloquea críticas con parche.
- Gitleaks: 98 commits, sin hallazgos. Formato Rust y `git diff --check`: OK.

No se eluden CodeRabbit, la aprobación humana ni CI. Sigue pendiente comprobar
el enforcement real de las políticas y el Ingress en el ambiente autorizado.
