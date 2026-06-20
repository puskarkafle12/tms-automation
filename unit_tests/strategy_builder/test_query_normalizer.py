import unittest

from utils.strategy_builder.query_normalizer import (
    StrategyQueryNormalizationError,
    normalize_strategy_query_text,
)
from utils.strategy_builder.strategy_parser import StrategyQueryError, parse_strategy_query


PLAIN_QUERY = """STRATEGY_VERSION 1
SIDE BUY
RULE "Test" FOR SYMBOL "NABIL" {
    WHEN technical_rsi_14 BETWEEN 30 AND 55
    ORDER QUANTITY 10
}"""


def wrap_fence(query: str, lang: str = "") -> str:
    opening = f"```{lang}".rstrip()
    return f"{opening}\n{query}\n```"


class StrategyQueryNormalizerTest(unittest.TestCase):
    def test_plain_query_without_backticks(self):
        self.assertEqual(normalize_strategy_query_text(PLAIN_QUERY), PLAIN_QUERY.strip())

    def test_query_wrapped_with_triple_backticks(self):
        wrapped = wrap_fence(PLAIN_QUERY)
        self.assertEqual(normalize_strategy_query_text(wrapped), PLAIN_QUERY.strip())

    def test_query_wrapped_with_text_label(self):
        wrapped = wrap_fence(PLAIN_QUERY, "text")
        self.assertEqual(normalize_strategy_query_text(wrapped), PLAIN_QUERY.strip())

    def test_query_wrapped_with_strategy_label(self):
        wrapped = wrap_fence(PLAIN_QUERY, "strategy")
        self.assertEqual(normalize_strategy_query_text(wrapped), PLAIN_QUERY.strip())

    def test_query_wrapped_with_sql_label(self):
        wrapped = wrap_fence(PLAIN_QUERY, "sql")
        self.assertEqual(normalize_strategy_query_text(wrapped), PLAIN_QUERY.strip())

    def test_leading_and_trailing_blank_lines(self):
        wrapped = f"\n\n{wrap_fence(PLAIN_QUERY, 'text')}\n\n"
        self.assertEqual(normalize_strategy_query_text(wrapped), PLAIN_QUERY.strip())

    def test_backticks_inside_strategy_raise_normalization_error(self):
        inner = PLAIN_QUERY.replace('"Test"', '"Test `note`"')
        with self.assertRaises(StrategyQueryNormalizationError) as ctx:
            normalize_strategy_query_text(wrap_fence(inner, "text"))
        self.assertIn("backticks", str(ctx.exception).lower())

    def test_unclosed_outer_fence_raises_normalization_error(self):
        broken = f"```text\n{PLAIN_QUERY}"
        with self.assertRaises(StrategyQueryNormalizationError) as ctx:
            normalize_strategy_query_text(broken)
        self.assertIn("closing", str(ctx.exception).lower())

    def test_fenced_query_parses_same_ast_as_plain_query(self):
        plain_plan = parse_strategy_query(PLAIN_QUERY)

        def comparable(plan):
            payload = plan.model_dump()
            for rule in payload.get("rules", []):
                rule.pop("rule_id", None)
            return payload

        plain_payload = comparable(plain_plan)
        for lang in ("", "text", "strategy", "sql"):
            fenced_plan = parse_strategy_query(wrap_fence(PLAIN_QUERY, lang))
            self.assertEqual(
                plain_payload,
                comparable(fenced_plan),
                msg=f"AST mismatch for fence label {lang!r}",
            )

    def test_inner_backticks_surface_as_strategy_query_error(self):
        inner = PLAIN_QUERY.replace('"Test"', '"Test `note`"')
        with self.assertRaises(StrategyQueryError) as ctx:
            parse_strategy_query(wrap_fence(inner, "text"))
        self.assertIn("backticks", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
