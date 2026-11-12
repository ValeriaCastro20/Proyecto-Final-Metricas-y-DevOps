set -euo pipefail
sudo -n k3s kubectl get node k3s-eventos -o json | python3 -c 'import json,sys; n=json.load(sys.stdin); print("allocatable="+str(n["status"]["allocatable"])); print("conditions="+str([(c["type"],c["status"]) for c in n["status"]["conditions"]]))'
sudo -n k3s kubectl describe node k3s-eventos | sed -n '/^Allocated resources:/,/^Events:/p'
free -m
df -h /var/lib/rancher/k3s
