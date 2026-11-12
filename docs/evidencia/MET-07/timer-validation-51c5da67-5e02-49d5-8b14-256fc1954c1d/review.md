# MET-07 ? Inventario estricto de timers

power_check solo construye timer_units cuando systemctl devuelve un array JSON de objetos y cada unit es un string no vac?o tras strip. Cualquier fila inv?lida invalida todo el inventario. Para aprobar se exige timer_units distinto de None. El array vac?o [] conserva su validez y los timers de apagado siguen bloqueando la aprobaci?n.

Cinco regresiones nuevas cubren JSON inv?lido, valores ra?z que no son arrays, elementos que no son objetos, unit ausente/null/vac?o/blanco/no textual, listas mixtas, inventario vac?o v?lido, objetos v?lidos con campos adicionales y timer de apagado v?lido.

| Suite aislada | Pruebas | Resultado |
| --- | ---: | --- |
| test_met07_operate.py | 14 | OK |
| test_met07_preparation.py | 28 | OK |
| test_met07_hardening.py | 11 | OK |
| test_met07_signals.py | 10 | OK |
| test_met07_os_watchdog.py | 4 | OK |

Todas se ejecutaron una vez en WSL root con fixtures offline, sin red, Kubernetes, systemd ni incidente real. Los detalles por suite est?n en suite-results.json; no se suman ejecuciones anteriores.

npm ci pas?: prepare de Husky, cero vulnerabilidades. Pasaron cargo fmt --all -- --check, el hook real .husky/_/pre-commit, hooksPath=.husky/_ y git diff --check. El commit vuelve a ejecutar Husky sin bypass. Ver local-checks.json. No se ejecutan tests Rust/PostgreSQL ni container porque no cambi? el runtime Rust ni la imagen.

Se verificaron 76 archivos de evidencia anteriores por SHA-256. El inventario nuevo usa filas sha256/path: Gitleaks detect? inicialmente dos hashes como generic-api-key al colocarlos detr?s de nombres que contienen secret. Se cambi? exclusivamente esa representaci?n, preservando hashes y rutas, sin excepciones a la configuraci?n de Gitleaks ni cambios en evidencias originales. No eran credenciales. Se usa Gitleaks 8.28.0 nativo cuyo checksum oficial ya fue verificado; Docker no se requiere para esta comprobaci?n equivalente. El escaneo aprobado se registra en secret-scan.json y el historial con el commit se comprobar? antes del push.

No se consult? Azure ni el cl?ster, no se ejecut? MET-07 y no se realizan acciones sobre #94. Publicaci?n ordinaria en feat/met-07-preparacion, sin force-push; no se afirma nueva revisi?n humana/CodeRabbit ni se integra el PR.
