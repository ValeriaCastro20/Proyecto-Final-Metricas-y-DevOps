# Observabilidad en eventos-development

Guía reproducible sobre los manifiestos versionados. Parche preparado contra `5d2a16e` y contrastado estáticamente con main `7607d54`; estos comandos no se ejecutaron en esta incorporación. La evidencia histórica de despliegue, ocho paneles y diez trazas API→worker está en [MET-05](../../docs/evidencia/MET-05/README.md). La disponibilidad actual requiere consultas nuevas. Esta guía no autoriza redesplegar ni repetir MET-07 para obtener nuevas capturas.

## Prerrequisitos y destino

Desde la raíz del repositorio: PowerShell, OpenSSH, Node.js >=18 para comprobar el dashboard, clave privada local y host previamente autenticado. En la VM: K3s, sudo sin interacción para los comandos autorizados y contexto `default`. Namespace existente `eventos-development`, API, worker y PostgreSQL disponibles. No crear ni modificar otros namespaces. La guía presupone la aplicación instalada según [Kubernetes](../README.md); no instala la aplicación ni consulta Secrets.

La huella ED25519 autorizada del servidor es `SHA256:L1RxG+BO2hEHHgsmPH1rLDhddP/s5O/8R4yhtOML6MU`. Una discrepancia requiere detenerse y verificar con el responsable. No usar aceptación automática ni desactivar StrictHostKeyChecking.

En PowerShell, desde la raíz del worktree. Ejecutar cada bloque completo como script (o dentro de un bloque `& { ... }`), para que `throw` interrumpa el flujo. No continuar manualmente con líneas posteriores tras un error:

```powershell
$SshKey = 'C:/Users/itsis/.ssh/id_ed25519'
$SshHost = 'azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com'
$SshOptions = @('-F','NUL','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UpdateHostKeys=no','-o','ConnectTimeout=15','-o','IdentitiesOnly=yes','-i',$SshKey)
ssh @SshOptions $SshHost 'sudo -n k3s kubectl config current-context'
if ($LASTEXITCODE -ne 0) { throw 'Falló la comprobación del contexto SSH. Detenerse.' }
ssh @SshOptions $SshHost 'sudo -n k3s kubectl --context default -n eventos-development get deployment/event-service-api deployment/event-service-worker'
if ($LASTEXITCODE -ne 0) { throw 'Falló la comprobación de los deployments. Detenerse.' }
```

Esperado: contexto `default`, API y worker disponibles. Si cambia la identidad del destino, detenerse. Revisar capacidad actual antes de desplegar: el margen histórico de MET-05 no prueba capacidad actual. Leer requests/limits y estado de los pods del namespace; el responsable de infraestructura puede aportar capacidad agregada del nodo sin ampliar este procedimiento a otros namespaces.

## Recursos y orden

| Archivo | Recursos principales y función |
| --- | --- |
| jaeger.yaml | ConfigMap event-service-telemetry, Deployment jaeger, Service jaeger-collector y políticas OTLP |
| k8-prometheus.yaml | ConfigMap prometheus-config, Deployment/Service prometheus, worker-metrics y políticas de scraping |
| grafana-dashboards.yaml | ConfigMap del dashboard de ocho paneles y provider |
| grafana.yaml | Datasource, Deployment/Service grafana y políticas hacia Prometheus |

Todos declaran `eventos-development`. El datasource usa UID `event-service-prometheus` y URL `http://prometheus:9090`. El dashboard tiene UID `event-service-met05`. Su [JSON importable](../../dashboards/event-service-met05.json) es la fuente; para regenerar su ConfigMap tras editarlo: `node dashboards/render-configmap.cjs`. Revisar el diff generado antes de publicar.

Para copiar exclusivamente los cuatro manifiestos a una carpeta privada de la VM:

La carpeta debe ser nueva o estar revisada previamente con propietario azureuser y modo 0700. umask no corrige los permisos de una carpeta que ya existe. Detenerse ante errores de SSH o copia; no reutilizar una carpeta de evidencias.

```powershell
ssh @SshOptions $SshHost 'umask 077; mkdir -p /home/azureuser/observabilidad-manifiestos'
if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar la carpeta remota. Detenerse.' }
scp @SshOptions ./kubernetes/observability/jaeger.yaml ./kubernetes/observability/k8-prometheus.yaml ./kubernetes/observability/grafana-dashboards.yaml ./kubernetes/observability/grafana.yaml "${SshHost}:/home/azureuser/observabilidad-manifiestos/"
if ($LASTEXITCODE -ne 0) { throw 'La copia de manifiestos falló. No aplicar.' }
ssh @SshOptions $SshHost
if ($LASTEXITCODE -ne 0) { throw 'Falló la sesión SSH. No continuar con el despliegue.' }
```

Los siguientes bloques son Bash **en la VM**, desde `/home/azureuser/observabilidad-manifiestos`, no PowerShell:

```bash
cd /home/azureuser/observabilidad-manifiestos
set -euo pipefail
k() { sudo -n k3s kubectl --context default --namespace eventos-development "$@"; }
for file in jaeger.yaml k8-prometheus.yaml grafana-dashboards.yaml grafana.yaml; do
  k apply --dry-run=client --validate=strict -f "$file"
  k apply --dry-run=server --validate=strict -f "$file"
done
```

Esperado: validación sin error para cada recurso. Un dry-run no despliega nada. Aplicación autorizada, en este orden:

```bash
k apply -f jaeger.yaml
k rollout status deployment/jaeger --timeout=180s
k apply -f k8-prometheus.yaml
k rollout status deployment/prometheus --timeout=180s
k apply -f grafana-dashboards.yaml
k apply -f grafana.yaml
k rollout status deployment/grafana --timeout=180s
k get deployment/jaeger deployment/prometheus deployment/grafana
k get pods -l app=jaeger
k get pods -l app=prometheus
k get pods -l app=grafana
k get service/jaeger-collector service/prometheus service/grafana service/event-service-worker-metrics
k exec deployment/prometheus -- promtool check config /etc/prometheus/prometheus.yml
k exec deployment/prometheus -- promtool check rules /etc/prometheus/alerts.yml
```

Esperado: deployments disponibles, pods Ready, Services presentes y validación de configuración y dos reglas satisfactoria. En una reinstalación se debe revisar si las ConfigMaps cambiaron: `rollout status` por sí solo no recarga configuración de procesos ya existentes. Prometheus y el datasource de Grafana pueden requerir reiniciar sus deployments si cambió su configuración; planificarlo y verificarlo antes de hacerlo. No reiniciarlos durante la ventana de captura de un incidente.

La API y el worker leen el ConfigMap OTLP mediante envFrom opcional al arrancar. Si ya estaban ejecutándose antes de crearlo, necesitan reinicio secuencial autorizado y espera de readiness. Este bloque es operativo y potencialmente disruptivo; no forma parte de una inspección:

```bash
k rollout restart deployment/event-service-api
k rollout status deployment/event-service-api --timeout=180s
k rollout restart deployment/event-service-worker
k rollout status deployment/event-service-worker --timeout=180s
```

La autorización histórica no demuestra que las condiciones de una ventana futura sigan vigentes.

## Acceso y verificación de ejecución

Desde otra terminal PowerShell en la raíz del repositorio, el launcher existente abre cuatro forwards de loopback, verifica HTTP y devuelve sus procesos. Rechaza puertos ocupados sin cerrar procesos ajenos. En esa terminal, volver a definir `$SshKey`, `$SshHost` y `$SshOptions` con exactamente los mismos valores del primer bloque y repetir sus comprobaciones SSH. El launcher histórico tiene valores fijos por defecto: el parámetro `-Start` siguiente los sustituye por esos valores, sin editar la evidencia de MET-05. Conservar las opciones de identidad y verificación de host; si cambia el destino, verificar previamente su huella con el responsable:

```powershell
. ./docs/evidencia/MET-05/tunnels.ps1
$StartObservabilitySsh = {
    param($spec)
    $remote = "sudo -n k3s kubectl --namespace eventos-development port-forward --address 127.0.0.1 service/$($spec.Service) $($spec.Port):$($spec.RemotePort)"
    $sshArgs = @($SshOptions) + @('-o', 'ExitOnForwardFailure=yes',
        '-L', "127.0.0.1:$($spec.Port):127.0.0.1:$($spec.Port)",
        $SshHost, ('"' + $remote + '"'))
    # Start-Process une ArgumentList: entrecomillar la ruta de clave si contiene espacios.
    $keyIndex = [array]::IndexOf($sshArgs, '-i') + 1
    $sshArgs[$keyIndex] = '"' + $SshKey + '"'
    Start-Process -FilePath ssh -ArgumentList $sshArgs -WindowStyle Hidden -PassThru
}.GetNewClosure()
$ObservabilityTunnels = Start-Met05Tunnels -Start $StartObservabilitySsh
Invoke-RestMethod http://127.0.0.1:28000/health/ready
Invoke-RestMethod http://127.0.0.1:29090/-/ready
Invoke-RestMethod http://127.0.0.1:23000/api/health
Invoke-RestMethod http://127.0.0.1:26686/api/services
Invoke-RestMethod http://127.0.0.1:29090/api/v1/targets
Invoke-RestMethod http://127.0.0.1:29090/api/v1/rules
Invoke-RestMethod 'http://127.0.0.1:29090/api/v1/query?query=up'
Invoke-RestMethod http://127.0.0.1:23000/api/datasources/uid/event-service-prometheus
Invoke-RestMethod http://127.0.0.1:23000/api/dashboards/uid/event-service-met05
```

Esperado: readiness HTTP 200, targets `event-service` y `event-service-worker` con health up, sus series `up=1`, reglas saludables y datasource/UID correctos. Verificar ambas reglas: `HighEventBacklog` (>100 durante 120 s) y `HighProcessorLatency` (media de lote >0.5 s durante 1m). La evaluación de reglas y scrape son procesos distintos: el scrape es 5 s; no se configura evaluation_interval y Prometheus usa su valor predeterminado.

Interfaces: Prometheus `http://127.0.0.1:29090/targets`, Grafana `http://127.0.0.1:23000/d/event-service-met05` y Jaeger `http://127.0.0.1:26686/`. Grafana configura acceso anónimo Viewer; no se necesita imprimir credenciales.

Jaeger debe recibir spans del flujo real. Una lista de servicios no prueba correlación API→worker: comprobar una lectura autorizada con su UUID, ambos servicios en el mismo trace y relación padre/hijo. La prueba histórica de diez lecturas está en `docs/evidencia/MET-05/10-correlation.json`; esta guía no repite carga. Usar tiempos recibidos/procesados por el servidor para buscar trazas, conservando cualquier discrepancia de reloj local.

Cerrar únicamente los túneles creados por esta ejecución al terminar:

```powershell
$ObservabilityTunnels | ForEach-Object { Stop-Process -Id $_.Process.Id -ErrorAction SilentlyContinue }
```

## Interpretación y problemas frecuentes

- Target down: comprobar selector, Service y endpoints con `k get endpoints event-service event-service-worker-metrics`; revisar políticas de scraping en k8-prometheus.yaml y puerto 9000 del worker. No eliminar default-deny.
- ConfigMap OTLP presente sin trazas: comprobar si API/worker arrancaron con esa configuración y si hubo trabajo real. Revisar logs pertinentes y políticas OTLP; no inferir exportación por la existencia del YAML.
- Dashboard ausente: comprobar ConfigMap grafana-dashboards, montajes de provider/dashboard y logs de Grafana. Regenerar el ConfigMap desde JSON cuando corresponda; no fabricar paneles vacíos.
- Panel sin datos: los histogramas de lote requieren procesamiento y las tasas requieren muestras. Conservar ausencia/NaN; no rellenar con cero para aparentar éxito. Comparar PromQL directo con el proxy de Grafana.
- HTTP local no responde: revisar procesos SSH, forwards y pods; un puerto escuchando no prueba salud. Volver a ejecutar el launcher solo con sus puertos disponibles y sin cerrar procesos ajenos.
- Alerta inactive: no prueba disparo previo. Capturar estado original, pending, firing y posterior inactive durante un incidente autorizado; no cambiar umbrales.
- Persistencia: Prometheus/Grafana usan emptyDir y Jaeger memoria. Recrear pods puede perder métricas, cambios manuales y trazas. Prometheus configura retención de 2 días; no es garantía de persistencia ni backup. Exportar evidencias antes de recrearlos.

## Validación final y evidencia

Registrar hora UTC del servidor, revisión fuente, contexto, namespace y salidas reales en archivos nuevos. Adjuntar targets, reglas, consultas de los ocho paneles, datasource, dashboard y trazas correlacionadas. Una respuesta HTTP 200 con datos ausentes no acredita el panel. La evidencia histórica de MET-05 separa el fallo inicial por reloj de la correlación posterior satisfactoria. El procedimiento de MET-07 y sus bloqueos se consultan en [su índice](../../docs/evidencia/MET-07/index.md); no se ejecuta el incidente desde esta guía.
