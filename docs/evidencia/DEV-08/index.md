# DEV-08 · Validación de Terraform en GitHub Actions

[Issue #14](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/14) · [PR #40](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/40) · [PR #55](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/55) · [PR #58](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/58). Criterios:

- todo PR de infraestructura ejecuta validación y plan;
- el plan es visible antes del merge;
- el apply requiere aprobación y no corre en PRs;
- no hay credenciales de Azure en el repositorio.

## Workflows

| Workflow | Disparador | Qué hace |
|---|---|---|
| [`terraform.yml`](../../../.github/workflows/terraform.yml) | PR que toca `infra/**` | `fmt -check`, `init -backend=false`, `validate`, `tflint` y speculative plan con `id-eventos-plan`. El plan se publica en el resumen del job y como artefacto `terraform-plan-pr-<n>` |
| `terraform.yml` | push a `main` o manual desde `main` | `plan -out=tfplan` y `apply tfplan` en el environment `azure-infra`, limitado a `main`, que exige la aprobación de un revisor antes de entregar el token de `id-eventos-apply` |
| [`terraform-drift.yml`](../../../.github/workflows/terraform-drift.yml) | diario, 08:00 | `plan -detailed-exitcode` de solo lectura; falla si Azure difiere del código |

Las identidades usan OIDC, así que no hay credenciales de Azure en el repositorio. Las variables guardan IDs de cliente, tenant y suscripción. La IP de administración y los correos van como *secrets* y como variables `sensitive` de Terraform, solo por privacidad: el repositorio es público. El job de apply exige `github.event_name != 'pull_request'` y `github.ref == 'refs/heads/main'`, y el environment `azure-infra` solo admite `main`. Ningún PR ni otra rama puede aplicar, tampoco con `workflow_dispatch`. Los checkouts usan `persist-credentials: false`: Terraform ejecuta binarios de providers y ningún paso necesita el token de Git.

## Resultado obtenido · 2026-11-08 / 2026-11-09

- **Local, equivalente al job `validate`:** `terraform fmt -check -recursive` sin diferencias y `terraform validate` exitoso con AzureRM 4.40.0. Los YAML de los workflows se analizaron sin errores. `tflint` no se ejecutó en local.
- **PR desde un fork (control negativo de OIDC):** en el PR #40 ([run `42446613442`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42446613442) y [run `42445426635`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42445426635)), `fmt y validate` se ejecuta tras la aprobación de un mantenedor y el job `plan` se omite de forma segura porque los forks no reciben token OIDC ni variables del repositorio.
- **En `main`, antes de configurar las variables (control negativo de `apply`):** [run `42499426565`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42499426565).
  - `fmt y validate`: éxito en todos sus pasos (`terraform fmt`, `init -backend=false`, `validate`, `tflint`).
  - `apply controlado`: se omitió (`skipped`) porque el repositorio aún no tenía `APPLY_CLIENT_ID`.
- **Speculative plan autenticado en PR del mismo repositorio:** [run `42539239440`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42539239440) ([PR #58](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/58), rama `docs/DEV-08-revocacion-kubeconfig`).
  - Autenticó por OIDC con `id-eventos-plan` (`pull_request`), ejecutó `terraform plan -input=false -out=tfplan` (`Plan: 1 to add, 0 to change, 0 to destroy` para `azurerm_virtual_machine_extension.team_ssh_keys`), publicó el detalle en el resumen del job y adjuntó el artefacto `terraform-plan-pr-58`.
- **Apply controlado desde `main` con aprobación en `azure-infra`:**
  - [Run `42538564827`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42538564827) (merge del PR #55 en `main`): permaneció en espera de revisión del environment `azure-infra` hasta su aprobación explícita; tras aprobarse, autenticó por OIDC con `id-eventos-apply` y aplicó el plan guardado (`Apply complete! Resources: 1 added, 0 changed, 0 destroyed`, creando `azurerm_virtual_machine_extension.team_ssh_keys` en 24 s).
  - [Run `42539253572`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42539253572) (merge del PR #58 en `main`): aprobado en `azure-infra` y completado con `Apply complete! Resources: 0 added, 0 changed, 0 destroyed`.
- **Detección de drift (`terraform-drift.yml`):**
  - **Con diferencia pendiente (control negativo):** [run `42718771263`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42718771263) (`schedule`), ejecutado antes de aprobar el apply de `team-ssh-keys`; devolvió código `2` en `terraform plan -detailed-exitcode` (`Plan: 1 to add, 0 to change, 0 to destroy`) y falló el workflow con el error esperado (`Azure difiere del código. Revisar el plan y reconciliar con un PR o un apply aprobado`).
  - **Estado reconciliado (`No changes`):** [run `42755140733`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42755140733), ejecutado tras el apply en `main`; finalizó en verde (`No changes. Your infrastructure matches the configuration.` · `### Sin drift`).

Verificaciones completadas:

- [x] Ejecución de `fmt`/`validate`/`tflint` en GitHub: [run `42499426565`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42499426565) y siguientes.
- [x] Enlace a un speculative plan autenticado de un PR del mismo repositorio, con su artefacto `terraform-plan-pr-58`: [run `42539239440`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42539239440).
- [x] Enlace a un apply en `main` con espera y aprobación de `azure-infra`: [run `42538564827`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42538564827) (`1 added`) y [run `42539253572`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42539253572) (`0 added`).
- [x] Enlace a ejecuciones de `terraform-drift.yml` tanto detectando diferencia ([run `42718771263`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42718771263)) como reconciliada con `No changes` ([run `42755140733`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42755140733)).

## Limitaciones

- Los PR abiertos desde un fork externo no reciben token OIDC por seguridad de GitHub Actions; el speculative plan autenticado corre en PRs desde ramas del propio repositorio.
- Los cron de GitHub pueden retrasarse algunos minutos.

## Corrección de la guía de revocación del PR #55

La guía de [acceso SSH](../../../infra/ssh/README.md#quitar-el-acceso) distingue ahora entre quitar una clave SSH, cerrar sesiones y revocar un kubeconfig de administrador copiado. Rotar solo el certificado `admin` no invalida el anterior; la documentación oficial de [K3s](https://docs.k3s.io/cli/certificate#cautions-against-ca-reuse) exige reemplazar la CA de confianza para invalidarlo.

La corrección es documental: no se ejecutó rotación de certificados, no se modificaron recursos de Azure y no se afirma que se haya probado una revocación real. La guía exige mantenimiento planificado, respaldo, recuperación y verificación de que las credenciales anteriores ya no autentican.
