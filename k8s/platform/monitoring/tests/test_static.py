"""Local dashboard, provisioning, privacy and alert-routing regression guards."""

import json
import re
import unittest
from pathlib import Path

import yaml
from dashboard_panels import iter_panels
from jsonschema import Draft202012Validator

MONITORING = Path(__file__).resolve().parents[1]
K8S = MONITORING.parents[1]
CONFIGS = MONITORING / "configs"
EXPECTED = {
    "homelab-overview": "Homelab Overview",
    "platform-delivery-edge": "Platform - Delivery & Edge",
    "platform-storage": "Platform - Storage",
    "ankilabs-service-health": "AnkiLabs - Service Health",
    "ankilabs-search-postgres": "AnkiLabs - Search & PostgreSQL",
    "ankilabs-ai": "AnkiLabs - AI",
    "quizlabs-overview": "QuizLabs - Overview",
}
NAVIGATION_TAG = "homelab-monitoring"
APP_TAGS = {"ankilabs", "quizlabs", "platform", "homelab"}
RUNBOOK = MONITORING / "runbook.md"
RUNBOOK_URL = "https://github.com/liav-hasson/homelab/blob/main/k8s/platform/monitoring/runbook.md"
SENSITIVE = r"\b(request_id|query_fingerprint|db_backend_pid|cursor)\s*(=|:)"
POSTGRES = "grafana-postgresql-datasource"
LITELLM_VIEWS = K8S / "apps/ankilabs/charts/llm-proxy/files/grafana-views.sql"
# LiteLLM columns holding key hashes, prompts, answers or request metadata.
LITELLM_PRIVATE = (
    r"\b(token|api_key|messages|response|metadata|proxy_server_request|key_name)\b"
)


def sql_targets(dashboards: list[dict]) -> list[str]:
    """Every PostgreSQL panel query."""
    return [
        target["rawSql"]
        for dashboard in dashboards
        for panel in iter_panels(dashboard)
        if panel.get("datasource", {}).get("type") == POSTGRES
        for target in panel["targets"]
    ]


def dashboard_validator() -> Draft202012Validator:
    """The checked-in dashboard contract."""
    schema = json.loads(
        (Path(__file__).parent / "dashboard.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def runbook_anchors() -> set[str]:
    """GitHub heading anchors of the runbook."""
    headings = re.findall(
        r"^#{1,6} (.+)$", RUNBOOK.read_text(encoding="utf-8"), re.MULTILINE
    )
    return {
        re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")
        for heading in headings
    }


def query_violations(panel: dict) -> list[str]:
    """Honesty rules for one panel's queries, whatever the panel type.

    A percentile is shown only alongside a minimum sample count in the same window,
    a duration sum is shown in seconds, and a heatmap reads one le-aggregated
    bucket rate per target.
    """
    violations = []
    for target in panel.get("targets", []):
        expr = target.get("expr", "")
        if "histogram_quantile" in expr and not re.search(
            r"\) and on \([\w, ]+\) sum by \([\w, ]+\) "
            r"\(increase\(\w+_count\{[^}]*\}\[\w+\]\)\) >= [1-9]\d*$",
            expr,
        ):
            violations.append(f"percentile without a sample guard: {expr}")
        if "duration_seconds_sum" in expr and (
            panel.get("fieldConfig", {}).get("defaults", {}).get("unit") != "s"
        ):
            violations.append(f"duration sum not in seconds: {expr}")
        if panel["type"] != "heatmap" or panel["datasource"]["type"] != "prometheus":
            continue
        if target.get("format") != "heatmap" or not re.fullmatch(
            r"sum by \(le\) \((?:rate|increase)\(\w+_bucket\{[^{}]*\}\[[^\]]+\]\)\)",
            expr,
        ):
            violations.append(f"heatmap needs a by (le) bucket rate: {expr}")
        if "_seconds_bucket" in expr and (
            panel.get("options", {}).get("yAxis", {}).get("unit") != "s"
        ):
            violations.append(f"duration heatmap not in seconds: {expr}")
    return violations


class MonitoringContractTests(unittest.TestCase):
    """Validate the repository contract without a cluster or secret access."""

    def setUp(self) -> None:
        """Read only monitoring definitions."""
        self.dashboards = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((CONFIGS / "dashboards").glob("*.json"))
        ]

    def test_exact_dashboard_schemas_and_nonoverlapping_layouts(self) -> None:
        """Reject obsolete dashboards, UID collisions and invalid panel layouts."""
        validator = dashboard_validator()
        self.assertEqual(len(self.dashboards), len(EXPECTED))
        self.assertEqual(
            {item["uid"]: item["title"] for item in self.dashboards}, EXPECTED
        )
        for dashboard in self.dashboards:
            with self.subTest(dashboard=dashboard["uid"]):
                validator.validate(dashboard)
                ids = [panel["id"] for panel in iter_panels(dashboard)]
                self.assertEqual(len(ids), len(set(ids)))
                self.assert_no_overlap(dashboard["panels"])
                for row in dashboard["panels"]:
                    if row["type"] == "row" and row["collapsed"]:
                        self.assert_no_overlap(row["panels"])
                        for panel in row["panels"]:
                            self.assertGreater(
                                panel["gridPos"]["y"], row["gridPos"]["y"]
                            )

    def test_schema_rejects_text_beta_and_undescribed_panels(self) -> None:
        """Explain panels with descriptions; rows only group them."""
        validator = dashboard_validator()
        dashboard = self.dashboards[0]
        panel = next(item for item in dashboard["panels"] if item["type"] != "row")
        row = {
            "id": 1000,
            "type": "row",
            "title": "Logs",
            "collapsed": True,
            "gridPos": {"x": 0, "y": 1000, "w": 24, "h": 1},
            "panels": [panel],
        }
        self.assertTrue(validator.is_valid({**dashboard, "panels": [row]}))
        undescribed = {k: v for k, v in panel.items() if k != "description"}
        for panels in (
            [{**panel, "type": "text", "options": {"content": "Read me"}}],
            [{**panel, "type": "trend"}],
            [{**panel, "type": "datagrid"}],
            [{**panel, "description": " "}],
            [undescribed],
            [{**row, "panels": [undescribed]}],
            [{**row, "panels": [row]}],
            [{**row, "collapsed": False}],
            [{**row, "targets": panel["targets"]}],
            [{**panel, "panels": []}],
        ):
            with self.subTest(panels=[item["type"] for item in panels]):
                self.assertFalse(validator.is_valid({**dashboard, "panels": panels}))

    def assert_no_overlap(self, panels: list[dict]) -> None:
        """Panels sharing one grid must not cover the same cell."""
        occupied = set()
        for panel in panels:
            grid = panel["gridPos"]
            self.assertLessEqual(grid["x"] + grid["w"], 24)
            cells = {
                (x, y)
                for x in range(grid["x"], grid["x"] + grid["w"])
                for y in range(grid["y"], grid["y"] + grid["h"])
            }
            self.assertFalse(occupied & cells, panel["title"])
            occupied |= cells

    def test_dashboards_are_tagged_linked_and_described(self) -> None:
        """Each dashboard explains itself through descriptions and its runbook section."""
        anchors = runbook_anchors()
        for dashboard in self.dashboards:
            with self.subTest(dashboard=dashboard["uid"]):
                tags = set(dashboard["tags"])
                self.assertIn(NAVIGATION_TAG, tags)
                self.assertEqual(tags & APP_TAGS, {dashboard["uid"].split("-")[0]})
                links = {link["type"]: link for link in dashboard["links"]}
                self.assertEqual(len(links), len(dashboard["links"]))
                self.assertEqual(set(links), {"dashboards", "link"})
                self.assertEqual(links["dashboards"]["tags"], [NAVIGATION_TAG])
                for option in ("asDropdown", "keepTime", "includeVars"):
                    self.assertIs(links["dashboards"][option], True)
                runbook = links["link"]
                page, _, anchor = runbook["url"].partition("#")
                self.assertEqual(page, RUNBOOK_URL)
                self.assertIn(anchor, anchors)
                self.assertIs(runbook["targetBlank"], True)
                self.assertEqual(runbook["icon"], "doc")

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
            for panel in iter_panels(dashboard):
                if panel.get("datasource", {}).get("type") == POSTGRES:
                    continue
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
            for panel in iter_panels(dashboard):
                self.assertEqual(query_violations(panel), [], panel["title"])

    def test_query_rules_reach_nested_and_new_panel_types(self) -> None:
        """The rules hold in collapsed rows and for panel types not used yet."""
        prometheus = {"type": "prometheus", "uid": "${metrics}"}
        bucket = 'x_duration_seconds_bucket{namespace="ankilabs"}'
        heatmap = {
            "type": "heatmap",
            "title": "Latency distribution",
            "datasource": prometheus,
            "options": {"yAxis": {"unit": "s"}},
            "targets": [
                {
                    "refId": "A",
                    "expr": f"sum by (le) (rate({bucket}[$__rate_interval]))",
                    "format": "heatmap",
                }
            ],
        }
        stat = {
            "type": "stat",
            "title": "Mean latency",
            "datasource": prometheus,
            "fieldConfig": {"defaults": {"unit": "ms"}},
            "targets": [{"refId": "A", "expr": "sum(x_duration_seconds_sum)"}],
        }
        gauge = {
            "type": "gauge",
            "title": "p95",
            "datasource": prometheus,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"histogram_quantile(0.95, sum by (le) ({bucket}))",
                }
            ],
        }
        row = {"type": "row", "collapsed": True, "panels": [heatmap, stat, gauge]}
        nested = list(iter_panels({"panels": [row]}))
        self.assertEqual(nested, [row, heatmap, stat, gauge])
        self.assertEqual(query_violations(heatmap), [])
        self.assertEqual(len(query_violations(stat)), 1)
        self.assertEqual(len(query_violations(gauge)), 1)
        for change in (
            {"format": "time_series"},
            {"expr": f"sum by (le, pod) (rate({bucket}[5m]))"},
            {"expr": f"sum by (le) ({bucket})"},
            {"expr": "sum by (le) (rate(x_duration_seconds_count[5m]))"},
        ):
            with self.subTest(change=change):
                broken = {**heatmap, "targets": [{**heatmap["targets"][0], **change}]}
                self.assertTrue(query_violations(broken))
        self.assertTrue(query_violations({**heatmap, "options": {}}))

    def test_litellm_panels_read_only_the_grafana_views(self) -> None:
        """Grafana's LiteLLM login sees views without key hashes, prompts or answers."""
        queries = sql_targets(self.dashboards)
        self.assertTrue(queries)
        for query in queries:
            with self.subTest(query=query):
                relations = re.findall(r"\bFROM\s+([\w.]+)", query)
                self.assertTrue(relations)
                self.assertLessEqual(
                    set(relations), {"grafana.usage_codes", "grafana.spend_logs"}
                )
                self.assertNotRegex(query, LITELLM_PRIVATE)
        views = LITELLM_VIEWS.read_text(encoding="utf-8")
        statements = re.sub(r"--.*", "", views)
        # The key hash is only a join key inside the views, never a column.
        for predicate in ("s.api_key = t.token", "t.token = s.api_key"):
            self.assertIn(predicate, statements)
            statements = statements.replace(predicate, "")
        self.assertNotRegex(statements, LITELLM_PRIVATE)
        grants = re.findall(r"^GRANT .*$", views, re.MULTILINE)
        self.assertEqual(
            grants,
            [
                'GRANT USAGE ON SCHEMA grafana TO :"grafana_role";',
                'GRANT SELECT ON grafana.usage_codes, grafana.spend_logs TO :"grafana_role";',
            ],
        )

    def test_scraped_application_pods_admit_prometheus(self) -> None:
        """Every AnkiLabs PodMonitor target's NetworkPolicy admits the monitoring namespace."""
        apps = set()
        for path in CONFIGS.glob("*podmonitor*.yaml"):
            for monitor in yaml.safe_load_all(path.read_text(encoding="utf-8")):
                spec = monitor["spec"]
                if spec["namespaceSelector"]["matchNames"] != ["ankilabs"]:
                    continue
                selector = spec["selector"]
                if "matchLabels" in selector:
                    apps.add(selector["matchLabels"]["app.kubernetes.io/name"])
                for expression in selector.get("matchExpressions", []):
                    apps.update(expression["values"])
        policies = {
            policy["spec"]["podSelector"]["matchLabels"][
                "app.kubernetes.io/name"
            ]: policy
            for path in (K8S / "apps/ankilabs").glob("*/networkpolicy.yaml")
            for policy in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        }
        self.assertIn("ai-card-actions", apps)
        monitoring = {"kubernetes.io/metadata.name": "monitoring"}
        for app in apps:
            with self.subTest(app=app):
                sources = [
                    source
                    for rule in policies[app]["spec"]["ingress"]
                    for source in rule["from"]
                ]
                self.assertTrue(
                    any(
                        source.get("namespaceSelector", {}).get("matchLabels")
                        == monitoring
                        and source.get("podSelector", {})
                        .get("matchLabels", {})
                        .get("app.kubernetes.io/name", "prometheus")
                        == "prometheus"
                        for source in sources
                    )
                )

    def test_alert_links_routes_and_namespace_matcher_strategy(self) -> None:
        """Application/database alerts must reach the existing POD Discord receiver."""
        rules = yaml.safe_load((CONFIGS / "alerts.yaml").read_text(encoding="utf-8"))
        anchors = runbook_anchors()
        for group in rules["spec"]["groups"]:
            for rule in group["rules"]:
                annotations = rule["annotations"]
                self.assertIn("/d/", annotations["dashboard_url"])
                page, _, anchor = annotations["runbook_url"].partition("#")
                self.assertEqual(page, RUNBOOK_URL)
                self.assertIn(anchor, anchors)
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

    def test_prometheus_and_alertmanager_state_is_persistent(self) -> None:
        """History and silences survive restarts; retentionSize caps the 10Gi claim."""
        values = yaml.safe_load(
            (MONITORING / "controllers/kube-prometheus-stack/release.yaml").read_text(
                encoding="utf-8"
            )
        )["spec"]["values"]
        prometheus = values["prometheus"]["prometheusSpec"]
        alertmanager = values["alertmanager"]["alertmanagerSpec"]
        for claim in (
            prometheus["storageSpec"]["volumeClaimTemplate"]["spec"],
            alertmanager["storage"]["volumeClaimTemplate"]["spec"],
        ):
            self.assertEqual(claim["accessModes"], ["ReadWriteOnce"])
            self.assertTrue(claim["resources"]["requests"]["storage"])
        self.assertEqual(prometheus["retention"], "7d")
        self.assertEqual(prometheus["retentionSize"], "8GB")
        self.assertEqual(
            prometheus["storageSpec"]["volumeClaimTemplate"]["spec"]["resources"][
                "requests"
            ]["storage"],
            "10Gi",
        )

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
