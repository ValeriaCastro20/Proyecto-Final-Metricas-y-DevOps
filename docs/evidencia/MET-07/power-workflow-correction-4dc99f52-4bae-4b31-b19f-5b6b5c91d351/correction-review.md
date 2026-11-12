# MET-07 ? Corrección de clasificación y nuevo preflight explícito

Se conserva sin cambios el aborto de las 21:00:04 UTC y todos sus archivos. El nuevo lanzamiento responde a una **nueva instrucción explícita del usuario**, no a un reintento automático. La confirmación administrativa sigue siendo información transmitida por el usuario, sin atribución a consultas ARM propias.

La revisión de actividad consulta exclusivamente https://api.github.com/repos/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/workflows/411281561/runs?per_page=100&page=N. Se eliminan las consultas generales de ejecuciones del repositorio y la consulta de contents del clasificador. La hora nominal de apagado ya revisada anteriormente no se presenta como fuente consultada de nuevo: los datos de esta revisión son solo las ejecuciones del workflow indicado.

El código exige HTTP 200 sin error de conexión, total_count entero no negativo, array de runs válidos del workflow exacto, IDs únicos, recuento estable entre páginas y cobertura completa del total declarado. Las páginas cortas prematuras, errores en páginas posteriores, duplicados y el límite de 10 páginas sin completar bloquean. Cualquier run no completed de este workflow cuenta como activo y bloquea. Los runs de CI Rust ajenos no se consultan ni se agregan a actividad de energía.

## Validación offline por suite

| Suite | Pruebas | Resultado final |
| --- | ---: | --- |
| test_met07_launch.py | 14 | OK |
| test_met07_operate.py | 14 | OK |
| test_met07_preparation.py | 28 | OK |
| test_met07_hardening.py | 11 | OK |
| test_met07_signals.py | 10 | OK |
| test_met07_os_watchdog.py | 4 | OK |

Las regresiones demuestran cinco runs CI Rust queued que no bloquean, runs del workflow 411281561 queued/pending/in_progress/waiting/requested que sí bloquean, un run pendiente en la segunda página, errores HTTP/conexión, paginación incompleta/cambiante/duplicada y datos de otro workflow que impiden aprobar. La primera pasada de launch falló por un fixture que confundía page=1 con per_page=100; se corrigió a &page=1 y se repitió solo esa suite. Se conservan ambos resultados en suite-results.json y launcher-final-suite.json, sin sumar repeticiones. Son fixtures offline, no evidencia de guard o incidente real.

Pasaron Gitleaks 8.28.0 con checksum oficial, sintaxis Node, cargo fmt --all -- --check y git diff --check. Se verificaron 102 hashes previos, incluido el aborto original. No se crearon commits, push ni acciones sobre #94.

El nuevo preflight exige reloj del servidor dentro de 21:00–23:00 UTC y más de 20 minutos restantes, reabre los cuatro forwards en la VM y conserva todos los controles de UID/réplica/generación/propietarios/HPA/permisos, Scheduled Events, timers, endpoints, baseline, followers y prueba real del guard antes de degradar. Los forwards permanecen abiertos hasta terminar la verificación o recuperación. Solo se permite una entrada al incidente y no hay reintento automático. Los resultados reales se conservarán aparte en execution/; este informe no anticipa su resultado.
