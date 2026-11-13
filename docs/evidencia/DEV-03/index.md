# DEV-03 · Integración continua y protección de la rama

[Issue #9](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/9). Criterios: todo PR ejecuta las validaciones, un check fallido impide el merge, los checks están declarados en la protección de la rama y los reportes quedan disponibles.

## Jobs de `acceptance.yml`

| Job (nombre del check) | Valida | Artefacto |
|---|---|---|
| `quality` | Auditor de gates (pruebas offline), formato, Clippy, pruebas, rustdoc y contrato OpenAPI | `rust-api-and-code-docs` |
| `postgres` | Aceptación contra PostgreSQL real y experimento de recuperación | `rust-postgres-evidence` |
| `secrets` | Secretos en todo el historial de Git | — |
| `container` | Build de la imagen, endurecimiento, vulnerabilidades y SBOM | `container-security-evidence` |

Las validaciones de infraestructura están en `terraform.yml` (DEV-08). Las dependencias se cachean con `rust-cache` y la caché de Buildx. Los jobs `secrets` y `container` se reproducen en local con los scripts de [`scripts/`](../../../scripts).

## Protección de `main`

**Estado vigente, 2026-11-13 03:21 UTC:** se activó `enforce_admins=true`
mediante el endpoint específico de GitHub, sin sustituir la configuración restante.
Se volvieron a consultar los cuatro checks obligatorios vinculados a Actions,
`strict=true`, una aprobación de CODEOWNERS, descarte de aprobaciones obsoletas
y resolución obligatoria de conversaciones: permanecen activos.
[Snapshot público reducido antes/después](proteccion-administradores.json).
El cambio de configuración ya está aplicado; este PR versiona la evidencia y
endurece el auditor, no aplica Terraform ni modifica Azure.

### Antecedente conservado

Estado leído de la API de GitHub el 2026-11-09 UTC: protección activa con los checks requeridos `quality`, `postgres`, `container` y `secrets`, vinculados a GitHub Actions (`app_id: 15368`), con rama actualizada obligatoria (`strict: true`) y `enforcement_level: non_admins`. [`CODEOWNERS`](../../../.github/CODEOWNERS) asigna la revisión de todos los cambios al dueño del repositorio. Se exige una aprobación, se descartan las aprobaciones obsoletas y las conversaciones deben estar resueltas.

Se agregó `secrets` a los checks requeridos mediante la API de protección, conservando los otros tres checks, la revisión humana y la excepción administrativa existente. No se amplió esa excepción ni se usó para integrar el control negativo.

No hay que marcar los checks de Terraform como requeridos: solo corren si el PR toca `infra/**`, y en los demás PR quedarían esperando para siempre.

## Control negativo real · PR #59

- [PR #59](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/59), head `8e71c833e1aa355464098613940e92da69e7118f`: prueba Rust deliberadamente fallida en una rama exclusiva que **no se integra**.
- [Run 42539969287](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42539969287): `quality` falló; `postgres`, `container` y `secrets` pasaron.
- Antes de cerrar el PR, GitHub reportó `state: OPEN`, `isDraft: false`, `mergeable: MERGEABLE` y `mergeStateStatus: BLOCKED`. No había conflictos ni era un borrador. El check fallido estaba declarado como obligatorio. La revisión humana también puede contribuir al bloqueo; no se intentó un merge ni se afirma haber aislado ese segundo control.
- [Snapshot de los campos verificados](control-negativo.json), capturado a las `2026-11-09T00:25:54Z`.
- Control positivo de CI: [run 42539239430](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42539239430), los cuatro checks de aplicación aprobados y artefactos disponibles.

El auditor es de solo lectura y falla si faltan checks, no están vinculados a Actions, desaparecen los controles de revisión, se desactiva la protección para administradores o el control negativo no tiene un check requerido fallido y estado bloqueado:

```bash
python3 -m unittest discover -s scripts/tests -v
python3 scripts/verify-ci-gates.py --negative-pr <PR-abierto-de-control> --output gates.json
```

Requiere Python 3 y `gh auth login` para la auditoría remota; Python no forma parte del runtime Rust. Las pruebas offline no requieren credenciales. El snapshot de #59 se conserva intacto: el auditor endurecido detecta su excepción administrativa histórica y no lo presenta como cumplimiento actual. No usar el PR #59 cerrado como entrada de una auditoría viva: crear otro control negativo, capturarlo y cerrarlo **sin merge**, si se necesita una demostración nueva.

## Integraciones históricas sin aprobación vigente · DEV-01 / DEV-03

Consulta de la API de PR y reviews realizada el 2026-11-13. Los tres PR fueron
creados por `CristiRR` e integrados por `marchelo23` bajo la excepción administrativa.
No se intentan aprobaciones retroactivas ni se reescribe su historial.

| PR | Merge UTC | Reviews observadas | Conclusión |
|---|---|---|---|
| [#93](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/93) | 2026-11-12 06:53:18 | CodeRabbit `COMMENTED`; Marcelo `COMMENTED` | Hubo comentarios humanos, pero no aprobación formal |
| [#95](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/95) | 2026-11-13 00:31:05 | Marcelo `DISMISSED`; CodeRabbit `COMMENTED` | No había aprobación vigente para la revisión final |
| [#96](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/96) | 2026-11-13 00:38:15 | Lista de reviews vacía | Sin revisión registrada |

La configuración anterior permitió estas integraciones; por tanto, ese historial
no acredita por sí solo PR aprobados conforme a DEV-01. El control preventivo nuevo
aplica también a administradores. Los próximos PR requieren aprobación de otro
CODEOWNER, checks correctos, rama actualizada y conversaciones resueltas.
Una revisión posterior puede documentar hallazgos, pero no cambia lo ocurrido
antes de los merges. No se afirma haber ejecutado una nueva prueba de merge fallido.

### Verificación de esta corrección

`npm ci`, `cargo fmt --all -- --check` y `git diff --check`: correctos.
`python3 -B -m unittest discover -s scripts/tests -p test_ci_gates.py -v`:
**10/10 pruebas aprobadas**, incluyendo rechazo de excepción administrativa,
conservación del snapshot histórico y comparación de los controles antes/después.
No se ejecutaron aplicación, PostgreSQL, contenedores ni Terraform: este cambio
solo afecta al auditor de protección y su evidencia. CI y revisión humana del PR
se verifican por separado; no se cuentan como aprobados por estas pruebas locales.

## Estado de aceptación

- [x] `secrets` agregado a los checks requeridos.
- [x] PR real con fallo requerido, sin conflictos y bloqueado, con evidencia capturada.
- [x] Ejecuciones reales y artefactos enlazados.
- [ ] Revisión humana independiente y demostración en defensa: no se suponen realizadas por publicar esta evidencia.

## Limitaciones

Los PR desde un fork no reciben OIDC ni escritura en el registro. Esto no afecta a estas validaciones, porque ninguna necesita credenciales.

La excepción `non_admins` descrita arriba es histórica: ahora la protección aplica
también a administradores. Quien administra el repositorio aún puede cambiar esa
configuración; no se confunde el control de merge con la imposibilidad de modificar
los ajustes. Activarlo no subsana retroactivamente las aprobaciones ausentes.
