"""Render the Discord notification templates with Alertmanager's own engine."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import yaml

MONITORING = Path(__file__).resolve().parents[1]
CONFIGS = MONITORING / "configs"
APPS = MONITORING.parents[1] / "apps"
RUNBOOK = "https://github.com/liav-hasson/homelab/blob/main/k8s/platform/monitoring/runbook.md"
GRAFANA = "https://grafana.ankilabs.org/d/"
GENERATOR_URL = "http://prometheus.monitoring:9090/graph?g0.expr=internal"
# Discord embed limits, in characters.
TITLE_LIMIT = 256
DESCRIPTION_LIMIT = 4096
# Pictographs, dingbats, misc symbols/arrows, variation selector 16 and keycap.
EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u20e3]")
# Alert times in UTC; Alertmanager's zero time marks a firing alert's end.
START = datetime(2026, 11, 26, 18, 49, 52, 864000)
ZERO_TIME = "0001-01-01T00:00:00Z"
ROUTE_MAPPING = re.compile(
    r'"route", "([^"$]+)", "envoy_cluster_name", "httproute/([^/]+)/([^/]+)/rule/(\d+)"'
)


def amtool_render(template: str, data: dict) -> str:
    """Render one template with amtool; fail explicitly when it is missing."""
    binary = shutil.which(os.environ.get("AMTOOL_BIN", "amtool"))
    if binary is None:
        raise RuntimeError(
            "amtool is missing; install Alertmanager 0.28.1 (brew install alertmanager)."
        )
    with tempfile.TemporaryDirectory() as directory:
        glob = Path(directory) / "empty.tmpl"
        glob.write_text("", encoding="utf-8")
        data_path = Path(directory) / "data.json"
        data_path.write_text(json.dumps(data), encoding="utf-8")
        result = subprocess.run(
            [
                binary,
                "template",
                "render",
                f"--template.glob={glob}",
                f"--template.data={data_path}",
                f"--template.text={template}",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    return result.stdout


def alertmanager_config() -> dict:
    """The AlertmanagerConfig spec."""
    return yaml.safe_load(
        (CONFIGS / "alertmanager-config.yaml").read_text(encoding="utf-8")
    )["spec"]


def discord_configs() -> list[dict]:
    """Every Discord receiver configuration."""
    return [
        config
        for receiver in alertmanager_config()["receivers"]
        for config in receiver.get("discordConfigs", [])
    ]


def rules() -> dict[str, dict]:
    """Alert rules by name."""
    groups = yaml.safe_load((CONFIGS / "alerts.yaml").read_text(encoding="utf-8"))
    return {
        rule["alert"]: rule
        for group in groups["spec"]["groups"]
        for rule in group["rules"]
    }


def alert(name: str, subject: str, lasted: timedelta = timedelta(0), **labels) -> dict:
    """One alert as Alertmanager hands it to a template, with real rule annotations.

    A nonzero ``lasted`` makes it resolved after that long.
    """
    rule = rules()[name]
    annotations = {**rule["annotations"], "subject": subject}
    if "{{" in annotations["dashboard_url"]:
        annotations["dashboard_url"] = GRAFANA + "platform-delivery-edge"
    return {
        "status": "resolved" if lasted else "firing",
        "labels": {"alertname": name, **rule["labels"], **labels},
        "annotations": annotations,
        "startsAt": f"{START.isoformat()}Z",
        "endsAt": f"{(START + lasted).isoformat()}Z" if lasted else ZERO_TIME,
        "generatorURL": GENERATOR_URL,
    }


def common(maps: list[dict]) -> dict:
    """Key/value pairs shared by every map, as Alertmanager computes them."""
    return {
        key: value
        for key, value in maps[0].items()
        if all(other.get(key) == value for other in maps[1:])
    }


def notification(alerts: list[dict]) -> dict:
    """A notification group in Alertmanager's template data layout."""
    firing = any(item["status"] == "firing" for item in alerts)
    common_labels = common([item["labels"] for item in alerts])
    return {
        "receiver": "pods-discord",
        "status": "firing" if firing else "resolved",
        "alerts": alerts,
        "groupLabels": {"alertname": common_labels["alertname"]},
        "commonLabels": common_labels,
        "commonAnnotations": common([item["annotations"] for item in alerts]),
        "externalURL": "http://alertmanager.monitoring:9093",
    }


def render(alerts: list[dict]) -> tuple[str, str]:
    """Rendered title and message of the checked-in template."""
    config = discord_configs()[0]
    data = notification(alerts)
    return amtool_render(config["title"], data), amtool_render(config["message"], data)


def crash_loop(index: int, lasted: timedelta = timedelta(0)) -> dict:
    """One crash-looping pod in the ankilabs namespace."""
    return alert(
        "PodCrashLoopBackOff",
        f"ankilabs/api-gateway-{index} (api-gateway)",
        lasted,
        namespace="ankilabs",
        pod=f"api-gateway-{index}",
    )


class DiscordTemplateTests(unittest.TestCase):
    """Short, grouped notifications that stay within Discord's embed limits."""

    def assert_compact(self, title: str, message: str) -> None:
        """No filler, internal URLs or emoji; within Discord's limits."""
        for text in (title, message):
            self.assertNotIn("n/a", text)
            self.assertNotIn(GENERATOR_URL, text)
            self.assertIsNone(EMOJI.search(text), text)
        self.assertLessEqual(len(title), TITLE_LIMIT)
        self.assertLessEqual(len(message), DESCRIPTION_LIMIT)

    def test_receivers_share_one_template_and_their_webhooks(self) -> None:
        """Both receivers render identically and keep their own webhook Secret key."""
        configs = discord_configs()
        self.assertEqual(
            [config["apiURL"] for config in configs],
            [
                {"name": "monitoring-discord-webhooks", "key": "nodes-webhook-url"},
                {"name": "monitoring-discord-webhooks", "key": "pods-webhook-url"},
            ],
        )
        for config in configs:
            self.assertTrue(config["sendResolved"])
            self.assertEqual(config["title"], configs[0]["title"])
            self.assertEqual(config["message"], configs[0]["message"])

    def test_related_alerts_share_one_notification(self) -> None:
        """One message per alert and namespace, not one per pod or instance."""
        route = alertmanager_config()["route"]
        self.assertEqual(route["groupBy"], ["alertname", "namespace"])
        self.assertEqual(route["repeatInterval"], "4h")

    def test_every_rule_carries_the_notification_annotations(self) -> None:
        """A short name and subject, links, and a one-sentence description."""
        for name, rule in rules().items():
            annotations = rule["annotations"]
            self.assertEqual(
                set(annotations),
                {"name", "subject", "description", "dashboard_url", "runbook_url"},
                name,
            )
            self.assertLessEqual(len(annotations["name"]), 40, name)
            self.assertLessEqual(len(annotations["description"]), 120, name)
            self.assertIn(rule["labels"]["severity"], {"warning", "critical"}, name)
            for value in annotations.values():
                self.assertIsNone(EMOJI.search(value), name)

    def test_edge_routes_are_named_after_their_httproute_rules(self) -> None:
        """Each mapped Envoy cluster names the path of the rule at that index."""
        mappings = ROUTE_MAPPING.findall(rules()["EdgeUpstreamFailure"]["expr"])
        self.assertTrue(mappings)
        mapped = set()
        for friendly, namespace, route, index in mappings:
            resource = yaml.safe_load(
                (APPS / namespace / "httproute.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(resource["metadata"]["name"], route)
            matches = resource["spec"]["rules"][int(index)].get("matches", [])
            path = matches[0]["path"]["value"] if matches else "/"
            self.assertTrue(friendly.endswith(f"({path})"), friendly)
            mapped.add((namespace, int(index)))
        for namespace in ("ankilabs", "quizlabs"):
            resource = yaml.safe_load(
                (APPS / namespace / "httproute.yaml").read_text(encoding="utf-8")
            )
            for index in range(len(resource["spec"]["rules"])):
                self.assertIn((namespace, index), mapped)

    def test_single_firing_alert(self) -> None:
        """Name and severity in the title; subject, start time and links below."""
        edge = alert(
            "EdgeUpstreamFailure",
            "AnkiLabs API (/api)",
            namespace="envoy-gateway-system",
        )
        edge["annotations"]["dashboard_url"] = GRAFANA + "ankilabs-service-health"
        title, message = render([edge])
        self.assertEqual(title, "Edge upstream failure · warning")
        self.assertEqual(
            message,
            "AnkiLabs API (/api) · since 18:49 UTC\n"
            f"[Dashboard]({GRAFANA}ankilabs-service-health) · [Runbook]({RUNBOOK}#requests)",
        )
        self.assert_compact(title, message)

    def test_grouped_firing_alerts_are_capped(self) -> None:
        """Ten lines, a remainder count, recovered members and one link line."""
        title, message = render(
            [crash_loop(index) for index in range(12)]
            + [crash_loop(12, timedelta(minutes=7))]
        )
        lines = message.split("\n")
        self.assertEqual(title, "Pod crash-looping · critical")
        self.assertEqual(
            lines[0], "ankilabs/api-gateway-0 (api-gateway) · since 18:49 UTC"
        )
        self.assertEqual(sum("· since" in line for line in lines), 10)
        self.assertEqual(lines[10], "and 2 more")
        self.assertEqual(
            lines[11], "ankilabs/api-gateway-12 (api-gateway) · resolved, lasted 7m 0s"
        )
        self.assertEqual(
            lines[12],
            f"[Dashboard]({GRAFANA}homelab-overview) · [Runbook]({RUNBOOK}#resources)",
        )
        self.assertEqual(len(lines), 13)
        self.assert_compact(title, message)

    def test_resolved_group(self) -> None:
        """Resolved title first, then how long each alert lasted."""
        title, message = render(
            [
                crash_loop(0, timedelta(minutes=12, seconds=5)),
                crash_loop(1, timedelta(hours=1, minutes=2)),
            ]
        )
        self.assertEqual(title, "Resolved · Pod crash-looping")
        self.assertEqual(
            message,
            "ankilabs/api-gateway-0 (api-gateway) · lasted 12m 5s\n"
            "ankilabs/api-gateway-1 (api-gateway) · lasted 1h 2m 0s",
        )
        self.assert_compact(title, message)

    def test_large_groups_stay_within_discord_limits(self) -> None:
        """Long subjects and many alerts never exceed the embed limits."""
        firing = [alert("NodeHighCPU", "x" * 150) for _ in range(40)]
        resolved = [
            alert("NodeHighCPU", "x" * 150, timedelta(days=1)) for _ in range(40)
        ]
        title, message = render(firing + resolved)
        self.assertIn("\nand 30 more\n", message)
        self.assertIn("\nand 30 more resolved\n", message)
        self.assert_compact(title, message)
        title, message = render(resolved)
        self.assertTrue(message.endswith("\nand 30 more"))
        self.assert_compact(title, message)


if __name__ == "__main__":
    unittest.main()
