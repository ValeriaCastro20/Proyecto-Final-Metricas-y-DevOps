# Simulacro de reconstrucción desde cero · DEV-13

**Objetivo:** demostrar que **otro integrante**, sin ayuda del autor, reconstruye la infraestructura desde una suscripción autorizada siguiendo solo la documentación, la verifica y la elimina.

**Dónde:** se hace en la suscripción Azure for Students **del integrante** que ejecuta el simulacro, con un sufijo nuevo. No toca el ambiente compartido (`rg-eventos-b97e31`) ni su state, y no hay que destruir nada del proyecto para obtener la evidencia.

**Alcance:** cubre el bootstrap, Terraform, K3s (cloud-init) y la verificación final. No incluye las imágenes, el despliegue de la aplicación, los datos ni la observabilidad, que pertenecen a los bloques C y D (ver [DEV-13](../evidencia/DEV-13/index.md#alcance)).

**Duración y costo:** unos 45 minutos. La VM `Standard_B2s_v2` cuesta ≈ US$0.08/h; con disco e IP, menos de US$0.50 si se elimina el mismo día.

## Prerrequisitos

- Suscripción Azure for Students **propia** y activa, con sesión de su dueño (Owner). No debe ser la del ambiente compartido ni tener ya un bootstrap de este proyecto:

  ```powershell
  az login
  az account list --query "[].{id:id,name:name}" -o table
  az account set --subscription <ID de la suscripción propia>
  az account show --query "{id:id,name:name}" -o table
  az group exists --name rg-eventos-tfstate      # debe ser false; si es true, DETENERSE
  ```

  `bootstrap.sh` reutiliza `rg-eventos-tfstate` y las identidades, porque sus nombres son fijos. Si ese grupo ya existe, el simulacro se mezclaría con otro bootstrap. `teardown.sh` se niega a borrar un grupo que contiene el state de otro bootstrap, pero el simulacro no debe llegar a ese punto.
- Herramientas en Windows:
  - Git for Windows (Git Bash, `openssl`);
  - Azure CLI;
  - Terraform ≥ 1.12 (validado con 1.16.6);
  - GitHub CLI con sesión (`gh auth login`);
  - OpenSSH.
- Par de claves SSH propio en `~/.ssh/id_ed25519`. Si no existe: `ssh-keygen -t ed25519`. Si se usa otra ruta, definir `SSH_KEY` en el paso 5.
- IPv4 pública de salida: `curl.exe -4 https://api.ipify.org`.

Registrar la hora de inicio y fin de cada paso en la tabla del final.

## Pasos

Los comandos se ejecutan en **PowerShell**. Los scripts de Bash se invocan con el `bash.exe` de Git, que evita problemas de la terminal de Git Bash.

### 1. Clonar el repositorio en una carpeta nueva

```powershell
git clone https://github.com/marchelo23/Proyecto-Final-Metricas-y-DevOps.git simulacro-eventos
cd simulacro-eventos
```

El clon no debe traer `infra/bootstrap/bootstrap.env` ni `infra/terraform/terraform.tfvars` de otra persona; ambos están en `.gitignore`.

### 2. Bootstrap

Crea en la suscripción propia el Storage del state, las tres identidades y sus permisos, con un sufijo nuevo.

```powershell
& "C:\Program Files\Git\bin\bash.exe" infra/bootstrap/bootstrap.sh
Get-Content infra/bootstrap/bootstrap.env
```

Anotar `NAME_SUFFIX` y `TFSTATE_STORAGE_ACCOUNT`. Las identidades quedan federadas con el repositorio, pero en GitHub no se configura nada: el teardown del paso 6 las elimina.

### 3. Variables de Terraform

```powershell
cd infra/terraform
Copy-Item terraform.tfvars.example terraform.tfvars
notepad terraform.tfvars
```

Completar:

- `subscription_id` (la propia);
- `name_suffix` (el `NAME_SUFFIX` del paso 2);
- `admin_ssh_public_key` (contenido de `~/.ssh/id_ed25519.pub`);
- `admin_cidrs` (`["<IP>/32"]`);
- `budget_contact_emails` (correo propio).

### 4. Aplicar

`backend.hcl` apunta al Storage del ambiente compartido. Para el simulacro se sobrescribe solo el nombre del Storage con el del paso 2; el archivo **no se modifica**.

```powershell
$env:ARM_USE_CLI = "true"
terraform init -backend-config=backend.hcl -backend-config="storage_account_name=<TFSTATE_STORAGE_ACCOUNT>"
terraform plan -out=tfplan
terraform apply tfplan
```

El plan debe crear todo y no cambiar ni destruir nada (`… to add, 0 to change, 0 to destroy`):

- Resource Group, VNet, subred, NSG y su asociación;
- IP pública, NIC y VM;
- presupuesto;
- la extensión `team-ssh-keys`, si `infra/terraform/acceso.tf` ya está en `main`.

Si Azure rechaza la VM por restricción de zona o capacidad (`SkuNotAvailable`), no cambiar región ni tamaño al azar. Revisar las restricciones de la propia suscripción:

```powershell
az vm list-skus --location mexicocentral --size Standard_B2s_v2 --query "[].restrictions" -o json
```

Si solo la zona 1 está restringida, repetir el plan con `-var vm_zone=3` y registrar la decisión.

Para el ensayo de punta a punta, con el despliegue del bloque C, ejecutar además `& "C:\Program Files\Git\bin\bash.exe" infra/bootstrap/deploy-access.sh` después del apply. Para el simulacro solo de B no hace falta.

### 5. Verificar

Unos 5 minutos después del apply, cuando cloud-init termina de instalar K3s:

```powershell
cd ../..
& "C:\Program Files\Git\bin\bash.exe" infra/scripts/verify.sh
```

Resultado esperado: 8 comprobaciones `OK` y `Ambiente verificado.`. El script compara la huella SSH del servidor con la que reporta Azure antes de conectarse. Con una clave que no sea la predeterminada: `$env:SSH_KEY = "/c/Users/<usuario>/.ssh/<clave>"` antes de ejecutarlo.

### 6. Eliminar

```powershell
cd infra/terraform
terraform plan -destroy      # revisar: solo recursos con el sufijo del simulacro
terraform destroy
az group exists --name rg-eventos-<NAME_SUFFIX>        # false
cd ../..
& "C:\Program Files\Git\bin\bash.exe" infra/bootstrap/teardown.sh
az group exists --name rg-eventos-tfstate              # false
```

`teardown.sh` pide escribir el sufijo para confirmar. Elimina:

- las asignaciones de rol de las identidades en la suscripción;
- el rol personalizado;
- el Resource Group del state.

Si se borrara solo el Resource Group, quedarían asignaciones huérfanas en la suscripción.

## Registro de resultados

Copiar esta tabla en `docs/evidencia/DEV-13/` (o en un comentario del issue #19), sin IDs de suscripción ni IPs. `verify.sh` imprime la IP pública en la primera línea: reemplazarla antes de pegar.

| Paso | Inicio | Fin | Resultado | Observaciones |
|---|---|---|---|---|
| 1. Clonar | | | | |
| 2. Bootstrap | | | | sufijo: |
| 3. Variables | | | | |
| 4. Plan y apply | | | `Plan: … to add` / `Apply complete! …` | zona usada: |
| 5. `verify.sh` | | | `Ambiente verificado.` (pegar la salida con la IP de la primera línea reemplazada por `<IP>`) | |
| 6. Destroy y teardown | | | `false` / `false` | |

Integrante que lo ejecutó, fecha y versión del repositorio (`git rev-parse --short HEAD`). Anotar también dónde la documentación no fue suficiente: es el objetivo del simulacro.
