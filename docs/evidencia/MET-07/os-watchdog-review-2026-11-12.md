# MET-07 ? Apagado del sistema y watchdog independiente ? 2026-11-12

**Detenido antes de degradar.** La autorizaci?n del incidente y la exclusividad reconfirmadas se mantienen separadas de la evidencia t?cnica. El preflight actualizado vuelve a fallar la revisi?n de apagado: no hay acceso ARM a la suscripci?n real de la VM. Se ejecutaron cero incidentes, cero escalados y cero lecturas de carga. No se invoc? Experiment.run. El PR #94 permanece intacto; no hay commits ni push.

## Mecanismos comprobados en lectura

Auditor?a a las 15:23:49 UTC y detalle a las 15:25:41 UTC, desde la VM:

| Mecanismo | Evidencia y alcance |
| --- | --- |
| Apagado programado systemd/logind | No existe /run/systemd/shutdown/scheduled; shutdown.target, reboot.target y poweroff.target inactivos, sin Job. |
| Timers del sistema | Se leyeron listado completo cargado, pr?ximas activaciones, unidad activada, propiedades de ejecuci?n, definiciones y drop-ins de 17 timers. Ninguna propiedad ExecStart/Pre/Post inspeccionada present? t?rminos de apagado. No se ejecutaron ni modificaron los timers. |
| systemd-tmpfiles-clean | La coincidencia textual shutdown corresponde a Conflicts/Before=shutdown.target; ExecStart es systemd-tmpfiles --clean. No programa un apagado. |
| Timer del usuario azureuser | launchpadlib-cache-clean.timer ejecuta limpieza de cach?; se ley? la definici?n del timer y servicio. No representa inspecci?n de todos los gestores de usuario posibles. |
| Cron | Root y azureuser sin crontab. /etc/crontab, /etc/cron.d y scripts hourly/daily/weekly/monthly le?dos; sin t?rminos directos de apagado en el contenido inspeccionado. Se conservan hashes, no l?neas arbitrarias que pudieran contener secretos. No es an?lisis transitivo de todos los scripts llamados. |
| at/atd | atq no disponible; comprobaci?n adicional acredita paquete at no instalado y atd.service not-found/inactive. La primera consulta fallida no se presenta como una cola vac?a. |
| unattended-upgrades | apt-config dump sin ajuste Automatic-Reboot. El c?digo instalado usa find_b(Automatic-Reboot, False) y retorna sin reiniciar cuando est? deshabilitado. Con esa configuraci?n observada, el reinicio autom?tico queda deshabilitado por defecto. El siguiente apt-daily-upgrade nominal era 2026-11-13 06:04:23 UTC. |
| Azure Scheduled Events | HTTP 200, cero eventos en el preflight actualizado. Es una observaci?n puntual, no un inventario de automatizaciones externas. |
| Workflow vm-power de main | SHA 70dcb8a06a6bb592150c9c6dcf70fb18c5619a72; cero runs activos en los estados consultados. Pr?ximo cron nominal: 2026-11-13 05:00 UTC. No se deduce seguridad solo del cron, por los retrasos observados anteriormente. |

Fuentes: [auditor?a OS](os-watchdog-66b07a85-7eea-4383-b965-e82c58de9d4d/os-power-audit.json), [detalle de unidades y paquetes](os-details-c1af5d73-b3dc-4f06-b831-6b5a0ce4aed0/os-details.json), [apagado refrescado](continuation-72ce6c96-6c85-4058-bda0-9473c93f86b2/power-preflight.json).

## Watchdog: validaci?n real segura y l?mites

Se cre? una unidad systemd transitoria independiente que ejecut? **el motor real core.watchdog con un backend de Kubernetes que proh?be mutaciones**. El backend rechaza patch/scale/delete/apply/create/replace/edit antes de ejecutar comandos; su m?todo scale solo comprueba que el worker siga Ready con una r?plica y registra una observaci?n sin escribir en Kubernetes. Si el worker cambiase, el canario fallar?a y no intentar?a restaurarlo. La unidad ten?a Restart=no, RuntimeMaxSec=50s y TimeoutStopSec=5s.

Se verificaron archivos privados 0700/0600 y ACK con identidad UID/GID 1000, run y UID del Deployment correctos; boot_id compartido; proceso principal 1523231 distinto del supervisor 1522960. Al dejar de renovar el heartbeat, el proceso independiente registr? lost-supervisor a los **30,421 s**, dentro del l?mite. La r?plica permaneci? 1/1. La unidad termin?: MainPID=0, LoadState=not-found, ActiveState=inactive, SubState=dead.

[Resultado real del canario](os-watchdog-66b07a85-7eea-4383-b965-e82c58de9d4d/independent-validation.json), [ACK y archivos de control](os-watchdog-66b07a85-7eea-4383-b965-e82c58de9d4d/watchdog-readonly-probe/), [unidad independiente](os-watchdog-66b07a85-7eea-4383-b965-e82c58de9d4d/watchdog-readonly-probe/independent-unit.json).

Esta prueba acredita lanzamiento independiente, IPC, identidad y detecci?n de p?rdida del supervisor. **No acredita restauraci?n real ni el launcher/backend con capacidad de mutaci?n del guard del incidente.** Los archivos internos guard-restored.json proceden del motor con backend sin escrituras; no se presentan como recuperaci?n de un worker degradado. El guard operativo original sigue pendiente de su prueba posterior a todas las precondiciones. No se debilit? power_check ni se sustituy? por una bandera aprobada manualmente.

## Preflight actualizado y decisi?n

A las 15:24:21?23 UTC se refrescaron selector/UID/generaci?n/propietarios/HPA/permisos, cuatro forwards loopback y autenticaci?n. API, Prometheus, Jaeger y Grafana respondieron HTTP 200; analyst 200 y producer 403 esperado en ruta de analyst. Baseline real: backlog 0, alerta inactive; expresi?n >100 y duraci?n 120 s conservadas. Los dos followers recibieron registros hist?ricos, marcados readiness_only. Los cuatro forwards se cerraron al terminar.

El worker termin? con UID f1c9cafa-7fe9-4495-b806-94776f8a8326 y una r?plica Ready/Available. [Estado final](continuation-72ce6c96-6c85-4058-bda0-9473c93f86b2/final-state.json).

**Requiere al administrador:** acreditar schedules y otras automatizaciones externas de apagado/reinicio en la suscripci?n e8293fad-4915-490d-b001-01575b97ed36, mediante acceso de lectura o evidencia administrativa verificable y reciente. La identidad actual no puede consultarla. Tambi?n quedan fuera del alcance de esta auditor?a los gestores de otros usuarios y las cadenas indirectas de scripts; el administrador debe confirmar su cobertura y el canal de un operador independiente para la ventana. No se ha aportado nueva evidencia que cierre esos puntos. La exclusividad del usuario no se convirti? en prueba ARM.

Por tanto, power_passed=false y la decisi?n es **STOP_BEFORE_DEGRADATION**, sin reintento autom?tico. Cuando se resuelva esa condici?n, habr? que refrescar nuevamente toda la ventana y completar el guard operativo antes de una ?nica prueba autorizada.

## Fixtures y conservaci?n

Pasaron **62 pruebas con fixtures Linux**, incluidas cuatro nuevas del backend de solo lectura; no son evidencia de recuperaci?n real. [Resultado de fixtures](fixtures-2036b99d-5cc3-483d-9f1b-e9a15bbf8315/fixture-validation.json). La repetici?n incluida en el preflight actualizado tambi?n pas?. Pas? sintaxis Node del despachador y git diff --check.

Los hashes de 36 archivos de evidencia preexistentes se comprobaron antes/despu?s de la auditor?a y de nuevo al cerrar este informe, sin diferencias. [Inventario SHA-256](os-watchdog-66b07a85-7eea-4383-b965-e82c58de9d4d/original-evidence-sha256.json). Cada captura nueva utiliza nombre exclusivo. Un intento del detalle OS fall? por interpolaci?n de JavaScript antes de SSH; se corrigi? y la lectura posterior qued? en otro directorio. No fue un incidente ni un reintento de carga.

[Decisi?n agregada](preflight-os-watchdog-decision-2026-11-12.json).
