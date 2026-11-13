#!/usr/bin/env bash
# Acceso de despliegue de la aplicación (DEV-05), reproducible para DEV-13.
#
# Crea lo que usa .github/workflows/deliver.yml con la variable DEPLOY_CLIENT_ID:
#   - identidad id-eventos-deploy (en el Resource Group del bootstrap);
#   - rol personalizado eventos-<sufijo>-vm-deploy: leer la VM, ver su estado y
#     ejecutar Run Command; asignado SOLO a la VM de K3s;
#   - credenciales federadas OIDC para los environments development y production.
#
# Se ejecuta DESPUÉS del primer `terraform apply`, porque la asignación apunta a
# la VM, y otra vez si la VM se reemplaza. Es idempotente: con todo creado no
# cambia nada. Requiere la sesión de Owner del bootstrap, GitHub CLI y
# infra/bootstrap/bootstrap.env.
set -euo pipefail
export MSYS_NO_PATHCONV=1 # Git Bash en Windows: no convertir /subscriptions/... en rutas.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/infra/bootstrap/bootstrap.env"
[[ -f "$ENV_FILE" ]] || { echo "No existe $ENV_FILE: ejecutar primero bootstrap.sh." >&2; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${NAME_SUFFIX:?bootstrap.env sin NAME_SUFFIX}"
: "${AZURE_SUBSCRIPTION_ID:?bootstrap.env sin AZURE_SUBSCRIPTION_ID}"

REPO="${GITHUB_REPOSITORY:-marchelo23/Proyecto-Final-Metricas-y-DevOps}"
RG="${TFSTATE_RESOURCE_GROUP:-rg-eventos-tfstate}"
LOCATION="${LOCATION:-westus}"
DEPLOY_ID="id-eventos-deploy"
ROLE="eventos-${NAME_SUFFIX}-vm-deploy"
VM_RG="rg-eventos-${NAME_SUFFIX}"
VM="vm-eventos-${NAME_SUFFIX}-k3s"
ENVIRONMENTS="development production"

CURRENT_SUB="$(az account show --query id -o tsv | tr -d '\r')"
if [[ "$CURRENT_SUB" != "$AZURE_SUBSCRIPTION_ID" ]]; then
  echo "La suscripción activa (${CURRENT_SUB}) no es la de bootstrap.env (${AZURE_SUBSCRIPTION_ID})." >&2
  echo "Ejecutar: az account set --subscription ${AZURE_SUBSCRIPTION_ID}" >&2
  exit 1
fi
SUB_SCOPE="/subscriptions/${CURRENT_SUB}"

if ! VM_ID="$(az vm show -g "$VM_RG" -n "$VM" --query id -o tsv 2>/dev/null | tr -d '\r')" || [[ -z "$VM_ID" ]]; then
  echo "No existe ${VM} en ${VM_RG}: ejecutar primero terraform apply." >&2
  exit 1
fi

echo "== Identidad ${DEPLOY_ID}"
if [[ "$(az identity list -g "$RG" --query "[?name=='${DEPLOY_ID}'] | length(@)" -o tsv | tr -d '\r')" == "0" ]]; then
  az identity create -g "$RG" -n "$DEPLOY_ID" --location "$LOCATION" -o none
  echo "creada"
else
  echo "ya existe"
fi
DEPLOY_CLIENT_ID="$(az identity show -g "$RG" -n "$DEPLOY_ID" --query clientId -o tsv | tr -d '\r')"
DEPLOY_PRINCIPAL_ID="$(az identity show -g "$RG" -n "$DEPLOY_ID" --query principalId -o tsv | tr -d '\r')"

echo "== Rol ${ROLE}"
if [[ "$(az role definition list --custom-role-only true --name "$ROLE" --query 'length(@)' -o tsv | tr -d '\r')" == "0" ]]; then
  az role definition create -o none --role-definition "$(cat <<JSON
{
  "Name": "${ROLE}",
  "Description": "Leer estado y ejecutar Run Command en la VM de K3s (entrega controlada DEV-05).",
  "Actions": [
    "Microsoft.Compute/virtualMachines/read",
    "Microsoft.Compute/virtualMachines/instanceView/read",
    "Microsoft.Compute/virtualMachines/runCommand/action"
  ],
  "NotActions": [],
  "AssignableScopes": ["${SUB_SCOPE}"]
}
JSON
)"
  echo "creado"
else
  echo "ya existe"
fi

echo "== Asignación del rol sobre la VM"
assigned() {
  [[ "$(az role assignment list --assignee-object-id "$DEPLOY_PRINCIPAL_ID" --scope "$VM_ID" \
    --query "[?roleDefinitionName=='${ROLE}'] | length(@)" -o tsv | tr -d '\r')" != "0" ]]
}
if assigned; then
  echo "ya existe"
else
  # Un rol o una identidad recién creados tardan en poder asignarse.
  for attempt in $(seq 1 18); do
    if az role assignment create --assignee-object-id "$DEPLOY_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
      --role "$ROLE" --scope "$VM_ID" -o none 2>/dev/null; then
      echo "creada"
      break
    fi
    [[ "$attempt" == 18 ]] && { echo "No se pudo asignar ${ROLE} (propagación)." >&2; exit 1; }
    sleep 10
  done
fi

echo "== Credenciales federadas para ${REPO}"
OWNER="${REPO%%/*}"
NAME="${REPO#*/}"
OWNER_ID="$(gh api "users/${OWNER}" --jq .id)"
REPO_ID="$(gh api "repos/${REPO}" --jq .id)"
for env in $ENVIRONMENTS; do
  # GitHub puede emitir el subject con o sin los IDs inmutables; se registran ambos formatos.
  for prefix in "repo:${OWNER}/${NAME}" "repo:${OWNER}@${OWNER_ID}/${NAME}@${REPO_ID}"; do
    tag="$([[ "$prefix" == *@* ]] && echo ids || echo nombre)"
    fic="github-${env}-${tag}"
    if az identity federated-credential show -g "$RG" --identity-name "$DEPLOY_ID" -n "$fic" -o none 2>/dev/null; then
      echo "${fic}: ya existe"
    else
      az identity federated-credential create -g "$RG" --identity-name "$DEPLOY_ID" -n "$fic" \
        --issuer "https://token.actions.githubusercontent.com" \
        --subject "${prefix}:environment:${env}" --audiences "api://AzureADTokenExchange" -o none
      echo "${fic}: creada"
    fi
  done
done

# bootstrap.sh reescribe bootstrap.env: se agrega (o actualiza) solo esta línea.
tmp="$(mktemp)"
grep -v '^DEPLOY_CLIENT_ID=' "$ENV_FILE" > "$tmp" || true
echo "DEPLOY_CLIENT_ID=${DEPLOY_CLIENT_ID}" >> "$tmp"
mv "$tmp" "$ENV_FILE"

cat <<MSG

Acceso de despliegue listo. En ${REPO} deben existir:
  - los environments "development" y "production", limitados a la rama main
    ("production" con revisores requeridos);
  - la variable de GitHub Actions DEPLOY_CLIENT_ID=${DEPLOY_CLIENT_ID}
Si la VM se reemplaza, volver a ejecutar este script: la asignación apunta a la VM.
MSG
