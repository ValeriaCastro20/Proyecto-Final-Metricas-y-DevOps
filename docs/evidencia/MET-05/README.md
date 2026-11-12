# MET-05 — Dashboard y despliegue de observabilidad

## Alcance y estado

Configuración y despliegue completados exclusivamente en `eventos-development` del servidor `eventos-b97e31.mexicocentral.cloudapp.azure.com`, con SSH y verificación estricta del host. Prometheus, Grafana y Jaeger proceden de los manifiestos de `origin/main`; no se cambiaron imágenes ni umbrales. No se modificaron producción ni Terraform. MET-07 sigue **BLOQUEADO**: no se confirmó aislamiento y no se ejecutaron pruebas de incidentes ni se detuvo el worker.

El worktree original estaba en `feat/observabilidad-met-07` (4b42e8c), con `diagnostico-eventos-development.txt` sin seguimiento. Se conservó intacto. Se ejecutaron `git fetch origin main` y `git worktree add -b feat/met-05-dashboard ../Proyecto-observabilidad-met05 origin/main`. Base recuperada: `eb8fa8fcfdccab1f9879e9acc1128a9b974d4933`. En esa fase aún no se habían creado commits ni PR.

## Configuración preparada

- JSON importable: `dashboards/event-service-met05.json`, fuera del directorio de manifiestos.
- Generador: `node dashboards/render-configmap.cjs`; produce `kubernetes/observability/grafana-dashboards.yaml` con el dashboard y el provider de archivos.
- Grafana monta provider y dashboard en directorios independientes, en modo lectura.
- UID del datasource: `event-service-prometheus`; UID del dashboard: `event-service-met05`.
- Ocho paneles: recepción por resultado, procesamiento/s, backlog, HTTP p95 por ruta, lote p95, estados HTTP, salud de targets y duración media de lote.
- Etiquetas verificadas en código: `outcome` en `src/scenario/store.rs`; `route` y `status` en `src/api.rs`. Los histogramas de lote no tienen etiquetas de negocio y solo se observan cuando se procesan lecturas. Las consultas se filtran por los jobs configurados.
- No se añadieron series ficticias, umbrales ni expresiones de relleno con cero. Series vacías y NaN conservan su significado. La tasa cero de un contador existente no equivale a una serie ausente.

## Capacidad antes del despliegue

Evidencia: `01-capacity.sh` y `01-capacity.txt`.

El nodo completo dispone de 2000m CPU y 8121964Ki de memoria asignable (aprox. 7931.6Mi). Solicitudes agregadas previas: 1100m CPU y 1164Mi. La pila añade 200m y 512Mi: total previsto 1300m y 1676Mi; margen restante aprox. 700m y 6255.6Mi. También hay margen para las réplicas temporales de los reinicios secuenciales (100m y 128Mi cada una). Memoria disponible del SO: 6424Mi; disco disponible: 57GiB. Nodo Ready, sin presión de memoria, disco ni PID.

Los límites CPU previos suman 200% y hay componentes sin requests: el margen de solicitudes permite programar la pila, pero no acredita capacidad bajo carga ni aislamiento. No se ejecutó carga.

## Validación, aplicación y readiness

Cada script `.sh` es el comando remoto reproducible, y su `.txt` contiene la salida y el código de retorno. `Invoke-Remote.ps1` transmite el script por entrada estándar codificada para evitar los límites y problemas de comillas/CRLF de Windows; no crea archivos remotos.

1. `02-validate.sh`: validación de cliente y dry-run del servidor con validación estricta, todos satisfactorios.
2. `03-deploy.sh`: aplicación Jaeger → Prometheus → ConfigMap dashboard → Grafana. Los tres rollouts finalizaron correctamente.
3. `04-restart-readiness.sh`: `promtool check config` validó configuración y dos reglas. Se reiniciaron API y luego worker, esperando cada rollout correctamente.
4. La espera general posterior incluyó el Job de migración Completed y pods antiguos; agotó el timeout. El error se conserva en `04-restart-readiness.txt`. No se ocultó ni provocó un nuevo reinicio.
5. `04b-readiness.sh`: comprobación con selectores específicos de componente y fase Running. API y worker nuevos Ready=True, ambos deployments 1/1 disponibles, sin reinicios de contenedor. Sus imágenes conservan el digest `17b4e6051228fd27df63471a3fff003bd8f2cb7ca916ef8e29d96a29835597e9`.
6. Se corrigió la codificación de los títulos del dashboard y se validó y actualizó únicamente su ConfigMap: `07-dashboard-utf8.sh` / `.txt`. Grafana lo recargó sin reinicio.

Ejemplo de ejecución local realmente utilizada:

```powershell
& ./docs/evidencia/MET-05/Invoke-Remote.ps1 -ScriptFile docs/evidencia/MET-05/03-deploy.sh -LogName 03-deploy.txt
```

Los scripts 02 y 03 contienen las instantáneas exactas iniciales de los manifiestos codificadas en base64; 07 conserva la actualización posterior. No contienen Secrets.

## Funcionamiento verificado

`tunnels.ps1` conserva los comandos SSH y port-forward, todos ligados a 127.0.0.1. Cada comando se ejecuta en una sesión separada. No se abrió Ingress ni un puerto público.

- Prometheus: http://127.0.0.1:29090/targets
- Grafana: http://127.0.0.1:23000/d/event-service-met05
- Jaeger: http://127.0.0.1:26686/

`05-verify.cjs` consulta las APIs por esos túneles. `05-verification.json` guarda las respuestas finales completas de targets, reglas, datasource, dashboard y consultas; los spans se resumen eliminando etiquetas no necesarias. `05-verification.txt` conserva la primera ejecución y `05-verification-final.txt` la última.

Verificado:

- Ambos targets `event-service` y `event-service-worker` están `up`, sin `lastError`.
- `HighProcessorLatency` y `HighEventBacklog`: salud `ok`, estado `inactive`; umbrales originales intactos.
- Datasource con UID estable, provisionado y de solo lectura. Se ejecutaron las ocho expresiones tanto directamente en Prometheus como a través del proxy de Grafana: HTTP 200 y `status=success` en las dieciséis consultas.
- Dashboard provisionado (`meta.provisioned=true`) con ocho paneles. Capturas reales de las interfaces en `grafana-dashboard.png`, `prometheus-targets.png` y `jaeger-traces.png`; comandos y resultados del navegador en `06-screenshots.cjs` / `.json`.
- Tras reiniciar, las métricas en memoria se reinicializan. En la comprobación previa a la prueba funcional no había series recientes de recepción ni histogramas de lote; esos paneles quedan sin datos. No se generaron lecturas ni se rellenaron series para mejorar la captura. La disponibilidad de las consultas no demuestra procesamiento de negocio bajo carga.
- Jaeger devuelve spans reales `http_request` de la API (por ejemplo `/metrics`, `/health/live` y `/health/ready`). Evidencia segura por servicio: `08-traces.cjs`, `08-traces.json` y `08-traces.txt`.

## Prueba funcional y trazabilidad API → worker (2026-11-12 UTC)

El bloqueo inicial por falta de credenciales quedó resuelto por autorización explícita del usuario. Se utilizaron exclusivamente `EVENT_PRODUCER_KEY` y `EVENT_ANALYST_KEY` del entorno; no se imprimieron, persistieron ni obtuvieron Secrets del clúster. Se reutilizaron los tres túneles de observabilidad existentes y se añadió un túnel SSH de API ligado a `127.0.0.1:28000`, hacia `service/event-service:8000` en `eventos-development`, con verificación estricta del host. No se modificó el despliegue.

### Ejecución única

`09-functional.cjs` ejecutó el generador existente `examples/scenario_load.rs`, sin modificarlo, con los argumentos:

```text
custom --count 10 --rate 1 --invalid 0 --duplicates 0 --late 0 --seed 3 --run met05-20261112051300975-8c6a5f
```

Se compiló con `cargo +1.97.1-x86_64-pc-windows-msvc build --locked --example scenario_load` y se invocó directamente `target/debug/examples/scenario_load.exe` con esos argumentos y `ESC3_BASE_URL=http://127.0.0.1:28000`. `09-functional.json` conserva el hash SHA-256 del ejecutable y la revisión fuente. Se mantuvo Rust 1.97.1; la variante GNU local falló por ausencia de herramientas auxiliares, por lo que se instaló la variante MSVC de la misma versión y se usaron las Build Tools ya instaladas. No se cambió `rust-toolchain.toml` ni `Cargo.lock`.

Dispositivo ficticio único: `load-met05-20261112051300975-8c6a5f`, instalación `simulated-maintenance`. Una sola emisión: diez respuestas HTTP 202, duración de emisión 10.0147595 s, retraso máximo de programación 20.9583 ms, cero solicitudes inciertas y cero aceptados perdidos. No se ejecutó otro perfil ni se reintentaron escrituras.

El ledger por dispositivo confirma `received=validated=accepted=processed=10`, `pending=duplicates=rejected=0`. Las diez filas del histórico tienen `processed_at`; sus estadísticas están en la evidencia. El ledger global pasó de 12886 a 12896 aceptados/procesados y mantuvo pendientes cero. Las fechas de generación son ficticias (2040), propias del generador; las fechas de recepción/procesamiento son reales.

### Métricas y trazas reales

`09-functional.json` conserva las respuestas completas de las ocho consultas de paneles, tanto en Prometheus como por el proxy de Grafana: dieciséis respuestas HTTP 200 con `status=success`, series presentes y al menos un valor finito por panel. Targets API/worker `up=1`, backlog cero, reglas saludables e inactivas. El dashboard continúa provisionado con ocho paneles.

Valores observados por Prometheus durante la prueba: recepción aceptada ≈0.0338/s y procesamiento ≈0.0339/s sobre ventanas de cinco minutos; estos promedios no representan la cadencia instantánea de emisión de 1/s. HTTP p95 de `/v1/readings` ≈20.7 ms; lote p95 ≈4.75 ms y media ≈2.893 ms. Los cuantiles provienen de histogramas y son estimaciones. Las series NaN de rutas sin incrementos suficientes se conservaron, sin relleno ni modificación de umbrales.

La comprobación inicial terminó con código 1 exclusivamente en la búsqueda de correlación: `09-functional.json` conserva `passed=false` y `error="API to worker parent correlation"`, aunque el generador y las verificaciones anteriores pasaron. El reloj local estaba adelantado respecto al servidor; el filtro `start` local excluyó las diez trazas. `10-correlation.cjs` corrigió la consulta de solo lectura usando `received_at`/`processed_at` del servidor con margen de 60 segundos y, como criterio de pertenencia, los UUID del histórico del dispositivo. No se emitieron lecturas adicionales ni se alteró la evidencia inicial.

`10-correlation.json` confirma `passed=true`: diez UUID distintos con diez trazas correlacionadas. En cada una se verificó `http_request` de `event-service-api`, ruta `/v1/readings`, estado 202, y `process_reading` de `event-service-worker` con `reading_id` perteneciente a esta ejecución. La referencia `CHILD_OF` apunta al span de recepción dentro del mismo trace ID. Ejemplo: traza `7e1f6ff684f5fa3f72b938fc7b223799`, API `e45ebabf6eb5f66f`, worker `478b3fac830a1273`, lectura `967d3bc1-e8df-4c96-9e0f-5ca186e956af`.

Capturas posteriores: `09-grafana-functional.png` y `09-jaeger-correlated.png`; ejecución en `09-screenshots.cjs` / `.json`. `11-worker-final.txt` confirma API y worker 1/1 disponibles, mismos pods, cero reinicios y mismo digest de imagen. El worker permaneció activo durante toda la prueba y al finalizar. No se ejecutó `drain`, MET-07, escalado, reinicios ni cambios de imágenes o umbrales. En esa fase aún no se habían creado commits ni PR.

## Limitaciones y errores conservados

La pila reutilizada utiliza `emptyDir` para Prometheus/Grafana y Jaeger all-in-one en memoria. Su estado no es persistente ante recreación de pods. La retención configurada de Prometheus es 2 días; no se cambió.

Antes de los scripts finales hubo errores de transporte local: JSONPath perdió comillas (`unclosed action`), Bash recibió finales de línea incompatibles (`unexpected end of file`) y un comando SSH superó el límite de Windows (`The filename or extension is too long`). Ninguno modificó recursos; se sustituyó el transporte por base64 en stdin. El timeout de readiness sí se conserva como salida original en 04. Un intento local de detectar PyYAML falló por comillas; no se instalaron herramientas. La validación Kubernetes y promtool posterior sí se completó.

MET-07 permanece bloqueado y no forma parte de la aceptación de MET-05. El clúster es compartido; no se presume aislamiento.