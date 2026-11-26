"""Per-volume usage of openebs-hostpath claims: the node-exporter sidecar and its queries."""

import json
import os
import re
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import yaml
from dashboard_panels import iter_panels
from test_rules import run_promtool

MONITORING = Path(__file__).resolve().parents[1]
RELEASE = MONITORING / "controllers/kube-prometheus-stack/release.yaml"
DASHBOARDS = MONITORING / "configs/dashboards"
VOLUME_ROOT = "/var/openebs/local"
USED = "openebs_hostpath_volume_used_bytes"
SAMPLE = re.compile(r'^(\w+)(?:\{persistentvolume="([^"]+)"\})? (\d+)$')


def node_exporter_values() -> dict:
    """The prometheus-node-exporter subchart values of the release."""
    release = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    return release["spec"]["values"]["prometheus-node-exporter"]


def kubernetes_expand(text: str, env: dict[str, str]) -> str:
    """Expand container args as the kubelet does: $$ is $, $(NAME) a defined variable."""

    def replace(match: re.Match) -> str:
        if match.group(0) == "$$":
            return "$"
        return env.get(match.group(1), match.group(0))

    return re.sub(r"\$\$|\$\((\w+)\)", replace, text)


def prometheus_exprs() -> list[tuple[str, str]]:
    """Every Prometheus dashboard query with its dashboard UID."""
    exprs = []
    for path in sorted(DASHBOARDS.glob("*.json")):
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        for panel in iter_panels(dashboard):
            if panel.get("datasource", {}).get("type") != "prometheus":
                continue
            exprs.extend((dashboard["uid"], t["expr"]) for t in panel["targets"])
    return exprs


class VolumeUsageSidecarTests(unittest.TestCase):
    """The sidecar reads every volume on the node, so its privileges stay pinned."""

    def setUp(self) -> None:
        """Read only the checked-in release values."""
        self.values = node_exporter_values()
        sidecars = self.values["sidecars"]
        self.assertEqual([sidecar["name"] for sidecar in sidecars], ["volume-usage"])
        self.sidecar = sidecars[0]

    def test_sidecar_reads_volumes_with_dac_read_search_only(self) -> None:
        """Root may only bypass read permissions, on read-only mounts."""
        context = self.sidecar["securityContext"]
        self.assertEqual(
            context["capabilities"], {"drop": ["ALL"], "add": ["DAC_READ_SEARCH"]}
        )
        self.assertIs(context["allowPrivilegeEscalation"], False)
        self.assertIs(context["readOnlyRootFilesystem"], True)
        self.assertIs(context.get("privileged", False), False)
        self.assertEqual(context["runAsUser"], 0)
        self.assertEqual(
            self.values["sidecarHostVolumeMounts"],
            [
                {
                    "name": "openebs-local",
                    "hostPath": VOLUME_ROOT,
                    "mountPath": VOLUME_ROOT,
                    "readOnly": True,
                }
            ],
        )
        # Every mount comes from the chart's sidecar mounts above.
        self.assertNotIn("volumeMounts", self.sidecar)
        self.assertRegex(self.sidecar["image"], r":[\w.-]+@sha256:[a-f0-9]{64}$")
        self.assertTrue(self.sidecar["resources"]["requests"])
        self.assertTrue(self.sidecar["resources"]["limits"]["memory"])

    def test_node_exporter_reads_the_sidecar_textfile(self) -> None:
        """Share one directory and keep the chart's filesystem excludes."""
        (textfile,) = self.values["sidecarVolumeMount"]
        env = {item["name"]: item["value"] for item in self.sidecar["env"]}
        self.assertEqual(env["TEXTFILE_DIR"], textfile["mountPath"])
        self.assertEqual(env["VOLUME_ROOT"], VOLUME_ROOT)
        arguments = self.values["extraArgs"]
        self.assertIn(
            f"--collector.textfile.directory={textfile['mountPath']}", arguments
        )
        # extraArgs replaces the kube-prometheus-stack defaults instead of adding to them.
        for flag in (
            "--collector.filesystem.mount-points-exclude=",
            "--collector.filesystem.fs-types-exclude=",
        ):
            self.assertTrue(any(arg.startswith(flag) for arg in arguments), flag)

    def test_scan_writes_valid_prometheus_textfile(self) -> None:
        """Run the checked-in script once over a synthetic volume tree."""
        self.assertEqual(self.sidecar["command"], ["sh", "-c"])
        with tempfile.TemporaryDirectory() as directory:
            root, output = Path(directory, "volumes"), Path(directory, "textfile")
            output.mkdir()
            (root / "pvc-aaaa-1111").mkdir(parents=True)
            (root / "pvc-aaaa-1111/data").write_bytes(b"x" * 10_000)
            (root / "pvc-bbbb-2222/locked").mkdir(parents=True)
            (root / "pvc-Not_A_Volume").mkdir()
            (root / "lost+found").mkdir()
            locked = root / "pvc-bbbb-2222/locked"
            locked.chmod(0)
            try:
                text = self.run_scan(root, output)
            finally:
                locked.chmod(0o700)
            self.assertEqual(
                [path.name for path in output.iterdir()], ["openebs-hostpath.prom"]
            )
        run_promtool(["check", "metrics"], stdin=text)
        samples = [
            SAMPLE.fullmatch(line).groups()
            for line in text.splitlines()
            if not line.startswith("#")
        ]
        used = {volume: int(value) for name, volume, value in samples if name == USED}
        self.assertEqual(set(used), {"pvc-aaaa-1111", "pvc-bbbb-2222"})
        self.assertGreaterEqual(used["pvc-aaaa-1111"], 10_000)
        self.assertEqual(used["pvc-aaaa-1111"] % 1024, 0)
        scan = {name: int(value) for name, volume, value in samples if volume is None}
        # Root reads the locked directory, like the sidecar with DAC_READ_SEARCH.
        expected_errors = 0 if os.geteuid() == 0 else 1
        self.assertEqual(scan["openebs_hostpath_volume_scan_errors"], expected_errors)
        self.assertGreaterEqual(
            scan["openebs_hostpath_volume_scan_duration_seconds"], 0
        )
        self.assertLessEqual(
            abs(scan["openebs_hostpath_volume_scan_timestamp_seconds"] - time.time()),
            60,
        )

    def run_scan(self, root: Path, output: Path) -> str:
        """Start the sidecar script, wait for its first file, then stop it."""
        result = output / "openebs-hostpath.prom"
        container_env = {item["name"]: item["value"] for item in self.sidecar["env"]}
        env = {
            **os.environ,
            **container_env,
            "VOLUME_ROOT": str(root),
            "TEXTFILE_DIR": str(output),
        }
        script = kubernetes_expand(self.sidecar["args"][0], container_env)
        with subprocess.Popen(
            ["sh", "-c", script],
            env=env,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        ) as process:
            try:
                deadline = time.monotonic() + 30
                while not result.exists() and time.monotonic() < deadline:
                    time.sleep(0.2)
            finally:
                # The session also holds the script's background sleep.
                os.killpg(process.pid, signal.SIGTERM)
                _, errors = process.communicate(timeout=10)
        self.assertTrue(result.exists(), "the scan wrote no textfile within 30s")
        # Only du may complain (about the locked directory); anything else is a script bug.
        for line in errors.splitlines():
            self.assertTrue(line.startswith("du: "), line)
        return result.read_text(encoding="utf-8")


class VolumeUsageQueryTests(unittest.TestCase):
    """Dashboards read the sidecar's per-volume usage, joined to claims."""

    def test_dashboards_do_not_read_kubelet_volume_stats(self) -> None:
        """kubelet volume stats are meaningless on openebs-hostpath.

        Its volumes are directories on the node filesystem, so kubelet reports that
        whole filesystem as every claim's used bytes and capacity.
        """
        for uid, expr in prometheus_exprs():
            with self.subTest(dashboard=uid):
                self.assertNotIn("kubelet_volume_stats_", expr)

    def test_application_volume_queries_join_their_own_claims(self) -> None:
        """The node-level metric reaches an app dashboard only through its claims."""
        found = set()
        for uid, expr in prometheus_exprs():
            if USED not in expr or not uid.startswith(("ankilabs-", "quizlabs-")):
                continue
            found.add(uid)
            namespace = uid.split("-")[0]
            with self.subTest(dashboard=uid, expr=expr):
                self.assertNotIn(USED + "{", expr)
                self.assertIn(
                    "* on (persistentvolume) group_left (namespace, persistentvolumeclaim)",
                    expr,
                )
                self.assertIn(
                    f'kube_persistentvolumeclaim_info{{namespace="{namespace}"', expr
                )
        self.assertEqual(found, {"ankilabs-search-postgres", "quizlabs-overview"})


if __name__ == "__main__":
    unittest.main()
