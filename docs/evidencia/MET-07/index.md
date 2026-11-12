# MET-07 · Preparación de degradación y recuperación — Refs #27

**Estado: preparado y validado con simulaciones; incidente NO ejecutado.** Esta entrega no escala, reinicia ni genera carga. No acredita la aceptación de #27, P3-5 ni una defensa. Se conserva la [auditoría de 2026-11-11](../ESC3/auditoria-2026-11-11.md) como antecedente: sus pendientes se contrastan aquí, sin convertir el plan en evidencia de ejecución.

Worktree separado: Proyecto-observabilidad-met07-prep; rama feat/met-07-preparacion, base origin/main 7607d54771cbadba29facd9d77aef5500ca2c2b9. Los worktrees de MET-05 y de la preparación antigua no se modifican.

## Comprobación real de solo lectura

[preparation-readonly.json](preparation-readonly.json) fue obtenido mediante [inspect-readonly.cjs](inspect-readonly.cjs), sin leer Secrets ni imprimir/guardar claves:

| Dato observado | Resultado |
| --- | --- |
| Hora del servidor | 2026-11-12T07:21:23Z |
| Contexto / namespace | default / eventos-development |
| Deployment | event-service-worker |
| UID | f1c9cafa-7fe9-4495-b806-94776f8a8326 |
| Réplica original / Ready | 1 / 1 |
| Selector real | app.kubernetes.io/component=worker,app.kubernetes.io/name=event-service |
| Comando del contenedor | process |
| Imagen | digest 17b4e6051228fd27df63471a3fff003bd8f2cb7ca916ef8e29d96a29835597e9 |
| Prometheus rules / queries | HTTP 200 |
| HighEventBacklog | inactive; health=ok |
| Expresión / duración | esc3_events_backlog_total > 100 / 120 segundos |
| Backlog consultado | 0 |

Esto verifica un estado anterior de lectura, no aislamiento ni autorización para un incidente. El snapshot declara execution_authorized=false e isolation_verified=false. Un namespace development compartido no se convierte en un entorno aislado por tener ese nombre. El UID/contexto/réplica se deben refrescar inmediatamente antes de una eventual ejecución y contrastar con la autorización; no se reutiliza esta observación como permiso.

La instrumentación y la regla están implementadas en main. La observación anterior verifica su disponibilidad actual en ese endpoint. **No se observó firing real**: inactive/pending/firing se contrastan con fixtures en las pruebas aisladas; obtener firing real y analizarlo sigue pendiente de la ejecución autorizada.

## Hipótesis y alcance

Reducir temporalmente la capacidad del worker process a cero debe detener el procesamiento mientras /v1/readings continúa aceptando lecturas válidas en un inbox durable. El backlog debe crecer, la regla debe llegar a firing y, después de restaurar la réplica original, todos los UUID confirmados deben procesarse y la alerta volver a inactive.

No se cambian imágenes, límites, reglas ni umbrales: se conserva estrictamente **>100 durante 2m**, severidad critical. Los snapshots conservan tasas de entrada/procesamiento en lecturas/s sobre ventanas móviles de un minuto, backlog en lecturas, p95 HTTP en segundos y la serie de errores 5xx. Series ausentes o NaN no se rellenan con cero. El experimento no acredita saturación física, HA ni aislamiento entre namespaces en el nodo compartido.

## Herramientas preparadas

- [scripts/met07.py](../../../scripts/met07.py): supervisor T0–T5, cliente HTTP sin redirects, JSONL por intento, comprobación de Prometheus/UUID y watchdog remoto independiente. Python estándar; no introduce runtime Node en la aplicación.
- [scripts/tests/test_met07_preparation.py](../../../scripts/tests/test_met07_preparation.py): pruebas locales con Kubernetes, HTTP, reloj, señales y thread de carga simulados; no contactan Azure.
- El CLI expone solo plan (por defecto) y el subcomando interno watchdog. **No existe CLI execute/run**. La API Experiment.run permanece preparada para un adaptador operativo revisado y una autorización separada; esta entrega no la invoca contra infraestructura real.
- inspect-readonly.cjs solo contiene comandos fijos de lectura. Para repetir esa inspección se debe usar un nombre de evidencia nuevo; nunca sobrescribe un snapshot.

Comandos seguros de preparación, ejecutados sin incidente:

~~~sh
python3 -B scripts/met07.py plan
python3 -B -m unittest discover -s scripts/tests -p test_met07_preparation.py -v
~~~

No ejecutar manualmente watchdog ni importar/invocar Experiment.run como parte de la preparación. El watchdog solo tiene sentido armado por el supervisor con estado nuevo, UID validado y autorización.

## Procedimiento operativo preparado — pendiente de autorización

### T0 · Contexto, aislamiento y línea base

1. Obtener aprobación explícita del incidente y evidencia de aislamiento. El supervisor exige incident_authorized=true, isolated=true, isolation_review_ref, context, namespace y deployment_uid. Esa estructura no demuestra aislamiento por sí sola: un operador distinto debe revisar el entorno, las dependencias compartidas, el tráfico ajeno y la ventana de operación.
2. Ejecutar el supervisor en el **servidor Linux revisado**, con systemd disponible y sudo no interactivo para K3s y systemd-run. No correrlo en la estación local: el watchdog y el supervisor deben compartir host, boot_id y reloj monotónico.
3. Confirmar que no hay apagado/reinicio de VM programado dentro de la ventana y disponer de un operador con canal independiente. La VM es de un solo nodo; no se autoriza cambiar Terraform o crear recursos Kubernetes para resolver esa precondición.
4. Verificar contexto activo y fijarlo explícitamente en todos los comandos. Exigir exactamente un Deployment worker con ese UID, una réplica Ready/Available de la generación actual, args=[process], labels correctos, un Pod perteneciente a un ReplicaSet del Deployment y ausencia de HPA que altere sus réplicas. Comprobar permiso patch.
5. Abrir un directorio **nuevo** en disco del servidor, con permisos restringidos; preservar el estado original reducido a contexto, namespace, UID, réplica, selector, imagen y resourceVersion. No guardar kubeconfig, Secrets, tfvars, claves ni headers de autenticación.
6. Consultar /api/v1/rules y exigir una regla HighEventBacklog inequívoca, health=ok, expresión original y duration=120. Exigir inactive y backlog cero como línea base. Error HTTP, respuesta Prometheus fallida, regla ausente/duplicada o target de otra namespace bloquean el experimento.
7. Los puertos loopback de API/Prometheus deben estar disponibles desde ese servidor. Si dependen de un SSH local, su pérdida debe producir fallo y restauración; el watchdog accede a K3s localmente y no depende de esos túneles. Las credenciales se suministran únicamente al entorno del proceso supervisor por un canal seguro, nunca como argumentos ni archivos.

### T1 · Carga instrumentada y línea base activa

Registrar un dispositivo ficticio único y emitir lecturas físicas válidas a **2 intentos/s** durante diez segundos de línea base. Mantener el productor activo durante T2, la espera de eliminación de Pods, toda la detección T3 y la recuperación T4, hasta confirmar que el worker restaurado está Ready. No detener la carga al cumplir dos minutos.

No se usa el resumen de scenario_load como evidencia por intento. El registrador nuevo escribe y fsync antes del envío attempt_started y después attempt_result, con:

- índice de intento, event_id y device_id, fase y hora monotónica del envío programado/iniciado;
- ancla UTC obtenida de Prometheus time(), con su instante monotónico de muestreo;
- HTTP real o null si no llegó respuesta; fallo de conexión/timeout separado;
- reading_id de la respuesta, Date del servidor cuando existe y final monotónico;
- retrasos de programación explícitos, sin compensarlos con ráfagas ocultas.

Un fallo leyendo el cuerpo conserva el HTTP ya recibido. Un intento iniciado sin resultado es incierto, no se reclasifica como rechazado ni se reenvía automáticamente. Las fechas occurred_at de los payloads son ficticias (2040); no se usan para cronometrar el incidente.

### T2 · Armar recuperación antes de degradar

Persistir restore-state.json con run, boot_id, identity (UID/GID Linux del supervisor y watchdog), contexto/namespace, UID, réplica original, selector, imagen, ancla del servidor y degraded_mono/deadline_mono. El reloj de seguridad comienza **antes** del primer intento de escala a cero; el plazo máximo es 600 segundos.

Antes de cambiar réplicas, iniciar y recibir ACK de un watchdog en una unidad systemd remota independiente met07-guard-<run>, con Restart=on-failure, User/Group iguales al supervisor y UMask=0077. Directorio 0700 y archivos 0600, con propietario/grupo comprobados antes de escalar. El ACK debe coincidir con run y UID, en el directorio nuevo. Si no confirma arranque, no degradar.

La única mutación preparada es un JSON Patch del número de réplicas del Deployment, con pruebas atómicas de UID, resourceVersion y réplica actual. Un resultado incierto de la petición entra igualmente en limpieza. Nunca se sustituye la réplica original por un 1 fijo sin contrastarla: el preflight exige una réplica y guarda ese valor, y la restauración utiliza el valor guardado.

Esperar como máximo 60 s a que la lista de Pods del selector real quede vacía:

~~~text
app.kubernetes.io/component=worker,app.kubernetes.io/name=event-service
~~~

La espera se realiza mediante listados comprobados, no con app=event-service-worker, que no selecciona los Pods reales. El productor sigue enviando durante esa espera. Eliminar Pods no demuestra por sí solo que el servicio de ingesta continúe disponible.

### T3–T4 · Detección y restauración normal

Tomar snapshots periódicos de reglas, métricas y ledger mientras se mantiene la carga. Registrar hora UTC del servidor, no la del portátil. La latencia de cada operación HTTP/Kubernetes está acotada; cualquier fallo del observador interrumpe la vía normal y activa limpieza.

La recuperación normal requiere consultar y guardar **firing** real de HighEventBacklog para el target API del namespace previsto. Superar 100 en el gauge, dormir 120 s o ver pending no sustituye esa prueba. La evaluación de Prometheus puede añadir retraso; no se reduce el umbral para conseguir firing.

Después de observar firing, restaurar con prueba de UID/resourceVersion y réplica original, esperar Ready/Available con observedGeneration actual y entonces detener la carga. Registrar el final de la ventana degradada. Si interviene el watchdog o vence el plazo, no marcar el experimento como éxito normal aunque se consiga recuperar.

### Recuperación de seguridad y pérdida de conexión local

- SIGINT, SIGTERM y SIGHUP activan cancelación y finally; error de HTTP, registro, observación, borrado de Pods o escala incierta también conduce a restauración.
- El watchdog independiente restaura al perder el heartbeat del supervisor durante **30 s**, o al alcanzar **540 s desde T2**. No espera al límite de 600 s para empezar. No necesita la sesión SSH ni las claves de API.
- Si se corta la conexión local y SIGHUP llega al supervisor, este restaura; si el supervisor muere sin ejecutar finally, el watchdog conserva el estado en disco y restaura por lease/deadline. Si continúa vivo, el plazo remoto permanece vigente.
- Una restauración tardía se intenta de todos modos y se marca deadline_exceeded; nunca se abandona el intento solo porque el plazo ya venció. Los fallos de restauración dejan al watchdog reintentando y un archivo de fallo, no una prueba de éxito.
- La unidad solo escribe guard-restored.json cuando el UID coincide, la réplica original está aplicada y la generación actual está Ready/Available; registra si ocurrió dentro del plazo.
- Nunca se toca un Deployment de reemplazo con otro UID ni una escala concurrente inesperada. Esos casos requieren intervención independiente y no cumplen la aceptación.
- El límite de diez minutos es una condición verificable, no una garantía física frente a VM apagada, API Kubernetes inaccesible, nodo bloqueado o Deployment borrado. El watchdog transitorio tampoco sobrevive al reinicio de la VM: excluir ese evento en las precondiciones. Si ocurre, el experimento falla y el operador debe recuperar manualmente con la identidad guardada; no inventar evidencia de restauración.

### T5 · Validar recuperación y todos los UUID

Con el productor detenido **después** de recuperar capacidad, consultar hasta observar simultáneamente en un sondeo:

1. worker Ready/Available de la generación actual y UID original;
2. backlog global del target cero;
3. HighEventBacklog de vuelta en **inactive** en Prometheus (no basta una captura de Grafana);
4. pending=0 del dispositivo.

La comprobación posterior tiene un plazo propio de 180 s; nunca prolonga la degradación para conseguir evidencia. Recorrer el histórico paginado, guardar los received_at/processed_at durables y contrastar el conjunto exacto de UUID con todas las respuestas 202/200, incluyendo línea base y ventana degradada. Exigir processed_at en todos, ausencia de filas ajenas, consistencia de event_id/idempotencia y accepted=processed=número de UUID confirmados. Un 5xx, timeout, intento incompleto o ID ausente impide concluir ingesta sin interrupciones; una operación incierta exige reconciliación de solo lectura por event_id, no repetir escrituras a ciegas.

## Evidencia y análisis antes/durante/después

| Archivo previsto | Contenido y criterio |
| --- | --- |
| context.json / restore-state.json | Identidad de recurso, réplica original y límite remoto; sin credenciales. |
| events.jsonl | Snapshots UTC de servidor, inicio/resultado por intento, firing, restauración, Ready y errores de control. |
| request-free-intervals.json | Todos los intervalos entre envíos y bordes de T2–T4, duración, período objetivo 0.5 s y missed_schedule. No se interpolan solicitudes. |
| guard-ready.json / heartbeat.json / guard-restored.json / guard-failure.json | Arranque y actuación del watchdog; un ACK no prueba una restauración. |
| control-result.json | Distingue vía normal con firing de aborto/restauración de seguridad; no sustituye aceptación. |
| after-readings.json / acceptance.json | Histórico real y comprobación final de todos los UUID, ledger, backlog cero y alerta inactive. |

En el informe posterior: calcular intentos/s y aceptados/s por fase sobre la duración realmente cubierta; tasas de procesamiento a partir de métricas y filas; backlog máximo/retraso; tiempo servidor a pending/firing/restauración/Ready/inactive; distribución HTTP, 5xx y fallos de conexión; p95 de latencia observado; y todos los intervalos sin solicitudes. Indicar aparte las ventanas antes del productor y después de su parada. Un tramo sin solicitudes no acredita disponibilidad y no se incluye como solicitudes exitosas. Si hay huecos, limitar la conclusión a los intentos observados.

El mecanismo causal se aceptará solo si la evidencia muestra: capacidad cero y falta de procesamiento, recepción durable durante la degradación, acumulación, firing, restauración y drenaje de los mismos UUID. Añadir limitaciones, resultados contrarios a la hipótesis y al menos la comparación cuantificada antes/después. Hasta entonces este documento sigue siendo un procedimiento preparado, no un análisis de incidente ejecutado.

## Validación de esta preparación

Los resultados locales y sus límites se registran en [validation-preparation.md](validation-preparation.md). El snapshot de lectura no modifica el entorno. No hay todavía evidencia real durante/después del incidente ni firing inducido, y no se solicita cerrar #27 u otros issues.

## Correcciones posteriores: identidad y señales

El contrato de identidad privada, las asociaciones exactas por evento y el observador de logs/trazas se describen en [hardening-identity-signals.md](hardening-identity-signals.md). Los snapshots originales y el estado no ejecutado se mantienen. El observador opcional inicia logs antes de la carga futura, conserva los del worker eliminado y consulta trazas después de recuperar capacidad. Sus planes se distinguen de fixtures y observaciones reales; sin observador no se declara cobertura de logs/trazas.
