# DEV-14 · Control del consumo de Azure (límite US$100)

[Issue #20](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/20) · [PR #40](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/40) · [PR #57](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/57). Criterios:

- estimación alineada con Terraform;
- alertas de presupuesto configuradas;
- procedimiento de detención y eliminación probado;
- cargos observados documentados, sin superar US$100.

Estimación, medidas y registro de cargos: [docs/infra/costos.md](../../infra/costos.md).

## Resultado obtenido · 2026-11-08

**Estimación** (alineada con los recursos de Terraform):

- ≈ US$1.30/día con la VM encendida 12 h;
- ≈ US$39/mes;
- ≈ US$27 en 3 semanas;
- peor caso, 24 h durante 3 semanas: ≈ US$48.

**Presupuesto** (`terraform state show 'azurerm_consumption_budget_subscription.project[0]'`):

```text
name       = "budget-eventos-b97e31"
amount     = 100
time_grain = "Monthly"
start_date = "2026-11-01T00:00:00Z"
threshold 50  Actual
threshold 80  Actual
threshold 100 Forecasted
```

Los correos de alerta son los de `budget_contact_emails`.

**Detención probada.** `bash infra/scripts/vm.sh stop` desasignó la VM (`VM deallocated`) en 34 s y `start` la encendió en 44 s. K3s volvió a `Ready` sin intervención: ver DEV-13.

**Apagado diario.** El apagado nativo de Azure (`Microsoft.DevTestLab/schedules`) no está disponible en `mexicocentral`. Se probaron las dos variantes y Azure las rechazó:

```text
location = mexicocentral → LocationNotAvailableForResourceType
location = westus3       → InvalidScheduleLocation: The schedule should be created in location mexicocentral.
```

Se reemplazó por [`vm-power.yml`](../../../.github/workflows/vm-power.yml), que desasigna la VM a las 23:00 y permite `start`, `stop` y `status` manuales desde GitHub. Usa `id-eventos-ops`, con un rol personalizado limitado a cuatro acciones (`virtualMachines/read`, `instanceView/read`, `start/action`, `deallocate/action`). Los nombres de las acciones se validaron contra `az provider operation show`. El bootstrap del 2026-11-08 creó la identidad y el rol (`az role definition list --name eventos-b97e31-vm-operator`):

```text
nombre:   eventos-b97e31-vm-operator
acciones: Microsoft.Compute/virtualMachines/read, Microsoft.Compute/virtualMachines/instanceView/read,
          Microsoft.Compute/virtualMachines/start/action, Microsoft.Compute/virtualMachines/deallocate/action
alcance:  /subscriptions/<sub>   (asignado a id-eventos-ops)
```

Primera ejecución programada verificada en GitHub Actions ([run `42628212259`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42628212259), 2026-11-09, evento `schedule` en `main`, 49 s): autenticó por OIDC contra `id-eventos-ops` en el environment `azure-ops` (`subject: repo:marchelo23@149895391/Proyecto-Final-Metricas-y-DevOps@1427515419:environment:azure-ops`), ejecutó `az vm deallocate` y confirmó el estado final:

```text
vm-eventos-b97e31-k3s: VM deallocated
```

**Eliminación probada.** El cambio de región destruyó por Terraform todos los recursos regionales anteriores, sin recursos huérfanos: el grupo antiguo se eliminó completo.

**Cargos reales al 2026-11-08** (API de Cost Management, `ActualCost` agrupado por Resource Group; comando en `costos.md`):

```text
Desde 2026-10-20 (proyecto)              Mes de noviembre
rg-ticket-e3065e-shared      1.3613      rg-ticket-e3065e-shared   1.2703
devops-k3s-rg                0.6250      devops-k3s-rg             0.6250
rg-eventos-b97e31            0.1711      rg-eventos-b97e31         0.1711
rg-ticket-e3065e-production  0.0254      rg-eventos-tfstate        0.0002
rg-ticket-e3065e-development 0.0251
rg-ticket-e3065e             0.0043
rg-ticket-bootstrap          0.0002
rg-eventos-tfstate           0.0002
TOTAL                        2.2126 USD  TOTAL                     2.0666 USD
```

La plataforma del proyecto (`rg-eventos-*`) suma US$0.17. El resto de la suscripción corresponde a:

- el Laboratorio 4 (`rg-ticket-*`), que aún existe y es el mayor gasto;
- la práctica de la clase de integración (`devops-k3s-rg`), ya eliminada.

Saldo hasta el límite: US$100 − US$2.21 = **US$97.79**.

**Crédito de Azure for Students** (portal, *Education → Información general*, 2026-11-08):

```text
Créditos disponibles             98 US$ de 100 US$
Días hasta que expire el crédito 344 (expira el 18/10/2027)
Costos de noviembre              2,12 US$
```

El crédito se activó el 2026-10-18, dos días antes del inicio del proyecto. Lo consumido según el portal (≈ US$2, redondeado) coincide con el acumulado de la API. Los costos de noviembre del portal (US$2.12) son algo mayores que los de la consulta (US$2.07) porque incluyen cargos más recientes.

## Verificación y seguimiento continuo

- [x] Ejecutar el bootstrap actualizado, que crea `id-eventos-ops` y su rol (2026-11-08).
- [x] Configurar el environment `azure-ops` y la variable `OPS_CLIENT_ID` (2026-11-08).
- [x] Enlazar la primera ejecución programada de `vm-power.yml` (`VM deallocated`): [run `42628212259`](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/runs/42628212259) (2026-11-09).
- [x] Primer registro de cargos reales (2026-11-08).
- [x] Crédito restante de Azure for Students, leído en el portal: US$98 de US$100 (2026-11-08).
- [ ] Seguimiento periódico: registrar cada semana, y antes de cada entrega y de la defensa, el acumulado del mes, el acumulado del proyecto, el crédito restante y el saldo hasta US$100 (tabla de `costos.md`). El presupuesto mensual no cubre el agregado de varios meses.
- [ ] Destruir los recursos del Laboratorio 4 después de su revisión docente (≈ US$1/día).

## Limitaciones

- Las alertas de presupuesto notifican, pero no detienen recursos.
- Con la VM desasignada siguen cobrándose el disco y la IP estática (≈ US$0.28/día).
