"""Vendored upstream dashboards: provisioned and valid, exempt from homelab style rules."""

import json
import re
import tempfile
import unittest
from pathlib import Path

import yaml
from dashboard_panels import iter_panels
from test_rules import run_promtool

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
DASHBOARDS = CONFIGS / "dashboards"
VENDOR = DASHBOARDS / "vendor"
# uid -> title of each upstream dashboard copied unmodified into dashboards/vendor/.
VENDORED = {
    "flux-cluster": "Flux Cluster Stats",
    "flux-control-plane": "Flux Control Plane",
}
VENDOR_FOLDER = "Platform"
COMMIT = re.compile(r"flux2-monitoring-example@([0-9a-f]{40})|Commit: `([0-9a-f]{40})`")


def load(path: Path) -> dict:
    """Parse one dashboard file."""
    return json.loads(path.read_text(encoding="utf-8"))


def promql(dashboard: dict) -> list[str]:
    """Every metric query, with Grafana range variables made parseable."""
    return [
        target["expr"]
        .replace("$__rate_interval", "5m")
        .replace("$__interval", "30m")
        .replace("$__range", "6h")
        for panel in iter_panels(dashboard)
        for target in panel.get("targets", [])
        if target.get("expr")
    ]


class VendoredDashboardTests(unittest.TestCase):
    """Upstream layout stays as-is; provisioning, identity and PromQL are still checked."""

    def setUp(self) -> None:
        """Read the vendored files by their file-name uid."""
        self.vendored = {path.stem: load(path) for path in VENDOR.glob("*.json")}

    def test_files_are_named_by_uid_and_uids_stay_unique(self) -> None:
        """Each file is its upstream uid; none collides with a homelab dashboard."""
        self.assertEqual(
            {uid: item["title"] for uid, item in self.vendored.items()}, VENDORED
        )
        for uid, dashboard in self.vendored.items():
            self.assertEqual(dashboard["uid"], uid)
        own = {load(path)["uid"] for path in DASHBOARDS.glob("*.json")}
        self.assertFalse(own & set(VENDORED))

    def test_provisioned_once_in_their_folder(self) -> None:
        """The vendored files ride in the Platform folder's single ConfigMap."""
        config = yaml.safe_load(
            (CONFIGS / "kustomization.yaml").read_text(encoding="utf-8")
        )
        placed = {
            path: generator["options"]["annotations"]["grafana_folder"]
            for generator in config["configMapGenerator"]
            for path in generator["files"]
            if path.startswith("dashboards/vendor/")
        }
        self.assertEqual(
            placed,
            {f"dashboards/vendor/{uid}.json": VENDOR_FOLDER for uid in VENDORED},
        )

    def test_pinned_commit_is_recorded_consistently(self) -> None:
        """The kustomization comment and the vendor README name the same commit."""
        commits = [
            {
                "".join(match)
                for match in COMMIT.findall(path.read_text(encoding="utf-8"))
            }
            for path in (CONFIGS / "kustomization.yaml", VENDOR / "README.md")
        ]
        self.assertEqual(len(commits[0]), 1)
        self.assertEqual(commits[0], commits[1])

    def test_promql_syntax(self) -> None:
        """Parse the vendored queries with promtool like the homelab dashboards."""
        rules = [
            {"record": f"homelab_validation:vendored_{index}", "expr": expr}
            for index, expr in enumerate(
                expr
                for dashboard in self.vendored.values()
                for expr in promql(dashboard)
            )
        ]
        self.assertTrue(rules)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vendored-queries.yaml"
            path.write_text(
                yaml.safe_dump({"groups": [{"name": "vendored", "rules": rules}]}),
                encoding="utf-8",
            )
            run_promtool(["check", "rules", str(path)])


if __name__ == "__main__":
    unittest.main()
