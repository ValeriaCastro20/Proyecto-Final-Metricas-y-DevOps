# MET-07 ? Lanzamiento detenido dentro de la ventana autorizada

**Incidente no ejecutado; no se reintentó.** El supervisor esperó en la VM desde las 20:35:44 UTC. La admisión empezó a las **21:00:00.621994 UTC**, dentro de la ventana 21:00–23:00, con 7199,378 s restantes. A las **21:00:04.828538 UTC** terminó con exit 1 por una precondición. No llegó al guard, followers, dispositivo, carga ni Experiment.run. No hubo degradación ni restauración necesaria.

## Confirmación administrativa

[administrator-confirmation-verbatim.json](administrator-confirmation-verbatim.json) conserva la frase exacta transmitida por el usuario: ausencia de automatizaciones externas y ventana aceptada. Es información del administrador **relatada por el usuario**, sin autenticación directa adicional del administrador. Se mantiene arm_query_performed=false y azure_schedules_verified=false. El preflight reconoció external_shutdown_basis=user_relayed_administrator; no falló por falta de ARM.

La copia inicial conservada en administrator-confirmation.json y la copia efectivamente enviada tuvieron sustituciones de diacríticos por la codificación de la consola. La copia literal adicional corrige la transcripción sin sobrescribirlas; los campos ASCII de ventana, alcance y confirmación usados por el control no estaban afectados.

## Resultado real de los controles alcanzados

| Control | Observación |
| --- | --- |
| Reloj y margen | Dentro de ventana; más de 20 minutos restantes |
| Contexto y worker | default / eventos-development; UID original f1c9cafa-7fe9-4495-b806-94776f8a8326; preflight de generación/labels/propietarios/HPA/permisos satisfactorio |
| Endpoints | API, Prometheus, Jaeger y Grafana HTTP 200; analyst 200 y producer 403 esperado en ruta de analyst |
| Scheduled Events | HTTP 200, cero eventos |
| Apagado local | Sin apagado pendiente; root crontab vacío; inventario válido de 17 timers |
| Workflow de energía | Fuente revisada SHA 70dcb8a06a6bb592150c9c6dcf70fb18c5619a72, cron nominal 05:00 UTC |
| Workflows del repositorio | Cinco runs Rust quality and acceptance en queued, de PRs ajenos; registrados con ID y rama |
| Guard operativo y followers | **No alcanzados**, por aborto de la primera admisión |
| Estado final | Worker con UID original, réplicas=Ready=Available=1 |
| Consulta final de lectura | 21:00:04.770 UTC: backlog 0, alerta inactive. Es estado tras aborto, no recuperación de incidente |
| Forwards | Cuatro forwards abiertos en la VM dentro de ventana y cerrados tras el aborto; all_stopped=true |

## Causa precisa y limitación del lanzador

El lanzador del agente inventarió correctamente todos los workflows activos del repositorio, pero pasó su **total** como active_power_workflows. power_check exigió cero y bloqueó. Los cinco registros son workflows de CI Rust en cola, no cinco automatizaciones de apagado. Es un **bloqueo demasiado amplio por clasificación del lanzador**, no una demostración de apagado cloud activo ni una falla de la confirmación administrativa.

No se corrigieron las fuentes ya ejecutadas ni se reinterpretó el resultado para reanudar. No se cancelaron runs de otros PRs. La corrección pendiente debe separar inventario de workflows, mecanismos de energía y ejecuciones que puedan modificar el Deployment; necesitará pruebas y una decisión posterior sobre un nuevo lanzamiento. Esta sesión respeta el aborto sin reintento automático solicitado.

## Evidencia y límites

- [preflight-1.json](execution/preflight-1.json): respuestas reales y contador usado, sin modificaciones.
- [launch-failure.json](execution/launch-failure.json), [final-worker.json](execution/final-worker.json), [final-snapshot.json](execution/final-snapshot.json) y [events.jsonl](execution/events.jsonl): aborto, estado final y vida de los forwards.
- [dispatch-start.json](dispatch-start.json) y [dispatch-result.json](dispatch-result.json): fuentes SHA-256 exactas, host/directorio y exit real.
- [before-window-readonly.json](before-window-readonly.json): a las 20:36:36 no existían guard de prueba ni directorio del incidente, con worker 1/1 y hashes instalados correctos.
- [operational-result.json](operational-result.json): decisión agregada que distingue el defecto de clasificación de las observaciones.

No hay firing real, UUIDs del incidente ni aceptación de MET-07/P3-5. Los contadores acumulados 12896 y los resultados de fixtures no se atribuyen a una prueba nueva. Las series 5xx ausentes y p95 NaN se conservan sin convertirlas a cero. No se probaron el guard operativo ni la persistencia de forwards durante una degradación, porque no hubo degradación.

Las suites offline previas pasaron por separado: launch 9, operate 14, preparation 28, hardening 11, signals 10 y OS watchdog 4; las repeticiones de launch 6/6/9 no se suman. Los registros originales de esas ejecuciones permanecen intactos.

Se verificaron de nuevo los 81 hashes de evidencias anteriores, sin diferencias. No se modificaron otros namespaces, umbrales, reglas ni #94. No se crearon commits ni push en esta sesión. Las fuentes locales y la evidencia nueva quedan revisables; las copias remotas originales permanecen en /home/azureuser/met07-operational-44c88e6e-5ab1-4d3c-b5fb-a19e99c44274.
