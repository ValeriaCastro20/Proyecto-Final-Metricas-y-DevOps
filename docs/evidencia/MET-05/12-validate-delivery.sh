#!/usr/bin/env bash
# Offline checks only; never applies Kubernetes resources or sends readings.
set -euo pipefail
repo="$PWD"
tools_dir=$(mktemp -d /tmp/met05-validation.XXXXXX)
cd "$tools_dir"
curl -fsSL https://github.com/gitleaks/gitleaks/releases/download/v8.28.0/gitleaks_8.28.0_linux_x64.tar.gz -o gitleaks_8.28.0_linux_x64.tar.gz
curl -fsSL https://github.com/gitleaks/gitleaks/releases/download/v8.28.0/gitleaks_8.28.0_checksums.txt -o checksums.txt
sha256sum --check --ignore-missing checksums.txt
tar -xzf gitleaks_8.28.0_linux_x64.tar.gz gitleaks
curl -fsSL https://github.com/yannh/kubeconform/releases/download/v0.8.0/kubeconform-linux-amd64.tar.gz -o kubeconform.tar.gz
echo '9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883  kubeconform.tar.gz' | sha256sum --check
tar -xzf kubeconform.tar.gz kubeconform
cd "$repo"
for scope in dashboards docs/evidencia/MET-05 kubernetes/observability; do
  "$tools_dir/gitleaks" dir "$scope" --max-decode-depth 3 --no-banner --redact --config .gitleaks.toml
done
"$tools_dir/kubeconform" -strict -summary -kubernetes-version 1.35.0 kubernetes/observability
