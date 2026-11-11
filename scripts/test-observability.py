#!/usr/bin/env python3
"""Offline contracts for the repository's same-namespace NetworkPolicies.

Requires PyYAML 6.0.3. Checks declared connectivity, not CNI enforcement.
"""
import importlib.util
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("render_k8s", ROOT / "scripts/render-k8s.py")
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)


def matches(selector, labels):
    """Match the label-only selectors supported by these network contracts."""
    # Fail rather than silently mis-model a newly introduced selector type.
    if set(selector) - {"matchLabels"}:
        raise ValueError("extend the contract model for this selector type")
    return all(labels.get(key) == value for key, value in selector.get("matchLabels", {}).items())


class NetworkTests(unittest.TestCase):
    """Check declared telemetry connectivity against real deployment and Service labels."""
    @classmethod
    def setUpClass(cls):
        """Load rendered development workloads and optional observability resources."""
        cls.namespace = "eventos-development"
        cls.items = RENDER.render("development", "foundation", RENDER.APP + "@sha256:" + "a" * 64,
                                  RENDER.POSTGRES + "@sha256:" + "b" * 64)["items"]
        cls.items.extend(RENDER.render("development", "workloads", RENDER.APP + "@sha256:" + "a" * 64,
                                      RENDER.POSTGRES + "@sha256:" + "b" * 64)["items"])
        for path in (ROOT / "kubernetes/observability").glob("*.yaml"):
            cls.items.extend(yaml.safe_load_all(path.read_text()))
        cls.policies = [item["spec"] for item in cls.items if item["kind"] == "NetworkPolicy"
                        and item["metadata"]["namespace"] == cls.namespace]
        cls.labels = {item["metadata"]["name"]: item["spec"]["template"]["metadata"]["labels"]
                      for item in cls.items if item["kind"] == "Deployment"}
        cls.labels.update(api=cls.labels["event-service-api"],
                          worker=cls.labels["event-service-worker"],
                          stranger={"app": "untrusted"})

    def direction_allowed(self, own, peer, direction, port):
        """Evaluate one TCP direction for peers in the same development namespace."""
        selected = [p for p in self.policies if direction.title() in p["policyTypes"]
                    and matches(p["podSelector"], own)]
        if not selected:
            return True
        for policy in selected:
            for rule in policy.get(direction, []):
                if "ports" in rule and not any(p.get("protocol", "TCP") == "TCP" and p["port"] == port
                                               for p in rule["ports"]):
                    continue
                peers = rule.get("to" if direction == "egress" else "from", [{}])
                for target in peers:
                    if set(target) - {"namespaceSelector", "podSelector"}:
                        raise ValueError("extend the contract model for this peer type")
                    if (matches(target.get("namespaceSelector", {}), {"kubernetes.io/metadata.name": self.namespace})
                            and matches(target.get("podSelector", {}), peer)):
                        return True
        return False

    def connected(self, source, destination, port):
        """Require both the source egress and destination ingress to permit TCP."""
        return (self.direction_allowed(self.labels[source], self.labels[destination], "egress", port)
                and self.direction_allowed(self.labels[destination], self.labels[source], "ingress", port))

    def test_datasource_and_telemetry_paths_are_allowed(self):
        """Permit Grafana queries, Prometheus scrapes and API/worker OTLP export."""
        for source, destination, port in [("grafana", "prometheus", 9090), ("prometheus", "api", 8000),
                                          ("prometheus", "worker", 9000), ("api", "jaeger", 4318),
                                          ("worker", "jaeger", 4318)]:
            with self.subTest(source=source, destination=destination, port=port):
                self.assertTrue(self.connected(source, destination, port))

    def test_permissions_remain_scoped_to_their_peers_and_ports(self):
        """Reject unrelated pods, destinations and ports under default-deny."""
        for source, destination, port in [("stranger", "prometheus", 9090), ("grafana", "api", 8000),
                                          ("api", "jaeger", 16686), ("grafana", "prometheus", 9091)]:
            with self.subTest(source=source, destination=destination, port=port):
                self.assertFalse(self.connected(source, destination, port))

    def test_services_select_the_backends_used_by_the_network_contracts(self):
        """Ensure each telemetry Service selects the expected deployment and port."""
        services = {item["metadata"]["name"]: item["spec"] for item in self.items if item["kind"] == "Service"}
        for name, backend, port in [("grafana", "grafana", 3000), ("prometheus", "prometheus", 9090),
                                     ("jaeger-collector", "jaeger", 4318), ("event-service", "api", 8000),
                                     ("event-service-worker-metrics", "worker", 9000)]:
            with self.subTest(service=name):
                self.assertTrue(matches({"matchLabels": services[name]["selector"]}, self.labels[backend]))
                self.assertIn(port, [entry["port"] for entry in services[name]["ports"]])

    def test_traces_are_opt_in_and_stay_in_the_jaeger_namespace(self):
        """Configure only the Jaeger namespace and make telemetry optional elsewhere."""
        config = next(item for item in self.items if item["kind"] == "ConfigMap"
                      and item["metadata"]["name"] == "event-service-telemetry")
        self.assertEqual(config["metadata"]["namespace"], self.namespace)
        self.assertEqual(config["data"]["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"],
                         f"http://jaeger-collector.{self.namespace}.svc.cluster.local:4318/v1/traces")
        for environment in ("development", "production"):
            foundation = RENDER.render(environment, "foundation", RENDER.APP + "@sha256:" + "a" * 64,
                                       RENDER.POSTGRES + "@sha256:" + "b" * 64)["items"]
            self.assertFalse(any("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT" in item.get("data", {})
                                 for item in foundation))
            workloads = RENDER.render(environment, "workloads", RENDER.APP + "@sha256:" + "a" * 64,
                                      RENDER.POSTGRES + "@sha256:" + "b" * 64)["items"]
            for deployment in workloads[1:]:
                container = deployment["spec"]["template"]["spec"]["containers"][0]
                self.assertIn({"configMapRef": {"name": "event-service-telemetry", "optional": True}},
                              container["envFrom"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
