"""Replay synthetic records through the actual Promtail binary, never a Python parser."""

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
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def pipeline_stages() -> list[dict]:
    """Unwrap only the Helm escape layer, leaving Promtail templates intact."""
    release = yaml.safe_load(
        (MONITORING / "controllers/loki-stack/promtail-release.yaml").read_text(
            encoding="utf-8"
        )
    )
    stages = release["spec"]["values"]["config"]["snippets"]["pipelineStages"]
    for stage in stages[1:]:
        for nested in stage["match"]["stages"]:
            if "template" in nested:
                template = nested["template"]["template"]
                if not (template.startswith("{{`") and template.endswith("`}}")):
                    raise ValueError("Expected explicit Helm template escape wrapper")
                nested["template"]["template"] = template[3:-3]
    return stages


def replay(app: str, records: list[str], namespace: str = "ankilabs") -> str:
    """Use stdin/dry-run mode so no Loki or Kubernetes endpoint is contacted."""
    binary = shutil.which(os.environ.get("PROMTAIL_BIN", "promtail"))
    if binary is None:
        raise RuntimeError(
            "Promtail is missing. Supply PROMTAIL_BIN for chart 6.17.1's "
            + "Promtail 3.5.1 binary; do not skip collector validation."
        )
    with tempfile.TemporaryDirectory() as directory:
        config_path = Path(directory) / "promtail.yaml"
        config = {
            "server": {"disable": True},
            "positions": {"filename": str(Path(directory) / "positions.yaml")},
            "clients": [{"url": "http://127.0.0.1:1/loki/api/v1/push"}],
            "scrape_configs": [
                {
                    "job_name": "fixture",
                    "pipeline_stages": pipeline_stages(),
                    "static_configs": [
                        {
                            "targets": ["localhost"],
                            "labels": {
                                "namespace": namespace,
                                "app": app,
                                "container": "postgres" if app == "postgres" else app,
                            },
                        }
                    ],
                }
            ],
        }
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        input_text = "".join(
            f"2026-11-13T18:00:00.000000000Z stderr F {record}\n" for record in records
        )
        result = subprocess.run(
            [binary, "-config.file", str(config_path), "-stdin", "-dry-run"],
            input=input_text,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return ANSI.sub("", result.stdout)


class PromtailReplayTests(unittest.TestCase):
    """Exercise schema/severity normalization and lossless raw fallbacks."""

    def test_postgres_native_and_normalized_severities(self) -> None:
        """EOF/open-transaction is WARNING without losing PostgreSQL LOG."""
        output = replay(
            "postgres",
            [
                (
                    "2026-11-13 18:00:00.000 UTC [42] app=sentence-lookup "
                    + "sqlstate=08006 LOG:  unexpected EOF on client connection "
                    + "with an open transaction"
                ),
                (
                    "2026-11-13 18:00:00.000 UTC [43] app= sqlstate=00000 "
                    + 'LOG:  checkpoint complete: "fixture"'
                ),
                (
                    "2026-11-13 18:00:00.000 UTC [44] app=postgres_exporter "
                    + "sqlstate=28P01 FATAL:  fixture authentication failure"
                ),
            ],
        )
        for expected in (
            '"pg_severity":"LOG"',
            '"level":"WARNING"',
            '"db_backend_pid":"42"',
            '"sqlstate":"08006"',
            '"level":"INFO"',
            '"pg_severity":"FATAL"',
            '"level":"CRITICAL"',
            '"raw":',
            r"\"fixture\"",
        ):
            self.assertIn(expected, output)

    def test_postgres_legacy_unknown_and_unparsed_records_survive(self) -> None:
        """Previous prefixes and multiline continuation fragments must not disappear."""
        records = [
            (
                "2026-11-13 18:00:00.000 UTC [45] LOG:  "
                + "unexpected EOF on client connection with an open transaction"
            ),
            (
                "2026-11-13 18:00:00.000 UTC [46] app=fixture "
                + "sqlstate=00000 FUTURE:  unknown-severity-fixture"
            ),
            "unparsed-fragment-fixture",
        ]
        output = replay("postgres", records)
        self.assertIn('"level":"WARNING"', output)
        self.assertIn('"pg_severity":"FUTURE"', output)
        self.assertIn('"level":"UNKNOWN"', output)
        self.assertIn("unknown-severity-fixture", output)
        self.assertIn("unparsed-fragment-fixture", output)

    def test_application_records_keep_fields_and_bounded_severity(self) -> None:
        """Started events, missing levels and malformed JSON remain available."""
        records = [
            json.dumps(
                {
                    "level": "ERROR",
                    "service": "api-gateway",
                    "event": "upstream.request.completed",
                    "upstream_service": "Sentence Lookup",
                    "status": "timeout",
                    "request_id": "request-fixture",
                }
            ),
            '{"level":"INFO","event":"db.stage.started","stage":"candidate_fetch"}',
            '{"level":"FUTURE","event":"future-event-fixture"}',
            '{"event":"missing-level-fixture"}',
            "invalid-json-fixture",
        ]
        output = replay("api-gateway", records)
        for expected in (
            'severity="ERROR"',
            'severity="INFO"',
            'severity="UNKNOWN"',
            "request-fixture",
            "db.stage.started",
            "future-event-fixture",
            "missing-level-fixture",
            "invalid-json-fixture",
        ):
            self.assertIn(expected, output)

    def test_postgres_primary_errors_cannot_quote_request_values(self) -> None:
        """SQLSTATE and PID survive while even primary-error literals are suppressed."""
        output = replay(
            "postgres",
            [
                (
                    "2026-11-13 18:00:00.000 UTC [47] app=sentence-lookup "
                    + 'sqlstate=22P02 ERROR:  invalid input syntax: "private-fixture-value"'
                ),
            ],
        )
        self.assertIn('"sqlstate":"22P02"', output)
        self.assertIn('"db_backend_pid":"47"', output)
        self.assertIn('"pg_severity":"ERROR"', output)
        self.assertIn('"raw_redacted":true', output)
        self.assertNotIn("private-fixture-value", output)

    def test_other_namespaces_are_not_reclassified(self) -> None:
        """The normalization branch must not combine application log streams."""
        output = replay("api-gateway", ["untouched-quizlabs-fixture"], "quizlabs")
        self.assertIn("untouched-quizlabs-fixture", output)
        self.assertNotIn("severity=", output)

    def test_edge_access_records_use_real_status_not_keywords(self) -> None:
        """Classify safe native edge JSON and preserve unexpected runtime output."""
        output = replay(
            "envoy",
            [
                '{"event":"edge.request.completed","http_status":503}',
                '{"event":"edge.request.completed","http_status":200}',
                "unparsed-edge-runtime-fixture",
            ],
            "envoy-gateway-system",
        )
        self.assertIn('severity="ERROR"', output)
        self.assertIn('severity="INFO"', output)
        self.assertIn('severity="UNKNOWN"', output)
        self.assertIn("unparsed-edge-runtime-fixture", output)


if __name__ == "__main__":
    unittest.main()
