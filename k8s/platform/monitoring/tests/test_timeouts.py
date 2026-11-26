"""The AnkiLabs AI request timeout chain: each hop gives up before the one in front of it."""

import re
import unittest
from pathlib import Path

import yaml

K8S = Path(__file__).resolve().parents[3]
ANKILABS = K8S / "apps/ankilabs"
# Cloudflare's proxy waits 100s for an origin response; not configurable below the Enterprise plan.
CLOUDFLARE_ORIGIN_SECONDS = 100.0
# ankilabs-api-gateway's code default (src/api_gateway/settings.py ai_timeout_seconds),
# used unless the release sets AI_TIMEOUT_SECONDS.
API_GATEWAY_AI_DEFAULT_SECONDS = 90.0
DURATION_PART = re.compile(r"(\d+)(h|ms|m|s)")
UNIT_SECONDS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


def gateway_api_seconds(duration: str) -> float:
    """A Gateway API (GEP-2257) duration such as 95s or 1m30s, in seconds."""
    parts = DURATION_PART.findall(duration)
    if not parts or "".join(value + unit for value, unit in parts) != duration:
        raise ValueError(f"not a Gateway API duration: {duration!r}")
    return sum(int(value) * UNIT_SECONDS[unit] for value, unit in parts)


def release_env(name: str) -> dict[str, str]:
    """The literal env values of an AnkiLabs HelmRelease."""
    release = yaml.safe_load(
        (ANKILABS / name / "release.yaml").read_text(encoding="utf-8")
    )
    return {
        item["name"]: item["value"]
        for item in release["spec"]["values"].get("env", [])
        if "value" in item
    }


def route_rules() -> dict[str, dict]:
    """The ankilabs HTTPRoute rules by path prefix."""
    route = yaml.safe_load((ANKILABS / "httproute.yaml").read_text(encoding="utf-8"))
    return {
        match["path"]["value"]: rule
        for rule in route["spec"]["rules"]
        for match in rule["matches"]
    }


class TimeoutChainTest(unittest.TestCase):
    """Cloudflare > Envoy /api route > API Gateway AI > AI Card Actions LLM Proxy."""

    def test_api_route_timeout_sits_between_cloudflare_and_the_api_gateway(self):
        """Envoy's 15s default answered slow AI calls with 504 while they were still running."""
        rules = route_rules()
        timeouts = rules["/api"]["timeouts"]
        self.assertNotIn("backendRequest", timeouts)
        route = gateway_api_seconds(timeouts["request"])
        api_gateway = float(
            release_env("api-gateway").get(
                "AI_TIMEOUT_SECONDS", API_GATEWAY_AI_DEFAULT_SECONDS
            )
        )
        llm_proxy = float(release_env("ai-card-actions")["LLM_PROXY_TIMEOUT_SECONDS"])
        self.assertGreater(CLOUDFLARE_ORIGIN_SECONDS, route)
        self.assertGreater(route, api_gateway)
        self.assertGreater(api_gateway, llm_proxy)

    def test_only_the_api_route_overrides_the_default_timeout(self):
        """The frontend serves static files and keeps Envoy's default."""
        rules = route_rules()
        self.assertEqual(
            [path for path, rule in rules.items() if "timeouts" in rule], ["/api"]
        )

    def test_gateway_api_durations_parse(self):
        """The parser accepts GEP-2257 durations and nothing else."""
        self.assertEqual(gateway_api_seconds("95s"), 95.0)
        self.assertEqual(gateway_api_seconds("1m35s"), 95.0)
        self.assertEqual(gateway_api_seconds("500ms"), 0.5)
        for invalid in ("95", "95 s", "1.5s", "s"):
            with self.assertRaises(ValueError):
                gateway_api_seconds(invalid)


if __name__ == "__main__":
    unittest.main()
