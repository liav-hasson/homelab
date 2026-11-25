"""Render affected local charts and non-secret monitoring provisioning offline."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

MONITORING = Path(__file__).resolve().parents[1]
K8S = MONITORING.parents[1]


class KustomizeSafeLoader(yaml.SafeLoader):
    """Accept bare '=' scalars emitted by Kustomize without relaxing other tags."""


KustomizeSafeLoader.add_constructor(
    "tag:yaml.org,2002:value", KustomizeSafeLoader.construct_scalar
)


def load_kustomize_documents(content: str) -> list[dict]:
    """Decode Kustomize YAML with only its scalar value-tag compatibility fix."""
    loader = KustomizeSafeLoader(content)
    try:
        documents = []
        while loader.check_data():
            documents.append(loader.get_data())
        return documents
    finally:
        loader.dispose()


def run_tool(name: str, arguments: list[str]) -> str:
    """Run a bounded local validator and expose failures without hiding missing tools."""
    binary = shutil.which(os.environ.get(f"{name.upper()}_BIN", name))
    if binary is None:
        raise RuntimeError(f"{name} is missing; install it before render validation.")
    result = subprocess.run(
        [binary, *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


class RenderTests(unittest.TestCase):
    """Use synthetic Cloudflare values; never load Helm valuesFrom secrets."""

    def test_kustomize_loader_accepts_only_scalar_value_tag(self) -> None:
        """Preserve scalar types and reject unsupported or nonscalar tagged values."""
        self.assertEqual(
            load_kustomize_documents("matchType: =\nenabled: true\nreplicas: 2\n"),
            [{"matchType": "=", "enabled": True, "replicas": 2}],
        )
        for content in ("value: !unsupported fixture\n", "value: !!value [fixture]\n"):
            with (
                self.subTest(content=content),
                self.assertRaises(yaml.constructor.ConstructorError),
            ):
                load_kustomize_documents(content)
        with self.assertRaises(yaml.constructor.ConstructorError):
            yaml.safe_load("matchType: =\n")

    def test_local_helm_charts_lint_and_render(self) -> None:
        """Check selectors, resource declarations and exporter isolation after rendering."""
        postgres_release, llm_proxy_release = (
            yaml.safe_load(
                (K8S / f"apps/ankilabs/{name}/release.yaml").read_text(encoding="utf-8")
            )
            for name in ("postgres", "llm-proxy")
        )
        charts = [
            (
                "postgres",
                "ankilabs",
                K8S / "apps/ankilabs/charts/postgres",
                postgres_release["spec"]["values"],
            ),
            (
                "llm-proxy",
                "ankilabs",
                K8S / "apps/ankilabs/charts/llm-proxy",
                llm_proxy_release["spec"]["values"],
            ),
            ("platform", "platform", K8S / "platform/envoy", {}),
            (
                "cloudflare-tunnel",
                "cloudflare",
                K8S / "platform/cloudflare",
                {
                    "secrets": {
                        "cloudflare": {
                            "account": "synthetic-validation-only",
                            "tunnelId": "synthetic-validation-only",
                            "secret": "synthetic-validation-only",
                        }
                    }
                },
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for name, namespace, chart, values in charts:
                with self.subTest(chart=name):
                    values_path = Path(directory) / f"{name}.yaml"
                    values_path.write_text(yaml.safe_dump(values), encoding="utf-8")
                    flags = ["--namespace", namespace, "--values", str(values_path)]
                    run_tool("helm", ["lint", str(chart), *flags])
                    output = run_tool("helm", ["template", name, str(chart), *flags])
                    resources = list(yaml.safe_load_all(output))
                    self._assert_workloads(resources)
                    if name == "postgres":
                        self._assert_exporter_secret(resources)
                    if name == "llm-proxy":
                        self._assert_grafana_views_hook(resources)

    def _assert_workloads(self, resources: list[dict]) -> None:
        for resource in resources:
            if resource["kind"] not in ("Deployment", "StatefulSet"):
                continue
            spec = resource["spec"]
            labels = spec["template"]["metadata"]["labels"]
            for key, value in spec["selector"]["matchLabels"].items():
                self.assertEqual(labels[key], value)
            for container in spec["template"]["spec"]["containers"]:
                self.assertTrue(container["resources"]["requests"])
                self.assertTrue(container["resources"]["limits"])

    def _assert_exporter_secret(self, resources: list[dict]) -> None:
        exporter = next(
            item
            for item in resources
            if item["kind"] == "Deployment"
            and item["metadata"]["name"] == "postgres-exporter"
        )
        container = exporter["spec"]["template"]["spec"]["containers"][0]
        password = next(
            env for env in container["env"] if env["name"] == "DATA_SOURCE_PASS"
        )
        self.assertEqual(
            password["valueFrom"]["secretKeyRef"],
            {"name": "postgres-monitoring", "key": "password"},
        )

    def _assert_grafana_views_hook(self, resources: list[dict]) -> None:
        jobs = {
            item["metadata"]["name"]: item
            for item in resources
            if item["kind"] == "Job"
        }
        bootstrap, views = (
            jobs["llm-proxy-db-bootstrap"],
            jobs["llm-proxy-grafana-views"],
        )
        self.assertEqual(
            bootstrap["metadata"]["annotations"]["helm.sh/hook"],
            "pre-install,pre-upgrade",
        )
        self.assertIn(
            "DROP VIEW IF EXISTS grafana.usage_codes, grafana.spend_logs;",
            bootstrap["spec"]["template"]["spec"]["containers"][0]["command"][2],
        )
        # After the proxy (and its migrations) is ready; a failure must not roll the proxy back.
        self.assertEqual(
            views["metadata"]["annotations"]["helm.sh/hook"],
            "post-install,post-upgrade",
        )
        script = views["spec"]["template"]["spec"]["containers"][0]["command"][2]
        sql = (
            K8S / "apps/ankilabs/charts/llm-proxy/files/grafana-views.sql"
        ).read_text(encoding="utf-8")
        self.assertIn(sql.strip(), script)
        self.assertTrue(script.startswith("if ! psql "))
        self.assertEqual(
            views["spec"]["template"]["metadata"]["labels"]["app.kubernetes.io/name"],
            bootstrap["spec"]["template"]["metadata"]["labels"][
                "app.kubernetes.io/name"
            ],
        )

    def test_monitoring_kustomize_build(self) -> None:
        """Resolve seven dashboards into one ConfigMap per Grafana folder, without secrets."""
        output = run_tool("kustomize", ["build", str(MONITORING / "configs")])
        resources = load_kustomize_documents(output)
        dashboards = {
            item["metadata"]["annotations"]["grafana_folder"]: set(item["data"])
            for item in resources
            if item["kind"] == "ConfigMap"
            and item["metadata"].get("labels", {}).get("grafana_dashboard") == "1"
        }
        self.assertEqual(
            dashboards,
            {
                "AnkiLabs": {
                    "ankilabs-service-health.json",
                    "ankilabs-search-postgres.json",
                    "ankilabs-ai.json",
                },
                "QuizLabs": {"quizlabs-overview.json"},
                "Platform": {
                    "homelab-overview.json",
                    "platform-delivery-edge.json",
                    "platform-storage.json",
                },
            },
        )
        self.assertFalse(any(item["kind"] == "Secret" for item in resources))


if __name__ == "__main__":
    unittest.main()
