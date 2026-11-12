# MET-07 · Corrección de identidad, asociaciones y señales — Refs #27

**Preparación corregida; incidente no ejecutado.** No se ha arrancado un watchdog real, enviado carga, escalado o reiniciado un recurso. No se modifica el PR #94 ni su rama. Los snapshots y logs originales de 9cdeb8a se conservan; los resultados de esta revisión son pruebas locales y validación del snapshot histórico, no observaciones cloud nuevas.

## Identidad y permisos

Supervisor y watchdog utilizan el **mismo UID y GID efectivos Linux**, con UID real=efectivo y GID real=efectivo. Se guarda identity={uid,gid} en el contexto y restore-state.json. La unidad systemd tiene User=<uid>, Group=<gid> y UMask=0077 explícitos: no depende de la identidad predeterminada root del gestor.

El directorio de IPC/evidencia debe pertenecer a esa identidad y ser exactamente 0700; todos los archivos son 0600. Se rechazan propietario/grupo distintos, modos incompatibles, enlaces simbólicos, enlaces duros y tipos de archivo inesperados. La validación no usa la capacidad de root para eludir el propietario esperado.

Antes de leer Kubernetes o emitir peticiones del experimento se comprueba el acceso del supervisor. Antes de escalar se verifica el estado privado, se escribe heartbeat, el proceso watchdog lo puede leer y crea ACK con identidad, run y UID del Deployment coincidentes. El supervisor valida dueño/grupo/modo y contenido del ACK. Esta comunicación acredita acceso en ambas direcciones para la identidad acordada; resultados y heartbeat usan el mismo contrato de archivos. Un directorio heredado con otro grupo o archivos antiguos de root no se vuelve accesible relajando permisos: se rechaza y se prepara una ubicación nueva correcta.

Pruebas:
- dos procesos con la misma identidad de fixture leen/escriben state, ACK, heartbeat y resultados;
- otro UID no puede leer ACK ni escribir heartbeat;
- se rechaza GID diferente aunque coincida el UID, propietario distinto, modos 0640, symlinks e identidad de ACK/proceso incompatible;
- root tampoco pasa la comprobación de política para archivos de otro propietario;
- la incompatibilidad se rechaza antes de llamar al adaptador Kubernetes.

La prueba entre usuarios cambia UID/GID **solo en hijos de un proceso local de fixture** y usa un directorio temporal nuevo. Requiere root local o sudo no interactivo; no crea cuentas ni unidades systemd. En este equipo sudo sin contraseña no estaba disponible: esa pasada falló por precondición y se repitió con WSL --user root. No se cuenta el fallo como prueba aprobada, ni se atribuye esa capacidad de prueba a la VM de Azure.

## Asociación exacta de recepción y procesamiento

processed() verifica:
1. inicios y resultados únicos por attempt, sin huérfanos ni intentos sin terminar;
2. device_id/event_id iguales entre inicio y resultado;
3. respuesta HTTP 202/200 confirmada, sin error de conexión y con UUID canónico;
4. correspondencia uno a uno entre ese UUID y el par dispositivo/evento, incluyendo retransmisiones consistentes;
5. igualdad exacta de id/device_id/event_id con cada fila persistida, sin filas duplicadas, ajenas o ausentes;
6. received_at y processed_at RFC3339 con zona válida, y procesamiento no anterior a recepción.

Intercambiar event_id entre dos filas con el mismo conjunto de UUID ya no pasa. Tampoco pasan UUID asociados a otro evento/dispositivo, timestamps nulos, inválidos, sin zona, fechas inexistentes u orden temporal inverso. Los timestamps se comparan normalizados a UTC; no se comparan con el reloj local ni con occurred_at ficticio de 2040.

## Logs y trazas antes/durante/después

El [colector preparado](../../../scripts/met07_signals.py) no ejecuta lecturas al importarse. Su modo predeterminado prepared solo produce instrucciones; collect/start_follow exigen modo fixture o real-read-only explícito.

Para la futura ejecución autorizada, el adaptador puede pasar a Experiment un signals_factory que construya SignalCollector(kube,http,uid,device,mode="real-read-only"). Esto **no se ha hecho contra infraestructura** en esta revisión.

Secuencia implementada:
- iniciar followers de logs API/worker antes del productor y antes de degradar;
- capturar las tres fronteras de fase con Prometheus time(), no hora del portátil;
- mantener un buffer acotado y persistir únicamente candidatos de log saneados en JSONL privado; el stream del Pod worker anterior se conserva aunque el Pod desaparezca;
- detener los followers en la limpieza, después de solicitar restauración; si fallan al iniciar, no escalar;
- recuperar candidatos durables tras cancelación con restore_buffers, rechazando otro dispositivo/contexto/Deployment;
- después de recuperar capacidad y verificar UUID, consultar las ventanas before/during/after y Jaeger; no retrasar la restauración para recoger señales.

Las consultas de lectura usan contexto/namespace explícitos y Pods cuyo ReplicaSet pertenece al Deployment. Se conserva el Pod UID. Los logs se obtienen con timestamps del servidor y since-time; las trazas usan las fronteras del servidor y los received_at/processed_at durables, con margen explícito de 60 s para incluir el padre HTTP. La recolección after puede abarcar todo el ciclo de las lecturas, incluido su padre API anterior a recepción. Cada entrada/span indica si está dentro de la fase solicitada: una traza del worker posterior no demuestra procesamiento mientras estaba en cero.

El buffer conserva solo UUID, trace_id/span_id, receipt_id, request_id validado, outcome y tiempo/pod/componente. No conserva mensaje bruto, payload, headers, credenciales, etiquetas arbitrarias ni diagnósticos de error. Las trazas solo retienen servicios/operaciones, identificadores, referencias y tags permitidos; request_id se cruza con las solicitudes conocidas. Los límites de stream/consulta quedan registrados; truncamiento o límite de 1000 trazas impiden declarar cobertura final completa.

La comprobación final exige para cada UUID:
- span process_reading del worker con CHILD_OF al http_request API de la misma traza;
- request_id esperado, ruta /v1/readings y 202/200;
- logs tanto de API como de worker con ese UUID y un trace_id de la correlación validada.

Muestreo, expiración, pérdida de logs, respuesta HTTP fallida, conexión fallida o falta de padre/UUID dejan cobertura incompleta; no se rellenan ni se inventan señales.

## Procedencia y aceptación

| Material | Significado |
| --- | --- |
| PREPARED_COLLECTION_PLAN / signal-collection-plan.json | Instrucciones y ventanas derivadas de datos del supervisor; observations_collected=false. No son logs/trazas observados. |
| FIXTURE_SIGNAL_OBSERVATION | Salida de pruebas simuladas; solo en directorios temporales de tests. No evidencia cloud. |
| REAL_READ_ONLY_SIGNAL_OBSERVATION | Reservado para consultas futuras explícitas de lectura; el colector no induce un incidente. |
| preparation-readonly.json existente | Observación real histórica, sin modificar. No contiene evidencia durante/después de un incidente. |

acceptance.json sin observador declara functional_recovery_only y logs_and_traces_collected=false. Con observador, las señales se validan antes de marcar la aceptación y se registra signal_provenance. Una cobertura de UUID no acredita disponibilidad continua: se mantienen el registro de intentos y los intervalos sin solicitudes.

Los tests verifican captura de las tres fases, supervivencia del buffer al cambio de Pod, recuperación del JSONL saneado, desfase local, exclusión de campos sensibles, padres/request_id/UUID incorrectos, contexto ajeno, errores HTTP/conexión, truncamiento y límites. Todos usan HTTP, Kubernetes, logs y procesos simulados. La única prueba con usuarios reales de Linux es la de permisos de archivos temporales; no ejecuta watchdog ni red.

## Resultados de esta revisión

Pasaron 72 pruebas de scripts (incluidos los casos locales entre UID/GID distintos y las tres fases de señales) y cuatro contratos de observabilidad. Gitleaks 8.28.0 no encontró secretos. También pasaron npm ci, formato Rust con la versión fijada y node --check del inspector. Los hooks Husky permanecen activos y el commit los ejecuta sin omitirlos. La salida nueva es [validation-hardening.txt](validation-hardening.txt); su cabecera declara fixtures, cero watchdogs reales, cero lecturas cloud nuevas e incidente no ejecutado. El envoltorio NativeCommandError de PowerShell contiene stderr informativo de los validadores; el EXIT_CODE final es 0.

No se cambió Rust, Kubernetes, imágenes, réplicas ni umbrales. No se repitieron clippy, la suite Rust o aceptación con PostgreSQL para estas modificaciones de herramientas Python; no se atribuye a esta revisión una aceptación cloud ni con BD. La publicación permanece en feat/met-07-preparacion; no crea otro PR ni actualiza el PR #94.
