set -euo pipefail
sudo -n k3s kubectl --namespace eventos-development exec deployment/prometheus -- promtool check config /etc/prometheus/prometheus.yml
sudo -n k3s kubectl --namespace eventos-development rollout restart deployment/event-service-api
sudo -n k3s kubectl --namespace eventos-development rollout status deployment/event-service-api --timeout=180s
sudo -n k3s kubectl --namespace eventos-development rollout restart deployment/event-service-worker
sudo -n k3s kubectl --namespace eventos-development rollout status deployment/event-service-worker --timeout=180s
sudo -n k3s kubectl --namespace eventos-development wait --for=condition=Ready pod -l app.kubernetes.io/name=event-service --timeout=120s
sudo -n k3s kubectl --namespace eventos-development get deployments,pods,services -o wide
