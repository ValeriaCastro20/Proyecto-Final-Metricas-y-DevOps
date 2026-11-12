# Validación de entrega MET-05

Fecha: 2026-11-12 UTC. Esta fase solo prepara la entrega Git; no ejecuta pruebas de incidente ni modifica recursos desplegados.

- `npm ci`, Node v22.15.0 / npm 11.1.0: correcto, una dependencia instalada, cero vulnerabilidades reportadas por npm. `git config --get core.hooksPath` devuelve `.husky/_`.
- `cargo fmt --all -- --check`: código 0 con el toolchain fijado. El commit se crea mediante `git commit`, con el hook Husky activo; no se usa `HUSKY=0` ni `--no-verify`.
- `wsl --exec python3 -B scripts/test-observability.py`: cuatro contratos offline correctos.
- `wsl --exec python3 -B -m unittest discover -s scripts/tests -v`: 23 tests correctos, incluidos contratos de manifiestos y dobles locales de entrega; no se conectan al development real.
- `node --check` sobre el generador de ConfigMap y los scripts JS de evidencia: correcto.
- ConfigMap y JSON importable: contenido del dashboard idéntico; ocho paneles, UID de datasource estable y provider con saltos de línea reales. Regeneración determinista comprobada.
- Coherencia de evidencias: generador con `passed=true`, diez procesadas, cero pendientes; 16 consultas exitosas de paneles; fallo inicial de correlación conservado en 09 y corrección de solo lectura satisfactoria en 10, con diez UUID correlacionados.
- Revisión de secretos: búsqueda exacta de las dos credenciales suministradas en memoria, sin imprimirlas, en los archivos de la entrega y bloques base64 decodificados. No hubo coincidencias ni encabezados de clave privada. Gitleaks 8.28.0 con redacción y profundidad de decodificación 3: cero hallazgos en los tres directorios revisados.
- Kubeconform 0.8.0, esquemas estrictos Kubernetes 1.35.0: 17 recursos válidos en cuatro archivos, cero inválidos, errores u omisiones. Descargas temporales verificadas por checksum. Script y salida real: [12-validate-delivery.sh](12-validate-delivery.sh), [12-validate-delivery.txt](12-validate-delivery.txt).
- `git diff --cached --check -- . ":(exclude)docs/evidencia/MET-05/*.txt"`: correcto para los archivos editables. El check general señaló espacios finales en dos capturas de terminal (04 y 12); se conservaron literalmente como evidencia, incluido el timeout original.

El primer intento local de kubeconform recibió un CR al final de la ruta enviada desde PowerShell y falló antes de validar recursos. Se corrigió ejecutando un script LF desde archivo; la salida final se conserva en 12. Los mensajes `NativeCommandError` de esa salida son el envoltorio PowerShell de stderr informativo de Gitleaks; el proceso terminó con `EXIT_CODE=0` y kubeconform validó los 17 recursos.

Docker local devolvió HTTP 500 en `docker version`. No se afirma escaneo local del historial mediante el contenedor de `scripts/scan-secrets.sh`, ni verificación local de imagen/SBOM. Gitleaks nativo revisó los archivos de entrega; el job `secrets` de CI debe revisar el historial del commit publicado. Los jobs `quality`, `postgres`, `container` y `manifests` se reportarán por su estado real en el PR; formato y tests offline no los sustituyen. No se ejecutaron localmente clippy, toda la suite Rust ni aceptación con BD para este cambio de dashboard/documentación. Terraform no aplica: no se cambió infraestructura.

El timeout de readiness de 04 y el desfase de reloj de 09 se conservan y explican en el [README](README.md). El resultado final se sustenta en 04b, las diez lecturas y los ocho paneles de 09, las diez trazas verificadas de 10 y el worker activo de 11. No se repitió la emisión funcional para esta entrega. El issue #25 permanece abierto y requiere revisión humana y defensa; el PR utiliza `Refs #25`.