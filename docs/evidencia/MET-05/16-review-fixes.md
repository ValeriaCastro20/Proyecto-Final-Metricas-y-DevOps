# Correcciones de revisión de MET-05 / PR #93

Esta revisión corrige verificadores y transporte; no repite la carga, no inicia túneles reales, no ejecuta comandos remotos y no modifica Kubernetes. Los JSON, logs y capturas originales del commit 8896d8d se conservan intactos, incluido el timeout de 04 y el desfase de reloj de 09. Los scripts actuales son una revisión posterior y no se presentan como los que produjeron aquellas salidas.

| Hallazgo contrastado | Corrección | Prueba negativa aislada |
| --- | --- | --- |
| HTTP/Prometheus fallidos podían terminar con éxito; provisión incompleta | Se registra la respuesta y se exige HTTP 200, status success, datasource provisionado de solo lectura, UID y ocho paneles con consultas coincidentes. | 404, error Prometheus bajo HTTP 200, dashboard no provisionado, panel ausente y datasource/consulta incorrectos. |
| every sobre lista vacía aceptaba targets ausentes | Se exige al menos un target API y uno worker; todos los correspondientes deben estar up y sin lastError. | Ninguno, solo uno de los jobs, target adicional down y lastError. |
| Ventana local excluía trazas por desfase | Los dos flujos 09/10 usan received_at/processed_at durables, validados, con margen de 60 segundos. | Reloj local en 2099, fechas nulas y fallo HTTP de Jaeger. |
| El flujo 09 aceptaba una correlación parcial | El polling solo finaliza al cubrir diez UUID distintos con servicios, ruta, 202 y referencia CHILD_OF al padre API de la misma traza. | Cero, una y nueve lecturas; padre ausente, traza ajena, servicio/ruta/estado incorrectos y UUID duplicado. |
| Capturas antiguas y ejecuciones mezcladas podían aceptarse | Directorio nuevo obligatorio, captura en ruta temporal nueva, salida Chrome y archivo nuevo verificados; cruce de dispositivo, run, conjunto de UUID y trazas antes de capturar. Nuevas correlaciones incluyen SHA-256 de su fuente. | PNG anterior, ENOENT, timeout, salida no cero, ausencia de archivo nuevo, mtime antiguo, dispositivo/UUID/digest de otra ejecución y fallo funcional ajeno. |
| El pipeline remoto ocultaba fallos del decodificador | Bash remoto explícito con pipefail; salida no cero de SSH propagada y salida escrita solo en un directorio nuevo. | Decodificador fallido/ausente, base64 truncado y script con exit 7; wrapper SSH simulado devuelve 23 y no sobrescribe su log. |
| Los túneles secuenciales bloqueaban el resto | Cuatro procesos independientes, incluido API 28000:8000, arrancan antes de esperar. Se rechazan puertos ocupados; se comprueba proceso vivo y endpoint HTTP. En fallo se detienen solo los procesos propios; en éxito permanecen activos. | Dobles de Start-Process, puertos y HTTP: orden concurrente, API presente, puerto ocupado, fallo al arrancar, proceso terminado y timeout. |

## Pruebas y uso de las versiones corregidas

Los 24 tests se ejecutan con:

~~~sh
node --test docs/evidencia/MET-05/tests/verification.test.cjs
~~~

No utilizan credenciales reales, red, navegador real, SSH ni generador: los accesos se sustituyen por dobles y el pipeline Bash se prueba localmente. Los JSON históricos solo se leen como fixtures. En Windows, el único uso de WSL en estos tests es ejecutar Bash local. CI ejecuta estas pruebas en el job quality; usa Node, Bash y PowerShell ya presentes en el runner Ubuntu.

Las invocaciones históricas del README describen lo realmente ejecutado antes de esta revisión. Las versiones actuales de 05, 06, 08, 09 y 10 exigen --output con un directorio que todavía no exista; nunca sobrescriben los originales. Ejemplos para un operador autorizado (no ejecutados en esta revisión):

~~~sh
node docs/evidencia/MET-05/05-verify.cjs --output /ruta/nueva/verificacion
node docs/evidencia/MET-05/10-correlation.cjs --functional /ruta/09-functional.json --output /ruta/nueva/correlacion
node docs/evidencia/MET-05/09-screenshots.cjs --functional /ruta/09-functional.json --correlation /ruta/10-correlation.json --output /ruta/nueva/capturas
~~~

El padre de cada directorio de salida debe existir. 09-functional sigue siendo una operación de escritura autorizable por separado: requiere --output nuevo y emite una sola vez diez lecturas; no debe ejecutarse para comprobar estas correcciones. 08 enumera trazas; no acredita correlación de negocio.

Invoke-Remote.ps1 exige ahora -OutputDirectory nuevo además de -ScriptFile y -LogName. Ejecutar tunnels.ps1 inicia los cuatro túneles y devuelve sus procesos después de validar endpoints; importarlo con dot-source solo define las funciones. Si ya hay túneles activos se rechaza el arranque; no se matan ni sustituyen conexiones existentes.

## Evidencia de validación

- [Pruebas negativas: 24 correctas, cero fallidas u omitidas](15-review-negative.txt).
- [Controles locales Rust con la versión 1.97.1/MSVC](14-review-quality.txt).
- El estado de CI y CodeRabbit corresponde al SHA publicado y se comunica en el PR; las salidas históricas no se vuelven a etiquetar como nuevas.
- La aceptación PostgreSQL ignorada requiere una BD dedicada; su ausencia no se considera aceptación local. Terraform no aplica: no hay cambios de infraestructura.

Refs #25. El PR continúa exclusivamente en MET-05. No se ejecuta MET-07 ni se solicita cerrar issues o integrar.

Resultado local final: los cuatro controles Rust finalizaron con código 0 (fmt, clippy, tests y rustdoc con -D warnings), además de 24 pruebas negativas, cuatro contratos de observabilidad y 23 tests de scripts. Gitleaks no encontró secretos y kubeconform validó 17 recursos; salida nueva en [17-review-security.txt](17-review-security.txt). Los 22 artefactos originales JSON/TXT/PNG coinciden con sus objetos Git en 8896d8d, respetando la normalización CRLF ya existente del checkout; no se reescribieron. El envoltorio NativeCommandError de PowerShell en los logs corresponde a stderr informativo; los EXIT_CODE reales son 0.
