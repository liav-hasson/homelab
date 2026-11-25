"""Dashboard rules that depend on what a metric means, not on panel layout."""

import json
import re
import unittest
from pathlib import Path

from dashboard_panels import iter_panels

DASHBOARDS = Path(__file__).resolve().parents[1] / "configs/dashboards"
TOKEN_TYPES = {"prompt", "completion", "reasoning"}
TOKEN_SELECTOR = re.compile(
    r"ankilabs_ai_card_actions_llm_tokens_total(?:\{([^}]*)\})?"
)
TYPE_MATCHER = re.compile(r'\btype\s*(=~|!~|!=|=)\s*"([^"]*)"')


def selected_token_types(expr: str) -> list[set[str]]:
    """Token types each token-counter selector in a PromQL expression reads."""
    selections = []
    for labels in TOKEN_SELECTOR.findall(expr):
        selected = set(TOKEN_TYPES)
        for operator, value in TYPE_MATCHER.findall(labels):
            if "~" in operator:
                matched = {name for name in TOKEN_TYPES if re.fullmatch(value, name)}
            else:
                matched = {value} & TOKEN_TYPES
            selected &= matched if operator in ("=", "=~") else TOKEN_TYPES - matched
        selections.append(selected)
    return selections


def mixes_reasoning(expr: str) -> bool:
    """Reasoning tokens are part of completion tokens, so a query reads them alone."""
    types = set().union(*selected_token_types(expr))
    return "reasoning" in types and types != {"reasoning"}


class TokenTotalTests(unittest.TestCase):
    """A token total is prompt + completion; adding reasoning counts it twice."""

    def test_dashboards_never_add_reasoning_to_other_token_types(self) -> None:
        """Every token query reads reasoning on its own or not at all."""
        exprs = [
            target["expr"]
            for path in sorted(DASHBOARDS.glob("*.json"))
            for panel in iter_panels(json.loads(path.read_text(encoding="utf-8")))
            if panel.get("datasource", {}).get("type") == "prometheus"
            for target in panel["targets"]
        ]
        token_exprs = [expr for expr in exprs if selected_token_types(expr)]
        self.assertTrue(token_exprs)
        for expr in token_exprs:
            with self.subTest(expr=expr):
                self.assertFalse(mixes_reasoning(expr))

    def test_rule_reads_type_matchers(self) -> None:
        """Equality, regex and negative matchers are all resolved."""
        metric = "ankilabs_ai_card_actions_llm_tokens_total"
        for labels in (
            'type=~"prompt|completion"',
            'type="reasoning"',
            'type!="reasoning"',
            'type!~"reasoning"',
            'type="prompt"',
        ):
            with self.subTest(labels=labels):
                self.assertFalse(
                    mixes_reasoning(f'{metric}{{namespace="ankilabs",{labels}}}')
                )
        for expr in (
            f'{metric}{{namespace="ankilabs"}}',
            metric,
            f'{metric}{{namespace="ankilabs",type!="prompt"}}',
            f'{metric}{{namespace="ankilabs",type=~".+"}}',
            f'sum({metric}{{type="prompt"}}) + sum({metric}{{type=~"completion|reasoning"}})',
            f'sum({metric}{{type="completion"}}) + sum({metric}{{type="reasoning"}})',
        ):
            with self.subTest(expr=expr):
                self.assertTrue(mixes_reasoning(expr))


if __name__ == "__main__":
    unittest.main()
