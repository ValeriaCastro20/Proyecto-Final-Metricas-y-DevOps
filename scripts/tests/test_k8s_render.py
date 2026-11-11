"""Offline contract checks, not a substitute for Kubernetes server dry-run."""

import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "render_k8s", Path(__file__).resolve().parents[1] / "render-k8s.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
IMAGE = MODULE.APP + "@sha256:" + "a" * 64
POSTGRES = MODULE.POSTGRES + "@sha256:" + "b" * 64


class RenderTests(unittest.TestCase):
    def stage(self, stage, environment="development"):
        return MODULE.render(environment, stage, IMAGE, POSTGRES)["items"]

    def test_namespaces_are_explicit_and_isolated(self):
        for environment in ("development", "production"):
            for stage in ("foundation", "migration", "workloads"):
                for item in self.stage(stage, environment):
                    if item["kind"] == "Namespace":
                        self.assertEqual(item["metadata"]["name"], f"eventos-{environment}")
                    else:
                        self.assertEqual(item["metadata"]["namespace"], f"eventos-{environment}")

    def test_floating_images_foreign_repositories_and_bad_digests_fail(self):
        for invalid in ("latest", MODULE.APP + ":sha-abc", IMAGE + ":tag", IMAGE[:-1], IMAGE.replace("ghcr.io", "evil.invalid")):
            with self.subTest(image=invalid), self.assertRaises(ValueError):
                MODULE.render("development", "workloads", invalid, POSTGRES)
        with self.assertRaises(ValueError):
            MODULE.render("development", "workloads", IMAGE, "postgres:16")
        with self.assertRaises(ValueError):
            MODULE.render("unknown", "workloads", IMAGE, POSTGRES)
        with self.assertRaises(ValueError):
            MODULE.render("development", "all", IMAGE, POSTGRES)

    def test_explicit_migration_uses_same_digest_without_runtime_keys(self):
        job = self.stage("migration")[0]
        self.assertEqual(job["spec"]["backoffLimit"], 0)
        container = job["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(container["image"], IMAGE)
        self.assertEqual(container["args"], ["migrate"])
        self.assertNotIn("envFrom", container)
        self.assertEqual(container["env"][0]["valueFrom"]["secretKeyRef"]["name"], "event-service-migration")

    def test_api_and_worker_are_separate_and_service_selects_only_api(self):
        service, api, worker = self.stage("workloads")
        self.assertEqual(service["spec"]["type"], "ClusterIP")
        for deployment, command in ((api, "serve"), (worker, "process")):
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            self.assertEqual(container["image"], IMAGE)
            self.assertEqual(container["args"], [command])
            self.assertNotIn("initContainers", deployment["spec"]["template"]["spec"])
        self.assertEqual(service["spec"]["selector"], api["spec"]["selector"]["matchLabels"])
        self.assertNotEqual(service["spec"]["selector"], worker["spec"]["selector"]["matchLabels"])
        worker_container = worker["spec"]["template"]["spec"]["containers"][0]
        for probe, kind in (("startupProbe", "live"), ("readinessProbe", "ready"), ("livenessProbe", "live")):
            self.assertEqual(
                worker_container[probe]["exec"]["command"],
                ["/usr/local/bin/event-service", "worker-health", kind],
            )
        self.assertEqual(
            [entry["name"] for entry in worker_container["env"]],
            ["DATABASE_URL", "WORKER_HEALTH_DIR"],
        )

    def test_database_data_outlives_pod_and_has_no_public_service(self):
        foundation = self.stage("foundation")
        db = next(item for item in foundation if item["kind"] == "StatefulSet")
        self.assertEqual(db["spec"]["volumeClaimTemplates"][0]["spec"]["storageClassName"], "local-path")
        self.assertEqual(db["spec"]["persistentVolumeClaimRetentionPolicy"]["whenDeleted"], "Retain")
        service = next(item for item in foundation if item["kind"] == "Service")
        self.assertNotIn("nodePort", service["spec"]["ports"][0])
        self.assertEqual(service["spec"]["clusterIP"], "None")

    def test_nonroot_no_tokens_capabilities_and_resource_bounds(self):
        for stage in ("foundation", "migration", "workloads"):
            for item in self.stage(stage):
                if item["kind"] not in ("StatefulSet", "Deployment", "Job"):
                    continue
                pod = item["spec"]["template"]["spec"]
                self.assertFalse(pod["automountServiceAccountToken"])
                self.assertTrue(pod["securityContext"]["runAsNonRoot"])
                for container in pod["containers"]:
                    self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
                    self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
                    self.assertEqual(container["securityContext"]["capabilities"]["drop"], ["ALL"])
                    self.assertEqual(set(container["resources"]), {"requests", "limits"})

    def test_api_liveness_does_not_restart_on_database_outage(self):
        api = self.stage("workloads")[1]["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(api["livenessProbe"]["httpGet"]["path"], "/health/live")
        self.assertEqual(api["readinessProbe"]["httpGet"]["path"], "/health/ready")

    def test_network_is_denied_by_default_with_only_database_exceptions(self):
        policies = {
            item["metadata"]["name"]: item["spec"]
            for item in self.stage("foundation")
            if item["kind"] == "NetworkPolicy"
        }
        self.assertEqual(policies["default-deny"]["podSelector"], {})
        self.assertEqual(set(policies["default-deny"]["policyTypes"]), {"Ingress", "Egress"})
        self.assertNotIn("ingress", policies["default-deny"])
        self.assertNotIn("egress", policies["default-deny"])
        for name in ("postgres-from-event-service", "event-service-to-postgres"):
            rules = policies[name].get("ingress") or policies[name]["egress"]
            self.assertEqual(rules[0]["ports"], [{"protocol": "TCP", "port": 5432}])

    def test_deployer_cannot_read_secrets_or_escalate(self):
        foundation = self.stage("foundation")
        role = next(item for item in foundation if item["kind"] == "Role")
        for rule in role["rules"]:
            self.assertNotIn("secrets", rule["resources"])
            self.assertNotIn("*", rule["resources"] + rule["verbs"] + rule["apiGroups"])
            self.assertNotIn("delete", rule["verbs"])
        self.assertFalse(any(item["kind"].startswith("Cluster") for item in foundation))

    def test_only_production_is_exposed_and_only_over_tls(self):
        host = "eventos-abc123.mexicocentral.cloudapp.azure.com"
        with self.assertRaises(ValueError):
            MODULE.render("development", "ingress", IMAGE, POSTGRES, host)
        for invalid in (None, "evil.example.com", host + ".evil.example.com"):
            with self.subTest(host=invalid), self.assertRaises(ValueError):
                MODULE.render("production", "ingress", IMAGE, POSTGRES, invalid)
        items = MODULE.render("production", "ingress", IMAGE, POSTGRES, host)["items"]
        ingress = next(item for item in items if item["kind"] == "Ingress")
        self.assertEqual(ingress["spec"]["tls"][0]["hosts"], [host])
        self.assertEqual(ingress["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.entrypoints"], "websecure")

    def test_public_ingress_excludes_metrics_but_preserves_api_routes(self):
        """Keep metrics internal without removing the API's public application routes."""
        host = "eventos-abc123.mexicocentral.cloudapp.azure.com"
        items = MODULE.render("production", "ingress", IMAGE, POSTGRES, host)["items"]
        ingress = next(item for item in items if item["kind"] == "Ingress")
        paths = ingress["spec"]["rules"][0]["http"]["paths"]

        def matches(request_path, rule):
            """Apply Kubernetes Exact or segment-based Prefix path matching."""
            if rule["pathType"] == "Exact":
                return request_path == rule["path"]
            prefix = rule["path"].rstrip("/")
            return request_path == prefix or request_path.startswith(prefix + "/")

        for private in ("/metrics", "/metrics/", "/metrics/example"):
            self.assertFalse(any(matches(private, rule) for rule in paths), private)
        for public in ("/v1/events", "/v1/readings", "/health/live", "/health/ready", "/docs", "/openapi.json"):
            self.assertTrue(any(matches(public, rule) for rule in paths), public)
        for rule in paths:
            self.assertEqual(rule["backend"]["service"], {"name": "event-service", "port": {"name": "http"}})
        service = self.stage("workloads")[0]
        self.assertEqual(service["spec"]["type"], "ClusterIP")
        self.assertEqual(service["spec"]["ports"][0]["port"], 8000)

if __name__ == "__main__":
    unittest.main()
