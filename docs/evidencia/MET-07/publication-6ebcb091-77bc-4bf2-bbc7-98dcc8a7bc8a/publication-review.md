# MET-07 ? Revisi?n y publicaci?n de cambios locales

Rama autorizada: feat/met-07-preparacion. Base local y remota antes del commit: 24620b231ef246d203f7220090bdacd039c717f9; divergencia 0/0 tras fetch. Esta publicaci?n conserva evidencia de preflights abortados, la correcci?n del selector del Deployment, validaci?n de cuatro forwards y auditor?a de apagado con canario independiente de solo lectura. No ejecuta el incidente ni acredita MET-07/P3-5. No se realizan operaciones sobre t?tulo, descripci?n, comentarios, revisiones o integraci?n del PR #94 y no se abre otro PR. El push ordinario de la rama actualiza naturalmente su contenido asociado.

## Resultados por suite de esta publicaci?n

Cada fila corresponde a una suite distinta. No se suman las ejecuciones hist?ricas de 58/62 pruebas ni las repeticiones. Todas las pruebas de esta tabla son fixtures o contratos locales: ninguna contacta Kubernetes/Azure ni inicia el watchdog operativo.

| Suite | Pruebas | Resultado v?lido |
| --- | ---: | --- |
| test_ci_gates.py | 8 | OK, WSL |
| test_k8s_delivery.py | 4 | OK, dobles locales de comandos |
| test_k8s_render.py | 11 | OK, contratos offline |
| test_met07_hardening.py | 11 | OK, WSL root; fixture aislado entre usuarios |
| test_met07_operate.py | 9 | OK, fixtures de precondiciones |
| test_met07_os_watchdog.py | 4 | OK, fixtures del backend sin mutaci?n |
| test_met07_preparation.py | 28 | OK, supervisor/recuperaci?n simulados |
| test_met07_signals.py | 10 | OK, fixtures de se?ales |
| test-observability.py | 4 | OK, contratos NetworkPolicy offline |

[suite-results.json](suite-results.json) conserva los resultados individuales iniciales. La primera ejecuci?n de hardening fall? exclusivamente porque sudo requer?a autenticaci?n; [hardening-root-result.json](hardening-root-result.json) registra su repetici?n con el privilegio que requiere el fixture. No se omiti? ni debilit? el test. No se repitieron las otras suites por ese fallo.

## Herramientas y seguridad

- npm.cmd ci: exit 0; prepare de Husky ejecutado, 1 paquete instalado, 2 auditados y 0 vulnerabilidades.
- Toolchain cargo 1.97.1; cargo fmt --all -- --check y hook real .husky/_/pre-commit: exit 0. core.hooksPath=.husky/_. Sin HUSKY=0 ni --no-verify. El commit volver? a ejecutar el hook normalmente.
- Comprobaciones de sintaxis Node, AST Python y git diff --check: exit 0. [Registro individual](local-checks.json).
- Revisi?n de archivos candidatos: sin valores reales de EVENT_PRODUCER_KEY/EVENT_ANALYST_KEY, claves privadas ni bloques de credenciales kubeconfig. Comparaciones de credenciales solo en memoria, sin imprimirlas. No se a?aden .env reales, tfstate ni kubeconfig. .env.example ya versionado conserva ?nicamente su papel de plantilla y no est? entre los cambios.
- Revisi?n manual: los JSON conservan contadores, identidades ficticias de lecturas, trazas, UID/boot_id, FQDN, ID de suscripci?n y rutas operativas necesarios para la auditor?a; no contienen cuerpos de lecturas personales, kubeconfig, claves SSH, tokens o cabeceras de autenticaci?n. Una ruta a un archivo SSH no contiene la clave. [Revisi?n autom?tica](sensitive-material-review.json).
- El script Docker scripts/scan-secrets.sh no complet?: el motor devolvi? error 500 en el diagn?stico y la invocaci?n del script agot? 25 s. **No se presenta como aprobado.**
- Se us? el mismo Gitleaks 8.28.0 nativo, con checksum oficial verificado y configuraci?n .gitleaks.toml sin nuevas excepciones. Escaneo de scripts y evidencias: sin hallazgos, con decodificaci?n hasta profundidad 3. Escaneo git --all: sin hallazgos; 203 commits alcanzables seg?n Git, 119 commits con contenido escaneado reportados por Gitleaks. [Resultado v?lido](secret-scan-final.json).
- El primer escaneo git nativo ley? cero commits por la referencia Windows del worktree: se conserv? como inv?lido, aunque devolviera exit 0. Se corrigi? con GIT_DIR/GIT_WORK_TREE traducidos a Linux. Un intento intermedio fall? porque WSL ya no conservaba el binario de /tmp; el resultado v?lido usa una ubicaci?n temporal persistente. [Intentos anteriores](secret-scan-results.json), [intento intermedio](history-scan-corrected.json).

No se ejecutan clippy, tests Rust/PostgreSQL, container, Terraform ni carga: los cambios son herramientas Python/Node, pruebas y evidencia, sin cambios de runtime Rust o manifiestos. No se atribuye a estas verificaciones el resultado de CI ni una nueva revisi?n CodeRabbit/humana. Esta publicaci?n no integra el PR; esas revisiones siguen siendo necesarias antes de integrar.

## Conservaci?n y procedencia

Se comprobaron los hashes de los 36 archivos del inventario hist?rico y de todos los archivos de evidencia existentes al comenzar la publicaci?n; ninguna evidencia original se reescribi?. El inventario de esta ejecuci?n contiene 66 archivos, incluidos dos artefactos de un intento inicial de esta publicaci?n. [SHA-256 original](original-evidence-sha256.json). Se verificar? tambi?n que los blobs de las evidencias nuevas coincidan con sus bytes locales al prepararlas para Git, evitando conversi?n CRLF al a?adirlas.

El primer control de nombres se detuvo por reconocer .env.example como candidato prohibido. Se corrigi? esa clasificaci?n y se conserv? el inventario inicial en publication-36a5e857-11d7-4e44-9d68-5ccff2335cdc; publication-current-path.txt corresponde exclusivamente a ese intento inicial, no a un resultado aprobado. Esta carpeta contiene la validaci?n completa.

Los preflights anteriores son evidencia real de lectura con worker 1/1, backlog 0 e inactive en las horas registradas. El canario real usa el motor del watchdog con backend sin capacidad de mutaci?n: prueba ACK/identidad/p?rdida de heartbeat, no restauraci?n de un worker degradado. Los tests con firing, degradaci?n o recuperaci?n simulados son fixtures. El apagado externo ARM sigue sin acreditar y el incidente sigue **no ejecutado**. No se refresca infraestructura durante esta publicaci?n.

[Inventario exacto para publicaci?n](published-files.txt). El SHA definitivo y la confirmaci?n del push se comunicar?n tras crear el commit, sin modificar esta evidencia para introducir un SHA circular.
