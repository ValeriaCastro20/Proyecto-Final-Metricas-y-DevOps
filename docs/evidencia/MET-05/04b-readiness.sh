set -euo pipefail
sudo -n k3s kubectl --namespace eventos-development get deployments,pods -o wide
for component in api worker; do
  sudo -n k3s kubectl --namespace eventos-development wait --for=condition=Ready pod -l "app.kubernetes.io/name=event-service,app.kubernetes.io/component=$component" --field-selector=status.phase=Running --timeout=30s
done
sudo -n k3s kubectl --namespace eventos-development get pods -l app.kubernetes.io/name=event-service -o json | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(json.dumps({"pod":p["metadata"]["name"],"phase":p["status"]["phase"],"conditions":p["status"].get("conditions",[]),"containers":p["status"].get("containerStatuses",[])})) for p in d["items"] if p["status"]["phase"]=="Running"]'
