# Validación de preparación MET-07 — Refs #27

Base: origin/main 7607d54771cbadba29facd9d77aef5500ca2c2b9, worktree separado Proyecto-observabilidad-met07-prep, rama feat/met-07-preparacion.

## Resultados

| Control realizado | Resultado |
| --- | --- |
| scripts/met07.py plan | PREPARED_NOT_EXECUTED; no CLI de ejecución de incidente. |
| Pruebas aisladas MET-07 | 26 correctas; sin red, SSH, systemd, Kubernetes ni carga reales. |
| unittest discover de scripts/tests | 49 correctas: las 23 existentes y 26 de MET-07. |
| Contratos offline de observabilidad | 4 correctos. |
| cargo fmt --all -- --check | Código 0 con la versión fijada. |
| node --check del inspector | Código 0. |
| Gitleaks 8.28.0, redact, decode depth 3 | Cero hallazgos en scripts y docs/evidencia/MET-07; descarga temporal verificada por checksum. |
| Revisión de snapshot de solo lectura | Contexto, UID, réplica, labels, regla >100/2m, inactive y backlog cero comprobados. |
| Diff de Kubernetes | Vacío; reglas, réplicas e imágenes no modificadas. |

Salidas locales completas: [validation-preparation-final.txt](validation-preparation-final.txt). Se conserva la primera pasada de 47 tests en [validation-preparation.txt](validation-preparation.txt), anterior a los dos casos adicionales de ACK remoto y desfase de reloj. Los mensajes NativeCommandError de PowerShell envuelven stderr informativo de unittest/Gitleaks; los códigos finales reales son 0.

Las pruebas negativas contrastan: bloqueo de namespace/contexto/UID incorrectos; selector y propietario de Pod/ReplicaSet; HPA y generación no observada; autorización/aislamiento ausentes; JSON Patch con pruebas atómicas; falla de ACK; watchdog fuera de la sesión local; pérdida de heartbeat; plazo de 540/600 s; reinicio de boot_id; restauración reintentada y estado Ready; fallo/cancelación/timeout/escala incierta; HTTP recibido con fallo posterior de conexión; intento sin resultado, HTTP 5xx y UUID ausente/ajeno/pendiente; intervalos sin solicitudes; y protección de evidencia y secretos.

La primera simulación detectó que el camino tardío de timeout podía abandonar la restauración al comprobar el plazo antes de intentarla. Se corrigió: intenta restaurar incluso tarde, registra deadline_exceeded y conserva el resultado fallido. También se corrigió el fixture para usar la estructura real por etapas de kubernetes/resources.json. Las nuevas pasadas son satisfactorias; esto no convierte las simulaciones en un incidente cloud.

## Observación real y límites

[preparation-readonly.json](preparation-readonly.json) es una observación real de solo lectura a las 2026-11-12T07:21:23Z del servidor:

- default / eventos-development, worker UID f1c9cafa-7fe9-4495-b806-94776f8a8326, réplica original 1 y Ready=1;
- ambos labels reales del worker y args=process;
- Prometheus HTTP 200, HighEventBacklog inactive, health ok, expresión >100 sin cambios, duración 120 s y backlog=0.

No se capturó firing real ni evidencia real durante/después de una degradación. La regla se prueba en los tres estados mediante fixtures. No se armó ningún watchdog real, no se invocó Experiment.run contra infraestructura y no se comprobó autorización para incidentes ni aislamiento. La preparación no sustituye las pruebas de armamento/ACK y de restauración que deberá observar una ejecución autorizada.

No se recompiló la aplicación ni se repitió aquí clippy, la suite Rust, rustdoc o aceptación ignorada con BD: no se cambió Rust. No se afirma aceptación PostgreSQL sin BD dedicada. No se construyó o escaneó una imagen ni se modificó Terraform. La fase inicial terminó sin commits ni PR. Esta entrega publica únicamente feat/met-07-preparacion para revisión; no crea otro PR ni modifica feat/met-07-degradacion, rama del PR #94. El incidente continúa sin ejecutar.

## Controles para publicación

Se repitieron 49 pruebas aisladas de scripts y cuatro contratos de observabilidad, más la validación local del snapshot histórico ya guardado. Gitleaks no encontró secretos. La salida separada está en [validation-publication.txt](validation-publication.txt), marcada como validación local: no es una nueva observación de Azure ni prueba de un incidente. El snapshot real preparation-readonly.json y los dos logs originales se conservaron íntegros.

Se ejecutó npm ci, core.hooksPath=.husky/_, cargo fmt --all -- --check y node --check del inspector, sin omitir controles. El commit usa los hooks instalados. No se ejecutó el inspector remoto en esta fase y no se escala, reinicia o genera carga. El PR #94 tiene otra rama de origen; la publicación no la modifica ni crea otro PR.
