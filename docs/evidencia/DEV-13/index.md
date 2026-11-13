# DEV-13 · Reconstrucción del ambiente con procedimiento documentado

[Issue #19](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/issues/19) · [PR #40](https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps/pull/40). Criterios:

- otra persona puede seguir el procedimiento;
- los prerrequisitos y costos están explícitos;
- el procedimiento es idempotente o indica cómo reintentar;
- existe evidencia de una reconstrucción completa.

El procedimiento está en [docs/infra/README.md · Reconstrucción desde cero](../../infra/README.md#reconstrucción-desde-cero--dev-13) y cubre:

- prerrequisitos, orden, variables, tiempos y costos de cada paso;
- verificación final y tabla de fallas conocidas;
- destrucción.

Scripts:

- [`bootstrap.sh`](../../../infra/bootstrap/bootstrap.sh): backend e identidades, idempotente;
- Terraform y cloud-init ([`cloud-init.yaml.tftpl`](../../../infra/terraform/cloud-init.yaml.tftpl)), que instala K3s con reintentos;
- [`verify.sh`](../../../infra/scripts/verify.sh): verificación final;
- [`vm.sh`](../../../infra/scripts/vm.sh) y [`kube-access.sh`](../../../infra/scripts/kube-access.sh): operación;
- [`deploy-access.sh`](../../../infra/bootstrap/deploy-access.sh): acceso de despliegue del bloque C (`id-eventos-deploy`), después del primer apply;
- [`teardown.sh`](../../../infra/bootstrap/teardown.sh): deshace el bootstrap y el acceso de despliegue sin dejar asignaciones huérfanas.

## Alcance

Este procedimiento reconstruye la **plataforma** del bloque B. La reconstrucción completa del sistema necesita además los pasos de C y D. Este issue no se cierra afirmando que se reconstruyó toda la plataforma hasta que esos bloques documenten su parte y se ensaye de punta a punta.

| Capa | Bloque | Estado |
|---|---|---|
| Backend del state, identidades y RBAC (`bootstrap.sh`) | B | Script idempotente y `teardown.sh`. Simulacro por otro integrante pendiente |
| Red, NSG, IP, VM y presupuesto (Terraform); acceso SSH del equipo en el PR de DEV-08 | B | Reconstruidos el 2026-11-08 (cambio de región y reemplazo de la VM) |
| K3s base: cloud-init, Traefik, `local-path` (DEV-09) | B instala; C opera | Reinstalado el 2026-11-08, `verify.sh` 8/8 |
| Imágenes, despliegue de la aplicación, configuración y Secrets, PostgreSQL y sus datos (DEV-02…05, 09…12) | C | Fuera de este procedimiento. Los datos de `local-path` se pierden al reemplazar la VM: C debe documentar respaldo y restauración |
| Observabilidad: Prometheus, Grafana, OpenTelemetry (MET-01…07) | D | Fuera de este procedimiento |

## Reconstrucciones ejecutadas · 2026-11-08

1. **Plataforma completa en otra región.** Al pasar de `northcentralus` a `mexicocentral`, el plan reemplazó los 9 recursos regionales: Resource Group, red, NSG, IP, NIC, VM, asociación y schedule. El apply destruyó y recreó la plataforma. Un `404` del proveedor al leer la VNet se resolvió con el procedimiento documentado (`terraform import`).
2. **VM con el cloud-init corregido.** `Plan: 2 to add, 0 to change, 1 to destroy`. Al reemplazar la VM, la descarga de K3s falló tres veces y el script la instaló al cuarto intento (`/var/log/k3s-bootstrap.log`):

   ```text
   == 2026-11-08T09:01:07+00:00 instalación de K3s v1.35.2+k3s1
   [ERROR]  Download failed
   Intento 1 fallido; nuevo intento en 30 s
   …
   k3s-eventos   Ready    control-plane   10s   v1.35.2+k3s1   10.40.1.4   Ubuntu 24.04.5 LTS
   == 2026-11-08T09:03:23+00:00 K3s listo
   ```

3. **Desasignar y encender.** La VM se desasignó y se volvió a encender. La IP y el DNS se conservaron, y K3s volvió a `Ready` sin intervención en unos 90 segundos.

   ```text
   09:11:43Z desasignar → VM deallocated
   09:12:17Z encender   → VM running
   09:13:37Z nodo Ready; CoreDNS, local-path, metrics-server y Traefik en Running; HTTP 404 de Traefik
   ```

Verificación final (`SSH_KEY=~/.ssh/<clave> bash infra/scripts/verify.sh`):

```text
Ambiente: eventos-b97e31.mexicocentral.cloudapp.azure.com (158.23.181.69)
  OK     vm-eventos-b97e31-k3s: VM running
  OK     huella SSH coincide con Azure (SHA256:L1RxG+BO2hEHHgsmPH1rLDhddP/s5O/8R4yhtOML6MU)
  OK     cloud-init: done
  OK     nodo K3s: Ready
  OK     Pods: 2 Completed 5 Running
  OK     HTTP público responde (404; sin Ingress, Traefik devuelve 404)
  OK     API de Kubernetes (6443) cerrada desde Internet
  OK     SSH solo acepta clave (sin contraseña)

Ambiente verificado.
```

Acceso de administración desde el equipo local: `kube-access.sh` obtuvo el kubeconfig, el túnel SSH abrió `127.0.0.1:6443` y `kubectl get nodes` respondió `k3s-eventos Ready`. El kubeconfig de prueba se borró después.

## Pendiente

- [ ] **Simulacro por otro integrante**, desde cero e incluido el bootstrap, en su propia suscripción Azure for Students. Así no se toca ni se destruye el ambiente compartido. Guía paso a paso con plantilla de resultados: [simulacro-reconstruccion.md](../../infra/simulacro-reconstruccion.md). Las reconstrucciones de arriba conservaron el backend y las identidades.
- [ ] **Ensayo de punta a punta**, con alcance actualizado al 2026-11-12. El bloque C ya está integrado (DEV-02…12 cerrados) y la observabilidad corre en `eventos-development`. El ensayo debe cubrir:
  1. bootstrap, Terraform y K3s (`verify.sh`);
  2. `deploy-access.sh`;
  3. el despliegue de la aplicación según `kubernetes/README.md`;
  4. Prometheus, Grafana y Jaeger;
  5. un smoke de la API.

  Marcelo pidió que lo ejecute otro integrante al reabrir el issue; el equipo decide si se mantiene ese requisito.

## Limitaciones

Reconstruir la VM borra los volúmenes `local-path` (datos de PostgreSQL y de la observabilidad). Las pruebas de persistencia deben hacerse antes de reconstruir.
