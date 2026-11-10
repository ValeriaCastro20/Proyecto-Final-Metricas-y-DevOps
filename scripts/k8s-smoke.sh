#!/bin/bash
# Prueba funcional posterior a un despliegue: salud, autenticación y una lectura procesada.
# Las claves se leen del clúster, quedan en memoria y llegan a curl por stdin.
#
# Uso: scripts/k8s-smoke.sh <development|production>
set -euo pipefail

case "${1:-}" in
  development | production) environment=$1 ;;
  *)
    echo "Uso: $0 <development|production>" >&2
    exit 2
    ;;
esac

namespace="eventos-$environment"
read -r -a kubectl_cmd <<<"${KUBECTL:-kubectl}"
kube() { "${kubectl_cmd[@]}" "$@"; }

port=${SMOKE_PORT:-18080}
base="http://127.0.0.1:$port"
device=smoke-entrega
workdir=$(mktemp -d)
forward_pid=

cleanup() {
  if [[ -n "$forward_pid" ]]; then
    kill "$forward_pid" 2>/dev/null || true
    wait "$forward_pid" 2>/dev/null || true
  fi
  rm -rf "$workdir"
}
trap cleanup EXIT

fail() {
  echo "SMOKE FALLÓ: $1" >&2
  exit 1
}

secret_value() {
  kube -n "$namespace" get secret event-service-credentials -o "go-template={{index .data \"$1\" | base64decode}}"
}

# request <metodo> <ruta> <clave o vacío> [cuerpo]: imprime el código HTTP.
request() {
  local method=$1 path=$2 key=$3 body=${4:-}
  local arguments=(--silent --max-time 10 --output "$workdir/body" --write-out '%{http_code}' --request "$method" --config -)
  [[ -n "$body" ]] && arguments+=(--header 'Content-Type: application/json' --data "$body")
  if [[ -n "$key" ]]; then
    printf 'header = "X-API-Key: %s"\n' "$key" | curl "${arguments[@]}" "$base$path"
  else
    curl "${arguments[@]}" "$base$path" </dev/null
  fi
}

# Con un puerto ocupado, las peticiones llegarían a otro servicio, quizá de otro ambiente.
if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
  fail "el puerto local $port ya está en uso"
fi

# Sin la función kube: en segundo plano, $! sería un subshell y kubectl sobreviviría al kill.
"${kubectl_cmd[@]}" -n "$namespace" port-forward service/event-service "$port:8000" --address 127.0.0.1 >/dev/null 2>&1 &
forward_pid=$!
for _ in $(seq 1 30); do
  [[ "$(request GET /health/live '')" == 200 ]] && break
  sleep 1
done

status=$(request GET /health/live '')
[[ "$status" == 200 ]] || fail "/health/live devolvió $status"
status=$(request GET /health/ready '')
[[ "$status" == 200 ]] || fail "/health/ready devolvió $status"
status=$(request GET /v1/devices '')
[[ "$status" == 401 ]] || fail "una consulta sin clave devolvió $status en vez de 401"

producer_key=$(secret_value EVENT_PRODUCER_KEY)
analyst_key=$(secret_value EVENT_ANALYST_KEY)

# El dispositivo se reutiliza entre entregas: la API no permite borrarlo.
status=$(request GET "/v1/devices/$device" "$analyst_key")
if [[ "$status" != 200 ]]; then
  status=$(request POST /v1/devices "$producer_key" \
    "{\"id\":\"$device\",\"facility_id\":\"smoke\",\"limits\":{\"temperature_min\":0,\"temperature_max\":35,\"humidity_min\":20,\"humidity_max\":80}}")
  [[ "$status" == 200 || "$status" == 201 ]] || fail "el alta del dispositivo devolvió $status"
fi

now=$(date -u +%s)
occurred=$(date -u -d "@$now" +%Y-%m-%dT%H:%M:%SZ)
until=$(date -u -d "@$((now + 1))" +%Y-%m-%dT%H:%M:%SZ)
event="smoke-$now-$RANDOM"
status=$(request POST /v1/readings "$producer_key" \
  "{\"device_id\":\"$device\",\"event_id\":\"$event\",\"occurred_at\":\"$occurred\",\"temperature\":20.5,\"humidity\":50.0,\"state\":\"running\"}")
[[ "$status" == 202 ]] || fail "la lectura devolvió $status en vez de 202"

# La respuesta 202 no significa procesada: se espera a que el worker la marque.
for _ in $(seq 1 30); do
  status=$(request GET "/v1/devices/$device/readings?from=$occurred&to=$until" "$analyst_key")
  [[ "$status" == 200 ]] || fail "el histórico devolvió $status"
  if python3 - "$event" "$workdir/body" <<'PY'
import json
import sys

with open(sys.argv[2], encoding="utf-8") as response:
    readings = json.load(response)
processed = isinstance(readings, list) and any(
    isinstance(reading, dict)
    and reading.get("event_id") == sys.argv[1]
    and isinstance(reading.get("processed_at"), str)
    and bool(reading["processed_at"])
    for reading in readings
)
sys.exit(0 if processed else 1)
PY
  then
    echo "SMOKE OK: $namespace, lectura $event procesada."
    exit 0
  fi
  sleep 2
done
fail "el worker no procesó la lectura en 60 segundos"
