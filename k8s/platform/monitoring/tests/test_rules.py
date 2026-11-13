"""Check and evaluate the actual PrometheusRule expressions with promtool."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

MONITORING = Path(__file__).resolve().parents[1]


def run_promtool(arguments: list[str]) -> None:
    """Fail explicitly when Prometheus tooling is missing or rejects an input."""
    binary = shutil.which(os.environ.get("PROMTOOL_BIN", "promtool"))
    if binary is None:
        raise RuntimeError(
            "promtool is missing; install Prometheus (brew install prometheus)."
        )
    subprocess.run([binary, *arguments], check=True, timeout=60)


def dashboard_queries() -> list[dict]:
    """Convert dashboard PromQL into temporary recording rules for syntax checking."""
    queries = []
    for path in (MONITORING / "configs/dashboards").glob("*.json"):
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        for panel in dashboard["panels"]:
            if panel.get("datasource", {}).get("type") != "prometheus":
                continue
            for target in panel["targets"]:
                queries.append(
                    {
                        "record": f"homelab_validation:panel_{len(queries)}",
                        "expr": target["expr"].replace("$__rate_interval", "5m"),
                    }
                )
    return queries


class PrometheusRuleTests(unittest.TestCase):
    """Use Prometheus' own evaluator for low-traffic and missing-data regressions."""

    def test_rule_syntax_and_behavior(self) -> None:
        """Render only rule groups into temporary local promtool inputs."""
        resource = yaml.safe_load(
            (MONITORING / "configs/alerts.yaml").read_text(encoding="utf-8")
        )
        groups = resource["spec"]["groups"]
        annotations = {
            rule["alert"]: rule["annotations"]
            for group in groups
            for rule in group["rules"]
        }
        cases = yaml.safe_load(
            (Path(__file__).parent / "rule-cases.yaml").read_text(encoding="utf-8")
        )
        for test in cases["tests"]:
            for assertion in test["alert_rule_test"]:
                for expected in assertion["exp_alerts"]:
                    labels = expected["exp_labels"]
                    expected["exp_annotations"] = {
                        name: re.sub(
                            r"\{\{ \$labels\.(\w+) \}\}",
                            lambda match, labels=labels: labels.get(match.group(1), ""),
                            value,
                        )
                        for name, value in annotations[assertion["alertname"]].items()
                    }
        with tempfile.TemporaryDirectory() as directory:
            rule_path = Path(directory) / "rules.yaml"
            rule_path.write_text(yaml.safe_dump({"groups": groups}), encoding="utf-8")
            cases["rule_files"] = [str(rule_path)]
            case_path = Path(directory) / "cases.yaml"
            case_path.write_text(yaml.safe_dump(cases), encoding="utf-8")
            run_promtool(["check", "rules", str(rule_path)])
            run_promtool(["test", "rules", str(case_path)])

    def test_dashboard_promql_syntax(self) -> None:
        """Parse all dashboard metric expressions with the same Prometheus tooling."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dashboard-queries.yaml"
            path.write_text(
                yaml.safe_dump(
                    {"groups": [{"name": "dashboards", "rules": dashboard_queries()}]}
                ),
                encoding="utf-8",
            )
            run_promtool(["check", "rules", str(path)])


if __name__ == "__main__":
    unittest.main()
