# MET-07 ? Preparaci?n de lanzamiento operativo

Ventana aceptada por el usuario: **2026-11-12T21:00:00Z?23:00:00Z**. La ausencia de automatizaciones externas se conserva como confirmaci?n del administrador transmitida por el usuario, no como consulta ARM propia ni mensaje autenticado directamente por el agente. Ver administrator-confirmation.json. El lanzamiento mantiene azure_schedules_verified=false y arm_query_performed=false y explicita external_shutdown_basis=user_relayed_administrator.

El nuevo met07_launch.py es el supervisor operativo y met07_launch_dispatch.cjs instala fuentes privadas, transporta las claves exclusivamente por stdin SSH y admite una sola invocaci?n. Los despachadores diagn?sticos anteriores no lanzan el incidente. Se conserva un marcador exclusivo, sin reintento autom?tico. No hay commits, push ni acciones sobre #94 en esta sesi?n.

El reloj del servidor Linux controla la espera y la admisi?n. No se crean forwards, guard, dispositivo ni carga antes de las 21:00 UTC. Para entrar, registrar el dispositivo, armar el guard y reducir capacidad se exige ventana vigente y **m?s de 1200 s** restantes. Fuera de la ventana o con margen insuficiente se bloquea. La recuperaci?n contin?a con el watchdog independiente y no se condiciona a abrir otro incidente.

Dentro de la ventana se refrescan: SHA revisado de vm-power.yml, todos los workflows activos del repositorio, Scheduled Events, inventario estricto de timers, crontab y apagado pendiente, contexto/namespace/UID/generaci?n/r?plica/propietarios/HPA/permisos, endpoints con autenticaci?n, baseline cero/inactive y recepci?n real de JSON en ambos followers. Los registros hist?ricos de readiness no representan carga de esta ventana.

Se abren y mantienen los cuatro forwards **en la VM** durante toda la ejecuci?n y verificaci?n. Se comprueba su proceso en cada petici?n HTTP y antes de degradar. El guard operativo original debe dar ACK con identidad/run/UID correctos y demostrar lost-supervisor al expirar el lease, con worker todav?a 1/1. Se refrescan de nuevo precondiciones y baseline tras esa prueba. El guard del incidente verifica otra vez precondiciones, followers y ACK antes del patch at?mico a cero.

El supervisor conserva 2 intentos/s, umbral >100 durante 120 s, evidencia antes/durante/despu?s, firing real antes de restaurar, UUID y tiempos durables del servidor, backlog cero y posterior inactive. Un fallo restaura capacidad y se registra sin volver a entrar al incidente. No se alteran im?genes, l?mites, reglas, otros namespaces o Terraform. La recuperaci?n del guard no depende de los forwards ni de SSH local.

## Suites previas: exclusivamente fixtures offline

| Suite | Pruebas | Resultado |
| --- | ---: | --- |
| test_met07_launch.py | 6 | OK; repetida tras endurecer autorizaci?n/SHA, sin sumarla dos veces |
| test_met07_operate.py | 14 | OK |
| test_met07_preparation.py | 28 | OK |
| test_met07_hardening.py | 11 | OK |
| test_met07_signals.py | 10 | OK |
| test_met07_os_watchdog.py | 4 | OK |

Resultados individuales en launcher-suite-results.json y launcher-final-suite.json. Los fixtures no contactan Azure/Kubernetes ni prueban un guard real. Pasaron sintaxis Node, cargo fmt y git diff --check. Gitleaks se ejecut? con descarga/checksum oficiales de 8.28.0 porque el binario temporal anterior ya no exist?a; ese intento anterior fall? antes del escaneo. Ver launcher-secret-scan.json. No se ejecut? Rust/PostgreSQL/container porque los cambios son herramientas Python/Node.

Se verificaron **81** hashes de evidencias anteriores sin diferencias. El primer reloj remoto observado fue 2026-11-12T20:20:46Z, a?n fuera de ventana. Ninguna evidencia anterior se reescribe. Las observaciones reales de la ejecuci?n se recuperar?n en execution/; dispatch-start.json identifica host/directorio y fuentes exactas; dispatch-result.json registra salida real sin repetir el incidente. Un resultado futuro no se presenta como ya obtenido.
