# MET-07 · Continuación del preflight — 2026-11-12

**Incidente no ejecutado.** Se conserva la autorización y la exclusividad de la ventana reconfirmadas por el usuario. Las condiciones técnicas se volvieron a consultar; la revisión de apagado sigue incompleta por acceso ARM. No se invocó `Experiment.run`, no hubo productor, dispositivos nuevos, lecturas ni escalado. El watchdog real no se armó: la vía operativa exige primero completar la revisión de apagado. Sus pruebas con fixtures no acreditan su funcionamiento real.

Los archivos previos de MET-07 permanecen conservados. No hay commits, push, nuevo PR ni cambios al PR #94. Todos los comandos Kubernetes de esta continuación usaron contexto `default` y namespace `eventos-development`; no se modificaron recursos Kubernetes ni automatizaciones.

## Corrección local

`scripts/met07.py` lista los Deployments del namespace sin aplicar el selector de metadata de Pods. Identifica candidatos por labels de la plantilla o selector del Deployment y exige un único candidato con el UID revisado. Mantiene la validación de réplicas, generación, args `process`, plantilla, propietario ReplicaSet/Pod, ausencia de HPA y permiso patch. ReplicaSets y Pods siguen consultándose con su selector. Se añadió un caso que rechaza un segundo Deployment candidato y se exige que la consulta de Deployments no use `-l`.

La corrección pasó también el preflight real del worker con UID `f1c9cafa-7fe9-4495-b806-94776f8a8326`.

## Evidencia real nueva

Directorio [continuation-3d2f8a57-2f4a-49b5-96f2-2dc846750157](continuation-3d2f8a57-2f4a-49b5-96f2-2dc846750157/). Se creó una copia privada nueva en `/home/azureuser/met07-continuation-3d2f8a57-2f4a-49b5-96f2-2dc846750157`; no se reutilizó el directorio del preflight abortado.

| Comprobación | Resultado observado |
| --- | --- |
| Worker | UID original, 1 réplica Ready/Available; preflight corregido satisfactorio |
| Forward API | `127.0.0.1:28000` → service/event-service:8000; readiness HTTP 200 |
| Autenticación | Analyst GET HTTP 200; producer GET en ruta de analyst HTTP 403 esperado; ningún POST |
| Forward Prometheus | `127.0.0.1:29090` → service/prometheus:9090; HTTP 200 |
| Forward Jaeger | `127.0.0.1:26686` → service/jaeger-collector:16686; HTTP 200 |
| Forward Grafana | `127.0.0.1:23000` → service/grafana:3000; HTTP 200 |
| Baseline, 15:12:54 UTC | Backlog 0, HighEventBacklog inactive, expresión `esc3_events_backlog_total > 100`, duración 120 s |
| Otras series | Tasas entrada/procesamiento 0; p95 NaN y serie 5xx ausente, sin convertirlos a cero |
| Followers | Dos procesos y lectores vivos; 10 registros JSON con timestamp recibidos por cada stream |
| Scheduled Events | HTTP 200, cero eventos |
| Apagado local | Sin apagado pendiente, crontab root vacío y sin timers con nombres de shutdown/reboot/poweroff |
| Workflow de energía | Fuente main SHA 70dcb8a06a6bb592150c9c6dcf70fb18c5619a72; cero runs en queued/in_progress/waiting/pending/requested; siguiente cron nominal 2026-11-13 05:00 UTC |
| ARM schedules | No verificado: la identidad Azure CLI no tiene acceso a la suscripción real e8293fad-4915-490d-b001-01575b97ed36 |
| Estado final, 15:12:56 UTC | Worker con UID original y 1/1 Ready/Available; cuatro forwards temporales terminados |

Los cuatro forwards se crearon directamente en la VM y atendieron HTTP; no se dedujo salud a partir de puertos escuchando. Se terminaron al cerrar el diagnóstico, por lo que deben abrirse y comprobarse nuevamente para una ejecución posterior. El transporte no depende de un túnel de Windows.

Los registros recibidos por los followers son de aproximadamente 05:12 UTC: son **readiness_only**, no actividad de esta ventana ni UUID de un incidente. Los contadores acumulados de recepción tampoco son carga emitida por esta continuación. Los resultados JSON conservan la procedencia y las marcas de tiempo.

La ausencia de Scheduled Events, de runs activos o un cron lejano no sustituye la lectura ARM. Se repitió la consulta ARM fuera del sandbox y mantuvo `Subscription not found`; no se cambió identidad, suscripción ni automatización. `power_passed=false`, `watchdog_verified=false` y `incident_executed=false` permanecen explícitos en [decision.json](continuation-3d2f8a57-2f4a-49b5-96f2-2dc846750157/decision.json).

## Fixtures y fallos conservados

La ejecución directa de la suite en Windows falló porque los controles de IPC privado exigen Linux. No se debilitó ese control.

El primer paquete de fixtures Linux usó una estructura sin `scripts/` y produjo dos errores de importación. Su resultado original permanece en `continuation-…/fixture-validation.json` con exit 1; no representa una falla del clúster ni una ejecución del incidente. Se corrigió el empaquetado del despachador para preservar las rutas del repositorio y los dos manifiestos que leen los tests.

La repetición **solo de fixtures**, sin volver a ejecutar el diagnóstico operativo, pasó **58 pruebas MET-07** en 1.493 s. Resultado completo y hashes en [fixtures-705f22ca-ca8d-4894-be05-4694216ef3a9/fixture-validation.json](fixtures-705f22ca-ca8d-4894-be05-4694216ef3a9/fixture-validation.json). Esto comprueba controles simulados, incluida recuperación/watchdog simulado; no acredita ACK ni restauración de un watchdog real. Pasó también la comprobación sintáctica Node de ambos despachadores nuevos. No se ejecutaron checks Rust para este cambio de herramientas Python/Node.

## Condición pendiente para continuar

Se necesita una sesión autorizada con lectura de schedules en la suscripción real de la VM. Se solicitó esa información al usuario sin volver a pedir autorización del incidente. Una vez disponible, hay que refrescar condiciones de ventana, UID/generación/propietarios/HPA, workflows y apagado, abrir y verificar los cuatro forwards, comprobar baseline y followers, y completar la prueba real del lease del watchdog con worker todavía 1/1. Solo entonces podrá armarse el guard independiente del incidente y considerarse la degradación autorizada. No hay reintento automático ni aceptación de MET-07/P3-5 en esta continuación.