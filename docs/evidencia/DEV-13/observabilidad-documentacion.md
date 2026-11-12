# DEV-13: guía de observabilidad incorporada — Refs #19

Rama docs/DEV-13-observabilidad-despliegue desde origin/main 7607d54771cbadba29facd9d77aef5500ca2c2b9, en worktree separado. Parche observabilidad-despliegue.patch, origen declarado a284f7a. SHA-256 original: 5993f96a4b2a220be214fdac7bd6ea878f9f8b55839986dd70474dcca140e9ca. INSTRUCCIONES.md: eb2051c37ac5eb9764df06428e06bce88c6604603127de348d748d8eeeba4409. La copia temporal LF pasó git apply --check y se aplicó; no se modificaron los archivos de entrada.

Se documentan orden Jaeger/Prometheus/dashboard/Grafana, contexto y namespace, configuración OTLP opcional, comprobaciones, acceso, persistencia y recuperación de configuración. Se contrastaron estáticamente recursos, selectores, puertos, UIDs, dos reglas, scrape 5 s y retención 2 d con los YAML de main. No se ejecutaron apply, dry-run Kubernetes, restart, túneles reales ni lectura de Secrets.

| Verificación | Resultado |
| --- | --- |
| npm ci y core.hooksPath=.husky/_ | OK |
| cargo fmt --all -- --check y Husky real | OK |
| git diff --check y enlaces locales | OK |
| NetworkPolicy: contratos offline scripts/test-observability.py | 4/4 |
| Verificación MET-05 con respuestas/procesos simulados | 29/30 inicial; la prueba de limpieza pasó al seleccionar Git Bash en lugar del shim WSL de Windows. Son 30 pruebas verificadas, no 31. |
| Sintaxis de la guía | 4 bloques PowerShell y 3 Bash; analizados, no ejecutados |

Los fallos simulados, snapshots históricos y tests de transporte no son una nueva ejecución Azure. No se reconstruyó ni inspeccionó el entorno en vivo. La guía cubre una parte documental de DEV-13; no se cierra #19 ni se afirma reconstrucción integrada completa. No se mezcla el requisito #27 en este PR. CI, CodeRabbit y revisión humana seguirán su proceso de revisión, sin declararlos aprobados localmente.

Gitleaks 8.28.0 nativo, descarga con checksum oficial: historial compartido y directorios documentales pertinentes sin hallazgos, con decode depth 3. Sin nuevas excepciones de escaneo.
