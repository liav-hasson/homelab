"""Platform - Edge reads only the application routes and names them by HTTPRoute rule."""

import json
import re
import unittest
from pathlib import Path

import yaml
from dashboard_panels import iter_panels

MONITORING = Path(__file__).resolve().parents[1]
K8S = MONITORING.parents[1]
EDGE = MONITORING / "configs/dashboards/platform-delivery-edge.json"
APP_ROUTES = ("ankilabs", "quizlabs")
APP_CLUSTERS = 'envoy_cluster_name=~"httproute/(ankilabs|quizlabs)/.*"'
ENVOY_SELECTOR = re.compile(r'\{namespace="envoy-gateway-system"(?:,[^{}]*)?\}')
CLUSTER = r"httproute/(?P<namespace>\w+)/(?P<name>\w+)/rule/(?P<index>\d+)"
LABEL_REPLACE = re.compile(
    rf'"route", "(?P<label>[^"$]+)", "envoy_cluster_name", "{CLUSTER}"\)'
)
LINE_FORMAT = re.compile(
    rf'eq \.upstream_cluster "{CLUSTER}" }}}}(?P<label>[^{{]+){{{{'
)
# Shared with the alert annotations (homelab#28): an unnamed rule reads "ns/route rule N".
FALLBACK = ('"httproute/([^/]+)/([^/]+)/rule/([0-9]+)"', '"$1/$2 rule $3"')
ACCESS_FILTER = '| upstream_cluster=~"httproute/(ankilabs|quizlabs)/.+" |'
SLOW = re.compile(r'duration_ms >= (\d+) and upstream_cluster (=|!~) "([^"]+)"')
AI_ROUTE = "httproute/ankilabs/ankilabs/rule/0"
SOCKET_IO_ROUTE = "httproute/quizlabs/quizlabs/rule/1"
SLOW_MS = 2000
AI_SLOW_MS = 30000
# Normal AI calls take 10-20 s; the threshold stays well inside the route timeout.
AI_TIMEOUT_HEADROOM = 2


def rule_names() -> dict[tuple[str, str, str], str]:
    """Path prefix of each application HTTPRoute rule, keyed like its Envoy cluster."""
    names = {}
    for app in APP_ROUTES:
        route = yaml.safe_load(
            (K8S / f"apps/{app}/httproute.yaml").read_text(encoding="utf-8")
        )
        meta = route["metadata"]
        for index, rule in enumerate(route["spec"]["rules"]):
            matches = rule.get("matches") or [{"path": {"value": "/"}}]
            names[(meta["namespace"], meta["name"], str(index))] = matches[0]["path"][
                "value"
            ]
    return names


def route_labels(expr: str) -> dict[tuple[str, str, str], str]:
    """Readable name a query gives each Envoy cluster (label_replace or log template)."""
    pattern = LINE_FORMAT if "line_format" in expr else LABEL_REPLACE
    return {
        (match["namespace"], match["name"], match["index"]): match["label"]
        for match in pattern.finditer(expr)
    }


def targets(dashboard: dict) -> list[tuple[dict, str]]:
    """(panel, query) for every panel target."""
    return [
        (panel, target["expr"])
        for panel in iter_panels(dashboard)
        for target in panel.get("targets", [])
    ]


class EdgeDashboardTests(unittest.TestCase):
    """Owner feedback: Grafana's own traffic and raw cluster names hid the useful data."""

    def setUp(self) -> None:
        """Read the edge dashboard."""
        self.dashboard = json.loads(EDGE.read_text(encoding="utf-8"))

    def test_envoy_queries_read_only_application_routes(self) -> None:
        """Every Envoy metric selector and the access-log panel skip other routes."""
        selectors = 0
        for panel, expr in targets(self.dashboard):
            if panel["datasource"]["type"] == "loki":
                if "edge.request.completed" in expr:
                    self.assertIn(ACCESS_FILTER, expr)
                continue
            for selector in ENVOY_SELECTOR.findall(expr):
                selectors += 1
                with self.subTest(panel=panel["title"]):
                    self.assertRegex(
                        selector,
                        rf'{re.escape(APP_CLUSTERS)}|envoy_cluster_name="{CLUSTER}"',
                    )
                    if "=~" not in selector:
                        cluster = re.search(CLUSTER, selector)
                        self.assertIn(cluster["namespace"], APP_ROUTES)
        self.assertTrue(selectors)

    def test_route_names_follow_httproute_rules(self) -> None:
        """Every per-route query maps each rule to "<name> (<path>)", others to a fallback."""
        expected = rule_names()
        mapped = 0
        for panel, expr in targets(self.dashboard):
            names = route_labels(expr)
            if not names:
                continue
            mapped += 1
            with self.subTest(panel=panel["title"]):
                self.assertEqual(set(names), set(expected))
                for rule, label in names.items():
                    self.assertTrue(label.endswith(f"({expected[rule]})"), label)
                for part in FALLBACK:
                    self.assertIn(part, expr)
                if "label_replace" in expr:
                    self.assertIn("{{route}}", json.dumps(panel["targets"]))
        self.assertGreaterEqual(mapped, 5)

    def test_access_log_slow_threshold_fits_each_route(self) -> None:
        """AI calls on AnkiLabs API are slow by nature; Socket.IO shows only errors."""
        access = next(
            expr
            for _, expr in targets(self.dashboard)
            if "edge.request.completed" in expr
        )
        thresholds = {
            operator: (int(milliseconds), selector)
            for milliseconds, operator, selector in SLOW.findall(access)
        }
        self.assertEqual(thresholds["="], (AI_SLOW_MS, AI_ROUTE))
        default, excluded = thresholds["!~"]
        self.assertEqual(default, SLOW_MS)
        for cluster in (AI_ROUTE, SOCKET_IO_ROUTE):
            self.assertRegex(cluster, rf"^(?:{excluded})$")
        for namespace, name, index in set(rule_names()):
            cluster = f"httproute/{namespace}/{name}/rule/{index}"
            if cluster not in (AI_ROUTE, SOCKET_IO_ROUTE):
                self.assertNotRegex(cluster, rf"^(?:{excluded})$")
        route = yaml.safe_load(
            (K8S / "apps/ankilabs/httproute.yaml").read_text(encoding="utf-8")
        )
        timeout = route["spec"]["rules"][0]["timeouts"]["request"]
        self.assertLessEqual(
            AI_SLOW_MS * AI_TIMEOUT_HEADROOM, int(timeout.removesuffix("s")) * 1000
        )

    def test_flux_left_for_the_vendored_dashboards(self) -> None:
        """Flux delivery is on Flux Cluster Stats and Flux Control Plane now."""
        serialized = json.dumps(self.dashboard)
        self.assertNotIn("gotk_", serialized)
        self.assertNotIn("flux-system", serialized)

    def test_envoy_latency_heatmaps_are_in_milliseconds(self) -> None:
        """Envoy upstream time buckets are milliseconds, unlike *_seconds_bucket."""
        heatmaps = [
            panel
            for panel, expr in targets(self.dashboard)
            if "envoy_cluster_upstream_rq_time_bucket" in expr
            and panel["type"] == "heatmap"
        ]
        self.assertTrue(heatmaps)
        for panel in heatmaps:
            self.assertEqual(panel["options"]["yAxis"]["unit"], "ms", panel["title"])


if __name__ == "__main__":
    unittest.main()
