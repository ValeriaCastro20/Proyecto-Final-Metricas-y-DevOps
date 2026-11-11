# Acceso de CristiRR a revisión y despliegues

Refs #84. Configuración comprobada el 2026-11-11 mediante la API de GitHub.

- `CristiRR` (ID GitHub 174069999) ya tiene **Write**; no se otorga Admin.
  Puede lanzar workflows y emitir revisiones de PR ajenos.
- Se añade a `CODEOWNERS` junto a los tres integrantes existentes. La revisión
  de codeowner de CristiRR contará tras integrar este cambio en la rama base.
  GitHub no permite aprobar el propio PR.
- Se añadió como revisor de los environments `production` y `azure-infra`,
  conservando los tres revisores anteriores y las políticas de rama.
- `production`: solo main, `prevent_self_review=false` y bypass de administradores
  deshabilitado, sin cambios respecto de la configuración previa.
- `azure-infra`: solo main, `prevent_self_review=true` y bypass de administradores
  habilitado, sin cambios respecto de la configuración previa. Esta operación no
  usa ese bypass ni ejecuta Terraform.
- La protección de main conserva `quality`, `postgres`, `container`, `secrets`,
  una aprobación de codeowner, descarte de revisiones obsoletas y resolución de
  conversaciones. No se reducen los controles para facilitar una entrega.

Los permisos de repositorio y environments están configurados en GitHub, no los
aplica CODEOWNERS. Este archivo registra su verificación; no contiene secretos.
La edición de CODEOWNERS requiere PR revisado y CI. Write no permite modificar
roles, secretos o protecciones como un administrador.
