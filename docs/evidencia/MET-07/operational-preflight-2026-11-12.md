# MET-07 · Preflight real abortado antes del incidente — Refs #27

**Incidente no ejecutado.** La ventana exclusiva y el incidente fueron autorizados por el usuario en esta conversación. La autorización se conserva separada del resultado: una precondición falló y se detuvo la ejecución sin degradar. No se invocó Experiment.run, no se registró dispositivo, no se emitieron lecturas ni se inició un watchdog real. No se escalaron/reiniciaron recursos, ni se alteraron imágenes, límites, umbrales, Terraform, automatizaciones o producción. No hubo reintento del incidente.

Base: 24620b231ef246d203f7220090bdacd039c717f9, rama feat/met-07-preparacion. Los nuevos archivos se mantienen como trabajo local revisable; no se ha publicado otro commit, actualizado el PR #94, abierto otro PR, integrado ni cerrado issues.

## Material operativo preparado y revisión

- [Adaptador](../../../scripts/met07_operate.py): conecta Experiment.run con RemoteGuard y VerifiedCollector, derivado de SignalCollector en real-read-only. El supervisor debe ejecutarse en la VM Linux; usa el mismo UID/GID efectivo que el watchdog. No cambia permisos para aceptar archivos incompatibles.
- [Despachador de preflight](../../../scripts/met07_preflight_dispatch.cjs): esta invocación fija execute_once=false, sin entrada al incidente y sin reintento. Instala copias privadas de los tres módulos y pasa claves únicamente por stdin de SSH cifrado, después al entorno del supervisor. No las usa en argumentos, archivos ni evidencias. Los SHA-256 de las fuentes efectivamente enviadas están en dispatch-result.json.
- La vía operativa preparada exige endpoints/autenticación, revisión reciente del apagado, baseline cero/inactive y prueba real del lease del watchdog **con worker todavía 1/1**. La prueba dejaría expirar heartbeat, exigiría ACK y guard-restored con run/UID correctos, reason=lost-supervisor y Ready dentro del plazo. En 1/1, Kubernetes.scale retorna sin patch. Esta vía no se alcanzó ni se acredita como probada.
- Los followers preparados exigen dos streams, lector vivo, proceso vivo y al menos un JSON con timestamp válido realmente recibido por cada stdout. Usan tail=10 para acreditar el transporte sin escribir lecturas; los registros históricos se marcan readiness_only y no demuestran actividad de la ventana. CheckedGuard vuelve a comprobarlos antes de armar el guard del incidente. Popen por sí solo no pasa.
- La ejecución futura conserva 2 intentos/s, >100 durante 120 s, lease de 30 s, restauración remota desde 540 s y límite de 600 s. Las consultas de ciclo de lectura usan tiempos durables del servidor. Los tests no sustituyen las pruebas reales del canal/followers.

**Hallazgo de revisión real:** el preflight heredado lista Deployments con el selector de Pods. El Deployment real no tiene esos labels en metadata.labels, aunque su spec.selector y template sí los tienen. La lista devuelve cero y genera Ambiguous worker deployment. Esto no demuestra dos Deployments ni un worker caído. No se añadieron labels al clúster ni se eliminó la comprobación para forzar la ejecución. El adaptador queda bloqueado para ejecución hasta corregir y validar esa compatibilidad en código y resolver las demás precondiciones. El código base y la copia ejecutada se conservan intactos.

## Cronología de observaciones reales

Todas las horas siguientes proceden de la VM, no del reloj de Windows. Los tiempos de creación de archivos describen el preflight, no la recepción/procesamiento de lecturas, porque no se emitió ninguna.

| UTC servidor, 2026-11-12 | Observación |
| --- | --- |
| 13:58:44 | SSH disponible; azureuser UID/GID 1000; contexto default; worker 1/1. La inspección inicial no mostró apagado local pendiente. |
| 14:07:26.338783 | Supervisor Linux creó invocation.json en directorio privado. Autorización explícita registrada, sin claves. |
| 14:07:26.774061 | Supervisor terminó con código 1 y Ambiguous worker deployment. No llegó a endpoints, watchdog, followers, dispositivo ni Experiment.run. |
| 14:11:59.334751 | Diagnóstico adicional exclusivamente de lectura: mismo UID, 1/1 Ready/Available; selector de Deployments devuelve []; labels de selector/plantilla correctos, metadata diferente. |
| Inmediatamente después de 14:11:59 | Seis GET de diagnóstico: API readiness, analyst, producer, Prometheus, Jaeger y Grafana devolvieron HTTP=null y connection_or_timeout. No hay respuestas HTTP exitosas ni autenticación acreditada. |
| Diagnóstico de energía, misma consulta | Scheduled Events devolvió HTTP 200 y cero eventos. No había apagado local pendiente, crontab root vacío ni workflow de energía activo. La lectura ARM de schedules de la suscripción real no fue posible. |
| 14:17:18.629980 | Captura final: UID original, réplicas=Ready=Available=1; directorios 0700 y JSON 0600, UID/GID 1000. No existen los directorios incident ni watchdog-probe. |

[Estado final y tiempos/permisos](preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a/final-readonly-state.json).
El primer sondeo de Scheduled Events agotó 8 s; la consulta posterior sí respondió sin eventos. Se conserva esta distinción: el éxito posterior de esa lectura no resuelve el acceso ARM faltante ni los demás bloqueos. Los forwards loopback escuchaban, pero eso no acreditó que atendieran HTTP.

El workflow de energía de main tiene cron nominal 05:00 UTC; siguiente nominal 2026-11-13T05:00:00Z. Se observan ejecuciones históricas diferidas respecto al cron, incluida la ejecución programada 43229219822 de 13:38:26, completada en failure. No se deduce seguridad solo del cron: se contrastaron los runs activos (cero). Azure CLI local solo dispone de otra suscripción; la suscripción real identificada por IMDS, e8293fad-4915-490d-b001-01575b97ed36, devolvió Subscription not recognized/not found al solicitar schedules. No se cambió de identidad ni se desactivó automatización alguna. La revisión global de apagado permanece passed=false.

## Resultado y matriz de evidencia

Fuente de MET-07/P3-5: [issue #27](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/27), consultado durante esta revisión. El PDF no está disponible en este worktree y la búsqueda de los literales 5.11/5.13 en documentación/issues no obtuvo el texto normativo; no se inventa su redacción ni se certifica conformidad literal. Las filas correspondientes indican el estado frente a la demostración/diagnóstico solicitados por el usuario.

| Referencia | Evidencia disponible | Resultado de esta sesión |
| --- | --- | --- |
| MET-07 | Hipótesis/procedimiento preparados; preflight real fallido, diagnóstico del bloqueo y estado final seguro | **No acreditado:** no hubo degradación, firing, mitigación ni recuperación del incidente. |
| §5.11 | Precondiciones y aborto conservados; no hay medidas de carga/degradación/recuperación | **No acreditado:** pendiente demostración y contraste con texto normativo. |
| P3-5 | Configuración preparada de 2 intentos/s; 0 intentos reales, sin capacidad reducida | **No acreditado:** tasas durante degradación, retraso/backlog, comparación y drenaje no medidos. |
| §5.13 · diagnóstico solicitado | Distinción demostrada entre selector de Deployment incorrecto, HTTP sin respuesta y falta de acceso ARM; VM/worker disponibles | **Diagnóstico operativo parcial:** no diagnostica una degradación inducida ni acredita literalmente §5.13. |
| Carga distinta P3-2 / 20/s durante 120 s | No ejecutada. [Issue #50](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/50) define 2.400 únicos | **No acreditada** por esta sesión ni por un eventual incidente de 2/s. |

T0 quedó incompleto. T1, T2, T3, T4 y T5 no comenzaron. Productor nunca iniciado, por lo que no había productor que detener. No se atribuye backlog cero ni alerta inactive al estado actual: Prometheus no respondió y el snapshot histórico no los sustituye. No existen UUID del incidente cuya persistencia se pueda validar; cero IDs no se presenta como éxito vacuo. No hay series antes/durante/después, trazas correlacionadas ni capturas de paneles del incidente. No se fabricaron screenshots o señales para llenar ese vacío.

## Evidencia real conservada

Directorio [preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a](preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a/):

- [invocation.json](preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a/invocation.json): base, alcance autorizado y configuración; sin credenciales.
- [adapter-failure.json](preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a/adapter-failure.json): fallo original, no modificado.
- [dispatch-result.json](preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a/dispatch-result.json): exit real, fuentes enviadas y réplica original conservada.
- [worker-selection.json](preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a/diagnostics/worker-selection.json): contraste real metadata/selector/template.
- [endpoint-preflight.json](preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a/diagnostics/endpoint-preflight.json): HTTP y fallos de conexión separados.
- [power-preflight.json](preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a/diagnostics/power-preflight.json): IMDS, timers, workflow y revisión ARM incompleta.
- [final-readonly-state.json](preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a/final-readonly-state.json): hora servidor, identidad, modos privados y worker Ready.
- [validation-local.txt](preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a/validation-local.txt): **fixtures y controles locales**, no evidencia de incidente.

Las copias originales continúan en /home/azureuser/met07-preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a, sin credenciales en disco. No se cambió su propietario ni se relajaron permisos para recuperarlas. El diagnóstico posterior tiene directorio separado y no reejecuta el supervisor.

## Validación local y límites

Pasaron **81 pruebas de scripts**, incluidas nueve nuevas del adaptador, y **4 contratos de observabilidad**. Pasaron npm ci, .husky/_ como hooksPath, hook real .husky/_/pre-commit sin bypass, sintaxis Node y Gitleaks 8.28.0 sin hallazgos. La lectura del snapshot anterior dentro de validate-preparation.sh sigue siendo validación histórica, no un baseline actual.

La primera pasada encontró un defecto en un fixture HTTP (comparaba None con el rol None y simulaba 401 accidentalmente); se corrigió y las nueve pruebas y la suite completa pasaron. Un envoltorio PowerShell inicial trató stderr informativo de unittest como error; se sustituyó por captura directa spawn con códigos de salida, registrada en validation-local.txt. Dos intentos de captura adicional fallaron por escapado local de Node/PowerShell antes de obtener el estado; el inspector en archivo produjo la captura final satisfactoria. No fueron incidentes ni reintentos de escrituras de aplicación.

No se repitieron clippy, PostgreSQL, container o carga Rust para cambios de herramientas Python/Node. No se afirma nuevo CI o revisión remota de este trabajo local. Los snapshots JSON/TXT y capturas ya versionados permanecen idénticos a la base.
