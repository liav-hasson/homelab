"""Local dashboard, provisioning, privacy and alert-routing regression guards."""

import json
import re
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

MONITORING = Path(__file__).resolve().parents[1]
K8S = MONITORING.parents[1]
CONFIGS = MONITORING / "configs"
EXPECTED = {
    "homelab-overview": "Homelab Overview",
    "platform-delivery-edge": "Platform - Delivery & Edge",
    "ankilabs-service-health": "AnkiLabs - Service Health",
    "ankilabs-search-postgres": "AnkiLabs - Search & PostgreSQL",
    "quizlabs-overview": "QuizLabs - Overview",
}
SENSITIVE = r"\b(request_id|query_fingerprint|db_backend_pid|cursor)\s*(=|:)"


class MonitoringContractTests(unittest.TestCase):
    """Validate the repository contract without a cluster or secret access."""

    def setUp(self) -> None:
        """Read only monitoring definitions."""
        self.dashboards = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((CONFIGS / "dashboards").glob("*.json"))
        ]

    def test_exact_five_dashboard_schemas_and_nonoverlapping_layouts(self) -> None:
        """Reject obsolete dashboards, UID collisions and invalid panel layouts."""
        schema = json.loads(
            (Path(__file__).parent / "dashboard.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        self.assertEqual(len(self.dashboards), 5)
        self.assertEqual(
            {item["uid"]: item["title"] for item in self.dashboards}, EXPECTED
        )
        for dashboard in self.dashboards:
            with self.subTest(dashboard=dashboard["uid"]):
                validator.validate(dashboard)
                occupied = set()
                panel_ids = set()
                for panel in dashboard["panels"]:
                    self.assertNotIn(panel["id"], panel_ids)
                    panel_ids.add(panel["id"])
                    grid = panel["gridPos"]
                    self.assertLessEqual(grid["x"] + grid["w"], 24)
                    cells = {
                        (x, y)
                        for x in range(grid["x"], grid["x"] + grid["w"])
                        for y in range(grid["y"], grid["y"] + grid["h"])
                    }
                    self.assertFalse(occupied & cells)
                    occupied |= cells

    def test_provisioning_is_exact_and_references_existing_resources(self) -> None:
        """Require one coherent source of provisioned dashboards."""
        config = yaml.safe_load(
            (CONFIGS / "kustomization.yaml").read_text(encoding="utf-8")
        )
        generators = config["configMapGenerator"]
        self.assertEqual(len(generators), 1)
        self.assertEqual(generators[0]["options"]["labels"]["grafana_dashboard"], "1")
        self.assertEqual(
            set(generators[0]["files"]),
            {f"dashboards/{uid}.json" for uid in EXPECTED},
        )
        for resource in config["resources"]:
            self.assertTrue((CONFIGS / resource).is_file(), resource)

    def test_application_selectors_are_namespace_isolated(self) -> None:
        """Only route-bound native edge metrics may use another scrape namespace."""
        for dashboard in self.dashboards:
            uid = dashboard["uid"]
            if not uid.startswith(("ankilabs-", "quizlabs-")):
                continue
            namespace = "quizlabs" if uid.startswith("quizlabs-") else "ankilabs"
            for panel in dashboard["panels"]:
                for target in panel.get("targets", []):
                    expr = target["expr"]
                    if panel["type"] == "logs":
                        selectors = [expr[: expr.index("}") + 1]]
                    else:
                        selectors = re.findall(r"\{[^{}]*\}", expr)
                    self.assertTrue(selectors, expr)
                    for selector in selectors:
                        if 'namespace="envoy-gateway-system"' in selector:
                            self.assertIn(
                                f'envoy_cluster_name=~"httproute/{namespace}/',
                                selector.replace(
                                    'envoy_cluster_name="', 'envoy_cluster_name=~"'
                                ),
                            )
                        else:
                            self.assertRegex(
                                selector, rf'\b(?:exported_)?namespace="{namespace}"'
                            )
                        self.assertNotRegex(selector, SENSITIVE)

    def test_no_fake_zero_health_or_sparse_percentiles(self) -> None:
        """Keep missing observations visible and latency units honest."""
        for dashboard in self.dashboards:
            serialized = json.dumps(dashboard)
            self.assertNotRegex(serialized, r"vector\s*\(\s*0\s*\)")
            self.assertNotIn("nullAsZero", serialized)
            self.assertNotIn("histogram_quantile", serialized)
            for panel in dashboard["panels"]:
                for target in panel.get("targets", []):
                    if panel["type"] == "timeseries" and (
                        "duration_seconds_sum" in target["expr"]
                    ):
                        self.assertEqual(panel["fieldConfig"]["defaults"]["unit"], "s")

    def test_alert_links_routes_and_namespace_matcher_strategy(self) -> None:
        """Application/database alerts must reach the existing POD Discord receiver."""
        rules = yaml.safe_load((CONFIGS / "alerts.yaml").read_text(encoding="utf-8"))
        for group in rules["spec"]["groups"]:
            for rule in group["rules"]:
                annotations = rule["annotations"]
                self.assertIn("/d/", annotations["dashboard_url"])
                self.assertIn("runbook.md#", annotations["runbook_url"])
                self.assertTrue(annotations["description"])
        routes = yaml.safe_load(
            (CONFIGS / "alertmanager-config.yaml").read_text(encoding="utf-8")
        )["spec"]["route"]["routes"]
        pod_route = next(
            route for route in routes if route["receiver"] == "pods-discord"
        )
        scope_pattern = pod_route["matchers"][0]["value"]
        for scope in ("pods", "applications", "database", "platform"):
            self.assertIsNotNone(re.fullmatch(scope_pattern, scope))
        release = yaml.safe_load(
            (MONITORING / "controllers/kube-prometheus-stack/release.yaml").read_text(
                encoding="utf-8"
            )
        )
        strategy = release["spec"]["values"]["alertmanager"]["alertmanagerSpec"]
        self.assertEqual(strategy["alertmanagerConfigMatcherStrategy"]["type"], "None")

    def test_postgres_privacy_and_monitoring_credentials(self) -> None:
        """Keep stderr, suppress query text and require a separate monitoring login."""
        chart = K8S / "apps/ankilabs/charts/postgres"
        values = yaml.safe_load((chart / "values.yaml").read_text(encoding="utf-8"))
        config = values["config"]
        self.assertEqual(config["log_destination"], "stderr")
        self.assertEqual(config["logging_collector"], "off")
        self.assertEqual(config["log_statement"], "none")
        self.assertEqual(config["log_min_error_statement"], "panic")
        self.assertEqual(config["log_error_verbosity"], "terse")
        for name in (
            "log_parameter_max_length",
            "log_parameter_max_length_on_error",
            "log_transaction_sample_rate",
        ):
            self.assertEqual(config[name], 0)
        for name in ("log_min_duration_statement", "log_min_duration_sample"):
            self.assertEqual(config[name], -1)
        monitoring = values["monitoring"]
        self.assertNotEqual(values["existingSecret"], monitoring["existingSecret"])
        self.assertNotEqual(values["user"], monitoring["user"])
        self.assertRegex(monitoring["image"], r":v[0-9.]+@sha256:[a-f0-9]{64}$")
        exporter = (chart / "templates/exporter.yaml").read_text(encoding="utf-8")
        self.assertIn("--no-collector.stat_statements", exporter)
        self.assertIn("--collector.stat_checkpointer", exporter)
        self.assertNotIn("POSTGRES_PASSWORD", exporter)
        self.assertNotIn("query-path", exporter)

    def test_collector_does_not_index_identifiers_or_drop_records(self) -> None:
        """Only bounded severity values are added as log index labels."""
        release = yaml.safe_load(
            (MONITORING / "controllers/loki-stack/promtail-release.yaml").read_text(
                encoding="utf-8"
            )
        )
        stages = release["spec"]["values"]["config"]["snippets"]["pipelineStages"]
        self.assertEqual(stages[0], {"cri": {}})
        serialized = json.dumps(stages)
        self.assertNotIn('"drop":', serialized)
        self.assertNotIn('"drop_malformed": true', serialized)
        for stage in stages[1:]:
            for nested in stage["match"]["stages"]:
                if "labels" in nested:
                    self.assertEqual(set(nested["labels"]), {"severity"})
        envoy = (K8S / "platform/envoy/templates/envoyproxy.yaml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("%REQ(X-ENVOY-ORIGINAL-PATH", envoy)
        self.assertNotIn("%REQ(:PATH)", envoy)
        self.assertIn("%ROUTE_NAME%", envoy)

    def test_lookup_scrapes_disambiguate_metric_families_without_shadowing_gateway(
        self,
    ) -> None:
        """Range functions drop metric names, so shared jobs need service identity."""
        monitors = list(
            yaml.safe_load_all(
                (CONFIGS / "application-podmonitors.yaml").read_text(encoding="utf-8")
            )
        )
        lookups = next(
            item for item in monitors if item["metadata"]["name"] == "ankilabs-lookups"
        )
        endpoint = lookups["spec"]["podMetricsEndpoints"][0]
        self.assertIn(
            {
                "sourceLabels": ["__meta_kubernetes_pod_label_app_kubernetes_io_name"],
                "targetLabel": "service",
            },
            endpoint["relabelings"],
        )
        gateway = yaml.safe_load(
            (CONFIGS / "ankilabs-api-gateway-podmonitor.yaml").read_text(
                encoding="utf-8"
            )
        )
        for endpoint in gateway["spec"]["podMetricsEndpoints"]:
            for relabeling in endpoint.get("relabelings", []):
                self.assertNotEqual(relabeling.get("targetLabel"), "service")


if __name__ == "__main__":
    unittest.main()
