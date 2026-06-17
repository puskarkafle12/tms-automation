"""Generate strict screener queries via NVIDIA Nemotron (OpenAI-compatible API)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

try:
    import config.db_config  # noqa: F401 — loads .env for NVIDIA_API_KEY
except Exception:
    pass

from utils.external_data_sources.nepse_alpha.query_parser import ScreenerQueryError, parse_screener_query
from utils.external_data_sources.nepse_alpha.screener import get_field_catalog, get_screener_query_spec

TEXT_FIELD_HINTS = {
    "technical_macd": "Usually 'Bullish' or 'Bearish'",
    "technical_sma_10": "Use 'above' or 'below'",
    "technical_sma_20": "Use 'above' or 'below'",
    "technical_sma_50": "Use 'above' or 'below'",
    "technical_sma_200": "Use 'above' or 'below'",
    "technical_volume_trend": "Trend label e.g. Up, Down",
    "technical_3m_price_tend": "Trend label e.g. Mean reverting, Trending",
}

OPERATOR_EXAMPLES = {
    "gt": "field_key > 10",
    "gte": "field_key >= 10",
    "lt": "field_key < 10",
    "lte": "field_key <= 10",
    "eq": "field_key = 10",
    "neq": "field_key != 10",
    "between": "field_key BETWEEN 30 AND 45",
    "contains": "field_key CONTAINS 'Bullish'",
    "in": "field_key IN ('above', 'below')",
}


class ScreenerAiError(Exception):
    """Raised when the AI cannot produce a valid screener query."""

    def __init__(self, message: str, *, status: str = "error", raw_response: str = "", generated_query: str = ""):
        super().__init__(message)
        self.status = status
        self.raw_response = raw_response
        self.generated_query = generated_query


def _nvidia_settings() -> Dict[str, Any]:
    return {
        "api_key": os.getenv("NVIDIA_API_KEY", "").strip(),
        "base_url": os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip(),
        "model": os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b").strip(),
        "temperature": float(os.getenv("NVIDIA_TEMPERATURE", "0.3")),
        "top_p": float(os.getenv("NVIDIA_TOP_P", "0.95")),
        "max_tokens": int(os.getenv("NVIDIA_MAX_TOKENS", "4096")),
        "enable_thinking": os.getenv("NVIDIA_ENABLE_THINKING", "true").lower() == "true",
        "reasoning_budget": int(os.getenv("NVIDIA_REASONING_BUDGET", "16384")),
    }


def build_ai_system_prompt() -> str:
    catalog = get_field_catalog()
    spec = get_screener_query_spec()
    allowed_keys = sorted(spec["allowed_filter_keys"])
    numeric_fields = [item for item in catalog if item["type"] == "number"]
    text_fields = [item for item in catalog if item["type"] == "text"]

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in catalog:
        grouped.setdefault(item["category"], []).append(item)

    field_sections: List[str] = []
    for category, items in grouped.items():
        lines: List[str] = []
        for field in items:
            key = field["key"]
            ops = field.get("operators") or []
            op_examples = ", ".join(f"`{OPERATOR_EXAMPLES.get(op, op)}`" for op in ops)
            aliases = spec["field_aliases"].get(key) or []
            alias_text = f" | aliases: {', '.join(aliases)}" if aliases else ""
            hint = TEXT_FIELD_HINTS.get(key)
            hint_text = f" | hint: {hint}" if hint else ""
            lines.append(
                f"- `{key}` — {field['label']} | type: {field['type']} | operators: {', '.join(ops)}"
                f"{alias_text}{hint_text}\n  examples: {op_examples}"
            )
        field_sections.append(f"### {category}\n" + "\n".join(lines))

    alias_lines = []
    for canonical, aliases in sorted(spec["field_aliases"].items()):
        if aliases:
            alias_lines.append(f"- `{canonical}` ← {', '.join(repr(a) for a in aliases)}")

    machine_catalog = {
        "source": "GET /stock_screener/fields",
        "filterable_field_count": len(catalog),
        "fields": [
            {
                "key": item["key"],
                "label": item["label"],
                "category": item["category"],
                "type": item["type"],
                "operators": item.get("operators") or [],
                "aliases": spec["field_aliases"].get(item["key"]) or [],
            }
            for item in catalog
        ],
        "non_filterable_columns": spec["non_filterable_columns"],
        "unsupported_user_terms": spec["unsupported_user_terms"],
    }

    return f"""You are a strict query generator for a NEPSE stock screener (Nepse Alpha data).
Output ONLY the response format below. This is NOT full SQL.

RULES:
1. Use ONLY field keys from ALLOWED_FIELD_KEYS ({len(allowed_keys)} keys). Copy snake_case exactly.
2. If the user asks for a column not in the list → STATUS: ERROR (no query block).
3. No OR, no parentheses logic, no JOIN, no math, no comparing two fields.
4. `symbol` is not filterable.
5. Numeric fields: >, >=, <, <=, =, !=, <>, BETWEEN.
6. Text fields: =, !=, <>, IN (...), CONTAINS, LIKE.
7. Always include ORDER BY and LIMIT (default {spec['limit_default']}, max {spec['limit_max']}).

ALLOWED_FIELD_KEYS:
{chr(10).join(f'- `{key}`' for key in allowed_keys)}

NUMERIC FIELDS ({len(numeric_fields)}):
{chr(10).join(f'- `{item["key"]}` — {item["label"]}' for item in numeric_fields)}

TEXT FIELDS ({len(text_fields)}):
{chr(10).join(f'- `{item["key"]}` — {item["label"]}' for item in text_fields)}

ALIAS MAP (map user terms → output canonical key only):
{chr(10).join(alias_lines) if alias_lines else '- (exact keys only)'}

UNSUPPORTED (always STATUS: ERROR):
{chr(10).join(f'- {term}' for term in spec['unsupported_user_terms'])}

FIELD CATALOG:
{chr(10).join(field_sections)}

MACHINE JSON:
```json
{json.dumps(machine_catalog, indent=2)}
```

RESPONSE FORMAT:

When valid:
STATUS: OK

Summary:
- bullet points

Query:
```
WHERE ...
ORDER BY field_key DESC
LIMIT 25
```

When invalid:
STATUS: ERROR

Reason:
- explanation

Invalid request detail:
- what user asked

Closest allowed API keys:
- list keys or none
"""


def _extract_summary(text: str) -> str:
    match = re.search(r"Summary:\s*(.+?)(?:\nQuery:|\nSTATUS:|\Z)", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    lines = [line.strip().lstrip("-• ").strip() for line in match.group(1).splitlines()]
    bullets = [line for line in lines if line and not line.startswith("```")]
    return "\n".join(f"- {line}" for line in bullets)


def _extract_error_reason(text: str) -> str:
    match = re.search(r"Reason:\s*(.+?)(?:\nInvalid request detail:|\nClosest allowed|\Z)", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip() or "AI could not map the request to allowed screener fields."


def _extract_query_block(text: str) -> str:
    labeled = re.search(r"Query:\s*```(?:\w+)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if labeled:
        return labeled.group(1).strip()

    for match in re.finditer(r"```(?:\w+)?\s*(.*?)```", text, flags=re.DOTALL):
        block = match.group(1).strip()
        if re.search(r"\b(WHERE|ORDER\s+BY)\b", block, flags=re.IGNORECASE):
            return block

    lines: List[str] = []
    capture = False
    for line in text.splitlines():
        upper = line.strip().upper()
        if upper.startswith("WHERE") or upper.startswith("ORDER BY"):
            capture = True
        if capture:
            if upper.startswith("STATUS:"):
                break
            lines.append(line.rstrip())
    return "\n".join(lines).strip()


def parse_ai_screener_response(text: str) -> Dict[str, Any]:
    """Parse Nemotron/ChatGPT style STATUS response into query or error."""
    raw = (text or "").strip()
    if not raw:
        raise ScreenerAiError("AI returned an empty response.")

    has_error = bool(re.search(r"STATUS:\s*ERROR", raw, flags=re.IGNORECASE))
    has_ok = bool(re.search(r"STATUS:\s*OK", raw, flags=re.IGNORECASE))

    if has_error and not has_ok:
        raise ScreenerAiError(_extract_error_reason(raw), status="error", raw_response=raw)

    if not has_ok:
        raise ScreenerAiError(
            "AI response missing STATUS: OK. Refusing to run an unvalidated query.",
            raw_response=raw,
        )

    query = _extract_query_block(raw)
    if not query:
        raise ScreenerAiError(
            "AI returned STATUS: OK but no query block was found.",
            status="ok",
            raw_response=raw,
        )

    return {
        "status": "ok",
        "summary": _extract_summary(raw),
        "query": query,
        "raw_response": raw,
    }


def _call_nvidia_chat(system_prompt: str, user_message: str) -> str:
    settings = _nvidia_settings()
    if not settings["api_key"]:
        raise ScreenerAiError("NVIDIA_API_KEY is not configured on the server.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ScreenerAiError("openai package is not installed on the server.") from exc

    client = OpenAI(base_url=settings["base_url"], api_key=settings["api_key"])
    request_kwargs: Dict[str, Any] = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": settings["temperature"],
        "top_p": settings["top_p"],
        "max_tokens": settings["max_tokens"],
    }
    if settings["enable_thinking"]:
        request_kwargs["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": settings["reasoning_budget"],
        }

    completion = client.chat.completions.create(**request_kwargs)
    if not completion.choices:
        raise ScreenerAiError("AI returned no completion choices.")

    message = completion.choices[0].message
    content = (message.content or "").strip()
    reasoning = getattr(message, "reasoning_content", None)
    if not content and reasoning:
        content = str(reasoning).strip()
    if not content:
        raise ScreenerAiError("AI returned empty content.")
    return content


def generate_and_validate_screener_query(user_message: str) -> Dict[str, Any]:
    """Call NVIDIA AI, parse STATUS response, and strictly validate query syntax."""
    cleaned = (user_message or "").strip()
    if not cleaned:
        raise ScreenerAiError("Message is required.")

    system_prompt = build_ai_system_prompt()
    raw_response = _call_nvidia_chat(system_prompt, cleaned)
    parsed_ai = parse_ai_screener_response(raw_response)

    try:
        parsed_query = parse_screener_query(parsed_ai["query"])
    except ScreenerQueryError as exc:
        raise ScreenerAiError(
            f"AI query failed strict parser validation: {exc}",
            status="parse_error",
            raw_response=raw_response,
            generated_query=parsed_ai["query"],
        ) from exc

    return {
        "ai_status": "ok",
        "ai_summary": parsed_ai["summary"],
        "generated_query": parsed_ai["query"],
        "parsed_query": parsed_query,
        "ai_raw_response": raw_response,
    }
