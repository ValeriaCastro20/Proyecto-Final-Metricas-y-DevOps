#!/usr/bin/env bash
# Preparation only: offline tests plus validation of the already-captured READ-ONLY snapshot.
set -euo pipefail
python3 -B scripts/met07.py plan
python3 -B -m unittest discover -s scripts/tests -v
python3 -B scripts/test-observability.py
python3 -B - <<'PY'
import importlib.util,json,pathlib
spec=importlib.util.spec_from_file_location("met07","scripts/met07.py")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
s=json.loads(pathlib.Path("docs/evidencia/MET-07/preparation-readonly.json").read_text())
assert s["incident_executed"] is False and s["execution_authorized"] is False
assert s["context"]["value"] and s["deployment"]["uid"]
assert s["deployment"]["replicas"] == s["deployment"]["ready_replicas"] == 1
assert s["deployment"]["selector"] == m.LABELS
for query in s["prometheus"].values():
    assert query["http"] == 200 and not query.get("failed") and not query["connection_error"]
assert m.rule_state({"status":"success","data":s["prometheus"]["rules"]["data"]},s["namespace"]) == "inactive"
assert s["prometheus"]["backlog"]["data"]["result"][0]["value"][1] == "0"
print("READ_ONLY snapshot: identity, real labels, unchanged >100/2m, inactive and backlog=0 verified")
PY
temp_tools=$(mktemp -d /tmp/met07-validation.XXXXXX)
curl -fsSL https://github.com/gitleaks/gitleaks/releases/download/v8.28.0/gitleaks_8.28.0_linux_x64.tar.gz -o "$temp_tools/gitleaks_8.28.0_linux_x64.tar.gz"
curl -fsSL https://github.com/gitleaks/gitleaks/releases/download/v8.28.0/gitleaks_8.28.0_checksums.txt -o "$temp_tools/checksums.txt"
(cd "$temp_tools" && sha256sum --check --ignore-missing checksums.txt && tar -xzf gitleaks_8.28.0_linux_x64.tar.gz gitleaks)
"$temp_tools/gitleaks" dir scripts --max-decode-depth 3 --no-banner --redact --config .gitleaks.toml
"$temp_tools/gitleaks" dir docs/evidencia/MET-07 --max-decode-depth 3 --no-banner --redact --config .gitleaks.toml
