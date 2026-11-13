#!/usr/bin/env bash
# Deshace el bootstrap (DEV-13): asignaciones de rol de las identidades en la
# suscripción, el rol personalizado y el Resource Group del state (Storage,
# identidades y credenciales federadas). Borrar solo el Resource Group dejaría
# asignaciones huérfanas y el rol personalizado en la suscripción.
#
# Ejecutar SOLO después de `terraform destroy`: elimina el state. Falla cerrado:
# ante cualquier duda (otra suscripción activa, plataforma existente, otro
# bootstrap en el mismo Resource Group, error de Azure) se detiene sin borrar.
# Pide escribir el sufijo para confirmar y es reejecutable.
set -euo pipefail
export MSYS_NO_PATHCONV=1 # Git Bash en Windows: no convertir /subscriptions/... en rutas.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/infra/bootstrap/bootstrap.env"
[[ -f "$ENV_FILE" ]] || { echo "No existe $ENV_FILE: no hay bootstrap que deshacer." >&2; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${NAME_SUFFIX:?bootstrap.env sin NAME_SUFFIX}"
: "${AZURE_SUBSCRIPTION_ID:?bootstrap.env sin AZURE_SUBSCRIPTION_ID}"
: "${TFSTATE_STORAGE_ACCOUNT:?bootstrap.env sin TFSTATE_STORAGE_ACCOUNT}"

RG="${TFSTATE_RESOURCE_GROUP:-rg-eventos-tfstate}"
ROLES="eventos-${NAME_SUFFIX}-vm-operator eventos-${NAME_SUFFIX}-vm-deploy"
IDENTITIES="id-eventos-plan id-eventos-apply id-eventos-ops id-eventos-deploy"

# 1. La sesión de az debe estar en la suscripción de este bootstrap.
CURRENT_SUB="$(az account show --query id -o tsv | tr -d '\r')"
if [[ "$CURRENT_SUB" != "$AZURE_SUBSCRIPTION_ID" ]]; then
  echo "La suscripción activa (${CURRENT_SUB}) no es la de bootstrap.env (${AZURE_SUBSCRIPTION_ID})." >&2
  echo "Ejecutar: az account set --subscription ${AZURE_SUBSCRIPTION_ID}" >&2
  exit 1
fi
SUB_SCOPE="/subscriptions/${CURRENT_SUB}"

# 2. La plataforma de este sufijo ya debe estar destruida (se exige "false").
PLATFORM_EXISTS="$(az group exists --name "rg-eventos-${NAME_SUFFIX}" | tr -d '\r')"
if [[ "$PLATFORM_EXISTS" != "false" ]]; then
  echo "rg-eventos-${NAME_SUFFIX} existe o no se pudo comprobar (${PLATFORM_EXISTS:-sin respuesta}): ejecutar primero terraform destroy." >&2
  exit 1
fi

RG_EXISTS="$(az group exists --name "$RG" | tr -d '\r')"
if [[ "$RG_EXISTS" != "true" && "$RG_EXISTS" != "false" ]]; then
  echo "No se pudo comprobar ${RG} (${RG_EXISTS:-sin respuesta}). No se borra nada." >&2
  exit 1
fi

# 3. El Resource Group no debe contener el state de otro bootstrap: borrarlo
#    eliminaría también ese state (por ejemplo, el del ambiente compartido).
if [[ "$RG_EXISTS" == "true" ]]; then
  OTHER_STORAGE="$(az storage account list -g "$RG" \
    --query "[?name!='${TFSTATE_STORAGE_ACCOUNT}'].name" -o tsv | tr -d '\r')"
  if [[ -n "$OTHER_STORAGE" ]]; then
    echo "${RG} contiene el state de otro bootstrap (${OTHER_STORAGE//$'\n'/, }). No se borra nada." >&2
    exit 1
  fi
fi

echo "Se eliminarán en ${SUB_SCOPE}:"
echo "  - todas las asignaciones de rol de ${IDENTITIES// /, };"
echo "  - los roles personalizados ${ROLES// /, };"
echo "  - el Resource Group ${RG} (state ${TFSTATE_STORAGE_ACCOUNT}, identidades y credenciales federadas)."
read -r -p "Escribir el sufijo (${NAME_SUFFIX}) para confirmar: " answer
[[ "$answer" == "$NAME_SUFFIX" ]] || { echo "Cancelado."; exit 1; }

if [[ "$RG_EXISTS" == "true" ]]; then
  for id in $IDENTITIES; do
    # Un error de Azure aborta el script (set -e); solo "no existe" deja pid vacío.
    pid="$(az identity list -g "$RG" --query "[?name=='${id}'].principalId | [0]" -o tsv | tr -d '\r')"
    if [[ -n "$pid" ]]; then
      # Todas sus asignaciones, en cualquier alcance (suscripción, Storage o la VM).
      ids="$(az role assignment list --assignee-object-id "$pid" --all --query "[].id" -o tsv | tr -d '\r')"
      if [[ -n "$ids" ]]; then
        # shellcheck disable=SC2086 # un ID por palabra
        az role assignment delete --ids $ids -o none
      fi
      echo "Asignaciones de ${id} eliminadas."
    fi
  done
else
  echo "${RG} ya no existe: no hay identidades cuyas asignaciones eliminar."
fi

for role in $ROLES; do
  if [[ "$(az role definition list --custom-role-only true --name "$role" --query 'length(@)' -o tsv | tr -d '\r')" != "0" ]]; then
    az role definition delete --name "$role" --custom-role-only true --scope "$SUB_SCOPE" -o none
    echo "Rol ${role} eliminado."
  fi
done

if [[ "$RG_EXISTS" == "true" ]]; then
  # Las asignaciones con alcance en el Storage se eliminan junto con el recurso.
  az group delete --name "$RG" --yes -o none
  echo "Resource Group ${RG} eliminado."
fi
echo "Comprobar: az group exists --name ${RG}   (esperado: false)"
