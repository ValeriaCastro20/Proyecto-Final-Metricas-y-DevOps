# Revisión y despliegue por el equipo

[Issue #72](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/72).

Configuración verificada con la API de GitHub el 2026-11-10:

- `Sushiland123` y `ValeriaCastro20` tienen rol **Write**, sin acceso Admin. Pueden ejecutar workflows manuales y emitir aprobaciones de PR ajenos.
- `azure-infra` y `production` tienen como revisores a `marchelo23`, `Sushiland123` y `ValeriaCastro20`. Basta la aprobación de uno de los revisores habilitados.
- Ambos environments conservan una única política de despliegue: rama `main`.
- Se conservó `prevent_self_review: true` en `azure-infra` y `false` en `production`. Se conservó el bypass administrativo existente de `azure-infra`; `production` sigue sin bypass.
- `main` sigue exigiendo una aprobación, revisión de CODEOWNERS, descarte de aprobaciones obsoletas y checks `quality`, `postgres`, `container` y `secrets`, con rama actualizada.

El cambio de `.github/CODEOWNERS` agrega a ambos colaboradores junto a Marcelo. Solo entra en vigor al integrar este PR: la revisión de este mismo PR todavía depende del CODEOWNERS de la rama base. Ningún autor puede aprobar su propio PR.

La configuración de environments se aplicó directamente en GitHub. No se inició ni aprobó ningún despliegue, y no se atribuye una nueva ejecución a Azure. Tener permisos no sustituye confirmar identidad, variables, CI y coordinación antes de desplegar.
