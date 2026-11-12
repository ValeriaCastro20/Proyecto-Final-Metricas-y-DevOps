# Guías de API y flujo DevOps contrastadas con main

Refs #91. Base: `eb8fa8f`; no se incorporan cambios de otros PR abiertos.

## Fuentes y cambios

- API: `src/api.rs`, `src/scenario/{mod,http,store}.rs`, `src/telemetry.rs` y
  OpenAPI generado por `cargo run --locked -- openapi`. ESC3 se documenta primero;
  se conserva la guía del contrato genérico sin atribuirle inbox ni 202.
- Desarrollo/operación/README: procesos separados, pools, dos tipos de respuesta
  422, contadores, configuración del worker/OTLP y pruebas ignored explícitas.
- DevOps: los siete workflows, acciones de entrega y scripts de rollout/smoke/
  rollback. Se explican publicación paralela a CI, entrega manual por SHA/digest,
  firmas, gate production, alcance de los Deployments y límites de recuperación.
- GitHub: protección de main y políticas de los cuatro environments consultadas
  por API. Son configuración externa comprobada, no garantía derivada del YAML.
- Kubernetes: se retira la afirmación obsoleta de que el workflow de promoción
  aún debe implementarse; se enlaza procedimiento/evidencia existentes.

## Validación local

- OpenAPI generado sin DB: 21 referencias método/ruta contrastadas; rutas
  operativas sin anotación contrastadas con el router, respuestas 200/202/422 y
  schemas ESC3 comprobados. No se mantiene un contrato JSON paralelo en Git.
- Enlaces locales, JSON de ejemplos y sintaxis de bloques Bash comprobados sin
  ejecutar los comandos de despliegue. Los siete workflows están mapeados.
- Diagrama de flujo renderizado con Mermaid CLI/Chromium; SVG local en
  `/tmp/opencode/api-devops-flow-1.svg`, no adjunto remoto ni evidencia de Azure.
- `cargo fmt --all -- --check`, Clippy estricto, all-targets y rustdoc: aprobados.
  Los tests PostgreSQL/metrics ignored no se ejecutaron contra DB en este cambio
  documental; sí se compilaron. No se afirma aceptación nueva de DB o carga.
- 23 pruebas Python de scripts y cuatro contratos de observabilidad aprobados;
  `git diff --check` sin errores.

No cambia Rust, HTML servido, OpenAPI generado, manifiestos, workflows, permisos,
secretos ni infraestructura. No se lanza entrega, plan/apply o experimento. La
entrega histórica `43114911744` se referencia como tal, no como estado actual.
CI del PR, CodeRabbit y revisión humana deben comprobarse por separado.
