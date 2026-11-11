# Workloads del escenario en K3s · DEV-09

**Estado: implementación para revisar y ejecutar; no desplegada por este cambio.** No reemplaza Terraform ni modifica la VM. `resources.json` es la fuente del renderer, no un archivo para aplicar directamente. JSON es un formato de manifiesto admitido por Kubernetes.

## Diseño

| Recurso por namespace | Propósito |
|---|---|
| `eventos-development` / `eventos-production` | Configuración, Secrets, DB y datos independientes; no son clústeres separados |
| `StatefulSet/postgres`, Service headless y PVC `data-postgres-0` | PostgreSQL 16 con disco `local-path` de 2 GiB; sin NodePort/LoadBalancer |
| `ConfigMap/postgres-init` | Roles distintos para migración y runtime, solo al inicializar un volumen vacío |
| `Job/event-service-migrate-<digest16>` | `migrate` explícito con identidad DDL; mismo digest que API y worker |
| `Deployment/event-service-api` | `serve`, Service interno en 8000, readiness DB y liveness del proceso |
| `Deployment/event-service-worker` | `process`, probes por `exec` con `worker-health`, solo credencial DB; Service `event-service-worker-metrics` en 9000 al instalar los manifiestos de observabilidad |
| `ServiceAccount/event-service` | Sin token montado ni permisos RBAC concedidos |
| `ServiceAccount/event-service-deployer` | Solo actualiza workloads y crea Jobs de su namespace; sin acceso a la API de Secrets (ver alcance en DEV-10) |
| `NetworkPolicy` | Todo denegado salvo DNS y event-service → PostgreSQL:5432 |

La imagen de aplicación se exige por digest del repositorio GHCR del proyecto. PostgreSQL también se exige por digest del repositorio oficial. El renderer rechaza tags, repositorios distintos y ambientes arbitrarios. No instala herramientas ni invoca `kubectl`, Azure o Docker.

Los límites iniciales son **estimaciones, no mediciones de capacidad**: API/worker 100m/128Mi solicitados y 500m/256Mi máximos; DB 250m/256Mi solicitados y 1 CPU/1Gi máximo. El Job usa 100m/128Mi y 500m/256Mi. Revisar con carga en #17 antes de afirmar dimensionamiento validado. El worker reinicia si el proceso falla, pero `Running` no acredita progreso: verificar lecturas procesadas/backlog (#17 y observabilidad).

## Prerrequisitos para un operador autorizado

- K3s `v1.35.2+k3s1`, nodo `Ready`, StorageClass `local-path`, `kubectl` conectado por el túnel documentado en [infraestructura](../docs/infra/README.md). No abrir 6443 a Internet.
- Python 3 solo para renderizar. El runtime sigue siendo Rust.
- Imagen de aplicación publicada y verificada: obtener el digest y commit de `publicacion.json` del workflow **Publicar imagen**, y comprobar `gh attestation verify "oci://$IMAGE" --repo marchelo23/Proyecto-Final-Metricas-y-DevOps`. No reutilizar los digests ficticios de las pruebas de esquema.
- PostgreSQL **16 bookworm, UID 999**. Digest amd64 probado localmente: `docker.io/library/postgres@sha256:5264710be20f409750ac6dc4e5706dcef929c87e241605463f0f9aefa932a8d9` (16.15). Revisar vulnerabilidades antes de promoverlo; la prueba de init no es un escaneo.
- Configurar y revisar el contexto/namespace; disponer de respaldo y espacio libre antes de tocar una DB existente. No borrar namespaces/PVC para reintentar.
- GHCR público o un `imagePullSecret` de lectura configurado en el ServiceAccount antes de lanzar migración/workloads. No poner tokens en los manifiestos ni usar credenciales de publicación para el pull.

## Secrets por namespace (fuera de Git)

`bash scripts/k8s-secrets.sh <ambiente>` crea los tres Secrets con valores aleatorios distintos por ambiente. Los valores no pasan por argumentos, archivos ni la salida del comando. Si ya existen no los modifica, y si existe solo una parte se detiene, porque regenerarlos dejaría contraseñas distintas a las de los roles de la base. En la VM: `KUBECTL="sudo k3s kubectl" sh scripts/k8s-secrets.sh development`.

| Secret | Claves requeridas |
|---|---|
| `postgres-credentials` | `POSTGRES_USER=bootstrap_admin`, `POSTGRES_DB=eventos`, `POSTGRES_PASSWORD`, `EVENT_MIGRATION_PASSWORD`, `EVENT_RUNTIME_PASSWORD` |
| `event-service-migration` | `DATABASE_URL=postgresql://eventos_migrator:<contraseña codificada como URL>@postgres:5432/eventos` |
| `event-service-credentials` | `DATABASE_URL=postgresql://eventos_runtime:<contraseña codificada como URL>@postgres:5432/eventos`, `EVENT_PRODUCER_KEY`, `EVENT_ANALYST_KEY` |

Las contraseñas de los DSN deben corresponder a las de los roles del primer Secret; usar contraseñas aleatorias distintas (por ejemplo, hexadecimales) y claves de API distintas por ambiente. `POSTGRES_USER` debe ser `bootstrap_admin`, nunca uno de los roles de aplicación. Esa credencial privilegiada no llega a los Pods de aplicación ni al Job.

**El init solo corre con volumen vacío.** Cambiar el Secret no cambia contraseñas en una DB existente ni vuelve a ejecutar el script. No resetear el volumen si falla el init: inspeccionar y recuperar con el DBA. Para rotaciones o una BD preexistente se necesita un procedimiento aparte y respaldo; no automatizar una recreación.

El renderer no produce Secrets. Red denegada por defecto, cuenta de despliegue limitada y qué protege un Secret: [DEV-10](../docs/evidencia/DEV-10/index.md). No se publican Services al exterior; el Ingress/TLS y entrega controlada corresponden a #11.

El Ingress público permite solo `/v1` (prefijo), `/health/live`, `/health/ready`,
`/docs` y `/openapi.json` (rutas exactas). `/metrics` no tiene ruta pública:
Prometheus accede directamente al Service `event-service:8000`. Si se añade una
ruta pública nueva, actualizar esta lista y la prueba del renderer; no restaurar
el prefijo global `/`. Las políticas de `observability/jaeger.yaml` permiten
OTLP HTTP desde API/worker a Jaeger únicamente por TCP 4318 en desarrollo.

La red de observabilidad también permite Grafana→Prometheus solo por TCP 9090.
Para comprobar los contratos offline: instalar `PyYAML==6.0.3` y ejecutar
`python3 scripts/test-observability.py`. CI ejecuta estos contratos y valida los
esquemas de todos los manifiestos de `observability/`; no sustituye una prueba
del CNI en el cluster.

Los manifiestos de Jaeger crean el ConfigMap `event-service-telemetry` en
development con `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`. Es la URL completa
`http://jaeger-collector.eventos-development.svc.cluster.local:4318/v1/traces`.
Production no instala Jaeger ni define esta variable: no crea un exportador ni
envía trazas a development. Si se incorpora Jaeger a otro ambiente, configurar
su endpoint propio en el ConfigMap y sus políticas de red antes de habilitarlo.
API y worker leen ese ConfigMap opcional por `envFrom`: sin instalarlo tampoco
exportan trazas en development. Instalarlo antes de crear los pods; si ya están
ejecutándose, un operador debe reiniciarlos para cargar la nueva configuración.
Los comandos locales
no exportan trazas salvo que se defina explícitamente esta variable.

## Entrega y recuperación

La preparación única usa [`k8s-bootstrap.sh`](../scripts/k8s-bootstrap.sh) e [`k8s-ingress.sh`](../scripts/k8s-ingress.sh). Las entregas siguientes usan el workflow **Entrega controlada** ([DEV-05](../docs/evidencia/DEV-05/index.md)). Si hay que hacerlas a mano, se puede seguir el orden siguiente.

## Orden de despliegue manual (no ejecutado por el PR)

Estos comandos son para una ventana autorizada. **Cada ambiente necesita sus propios Secrets y datos.** No promover production hasta validar development.

```bash
ENVIRONMENT=development
NS=eventos-development
IMAGE='ghcr.io/marchelo23/proyecto-final-metricas-y-devops/event-service@sha256:<digest-real-de-64-hex>'
POSTGRES_IMAGE='docker.io/library/postgres@sha256:5264710be20f409750ac6dc4e5706dcef929c87e241605463f0f9aefa932a8d9'
mkdir -p artifacts/kubernetes
for STAGE in foundation migration workloads; do
  python3 scripts/render-k8s.py --environment "$ENVIRONMENT" --stage "$STAGE" \
    --image "$IMAGE" --postgres-image "$POSTGRES_IMAGE" --output "artifacts/kubernetes/$STAGE.json"
done
```

Un digest inválido termina con error, sin renderizar ni aplicar recursos. Revisar los tres archivos y comprobar `kubectl config current-context`. Después:

```bash
# 1. Namespace para poder crear Secrets ANTES de arrancar PostgreSQL.
kubectl create namespace "$NS" --dry-run=client -o json | kubectl apply -f -
KUBECTL=kubectl sh scripts/k8s-secrets.sh "$ENVIRONMENT"

# 2. Base y DB. Los Secrets anteriores no se regeneran en un reintento.
kubectl apply --dry-run=server -f artifacts/kubernetes/foundation.json
kubectl apply -f artifacts/kubernetes/foundation.json
kubectl -n "$NS" rollout status statefulset/postgres --timeout=300s

# Si GHCR es privado, configurar ahora ghcr-pull en el ServiceAccount.
# El Secret debe existir previamente con credencial de solo lectura.
# kubectl -n "$NS" patch serviceaccount event-service --type merge \
#   -p '{"imagePullSecrets":[{"name":"ghcr-pull"}]}'

# 3. Migrar antes de iniciar o actualizar la API y el worker.
kubectl apply --dry-run=server -f artifacts/kubernetes/migration.json
kubectl apply -f artifacts/kubernetes/migration.json
JOB=$(python3 -c 'import json; print(json.load(open("artifacts/kubernetes/migration.json"))["items"][0]["metadata"]["name"])')
kubectl -n "$NS" wait --for=condition=complete "job/$JOB" --timeout=240s
# DETENERSE si falla; no ejecutar el paso siguiente.

# 4. Solo con migración exitosa, activar los dos procesos.
kubectl apply --dry-run=server -f artifacts/kubernetes/workloads.json
kubectl apply -f artifacts/kubernetes/workloads.json
kubectl -n "$NS" rollout status deployment/event-service-api --timeout=180s
kubectl -n "$NS" rollout status deployment/event-service-worker --timeout=180s
kubectl -n "$NS" get pods,pvc
kubectl -n "$NS" port-forward service/event-service 18000:8000 --address 127.0.0.1
```

**No pegar todo como un script sin control de errores.** Si un paso falla, detenerse y diagnosticar; no aplicar workloads tras una migración fallida. Los Jobs por digest conservan el resultado por 24 h; un Job completo existente indica que ese digest ya migró esa DB. No borrar Jobs para ocultar errores ni reusar un resultado después de restaurar/cambiar la DB. Un fallo requiere revisión, no reintentos ciegos.

La promoción al otro namespace reutiliza **el mismo `IMAGE`**, no reconstruye. El workflow con aprobación y smoke obligatorio todavía debe implementarse/probarse en #11. Migraciones nuevas deben ser compatibles con los procesos que sigan activos durante un rollout; no se ejecutan downgrades automáticos.

## Verificación funcional y evidencia pendiente

Desde otra terminal, con las claves del ambiente cargadas **sin imprimirlas**:

```bash
curl --fail --silent --show-error http://127.0.0.1:18000/health/live
curl --fail --silent --show-error http://127.0.0.1:18000/health/ready
ESC3_BASE_URL=http://127.0.0.1:18000 cargo run --locked --example scenario_load -- custom --count 1 --rate 1 --invalid 0 --duplicates 0 --late 0 --seed 3
```

El generador es de carga/aceptación de A; verificar además histórico/estadísticas y que la lectura llegue a `processed_at != null` antes de afirmar que funciona el worker. `rollout status` del worker solo prueba disponibilidad del proceso. Capturar counts y backlog al detener/reanudar **solo un worker del entorno de prueba**; no ejecutar esto sin autorización en el compartido.

Guardar commit del repositorio, workflow de publicación, digest, versión K3s, nodo `Ready`, estado de Pods/PVC, resultado del Job y smoke funcional en `docs/evidencia/DEV-09/`. No adjuntar `kubectl get secret`, kubeconfig, archivos `.env` ni contraseñas. Revisar la salida y redactar IPs/IDs antes de publicarla.

**Persistencia no equivale a backup:** el PVC sobrevive al Pod, pero `local-path` no sobrevive a perder la VM/disco. `Retain` del StatefulSet no protege de borrar el namespace/PVC ni reemplaza restauración probada. No cambiar cloud-init, disco o VM para probar este PR. Rollback probado (#18), recursos medidos/probes del worker (#17) y observabilidad (#21–#27) siguen pendientes.
