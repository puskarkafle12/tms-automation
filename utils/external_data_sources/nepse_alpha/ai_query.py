"""Generate strict screener queries via NVIDIA integrate API (DeepSeek v4 Flash)."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

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

# Keep system prompt bounded; override via env if your model allows more.
MAX_AI_SYSTEM_PROMPT_CHARS = 12_000

MAX_AI_SCREENER_RETRIES = int(os.getenv("NVIDIA_AI_MAX_RETRIES", "3"))


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
        "model": os.getenv("NVIDIA_MODEL", "deepseek-ai/deepseek-v4-flash").strip(),
        "temperature": float(os.getenv("NVIDIA_TEMPERATURE", "1")),
        "top_p": float(os.getenv("NVIDIA_TOP_P", "0.95")),
        "max_tokens": int(os.getenv("NVIDIA_MAX_TOKENS", "16384")),
        "enable_thinking": os.getenv("NVIDIA_ENABLE_THINKING", "true").lower() == "true",
        "reasoning_effort": (os.getenv("NVIDIA_REASONING_EFFORT", "high") or "high").strip().lower(),
    }


def build_ai_system_prompt() -> str:
    catalog = get_field_catalog()
    spec = get_screener_query_spec()
    allowed_keys = sorted(spec["allowed_filter_keys"])
    numeric_keys = [item["key"] for item in catalog if item["type"] == "number"]
    text_keys = [item["key"] for item in catalog if item["type"] == "text"]

    alias_pairs: List[str] = []
    for canonical, aliases in sorted(spec["field_aliases"].items()):
        if aliases:
            alias_pairs.append(f"{canonical}={','.join(aliases[:4])}")

    text_hints = "; ".join(
        f"{key}({hint})" for key, hint in TEXT_FIELD_HINTS.items() if key in allowed_keys
    )

    return f"""You are a NEPSE stock screener query generator (Nepse Alpha). Single-pass: answer once with the best valid query you can build.

GOAL: The user may ask anything. Return the most relevant runnable screen using ONLY allowed fields below.
Prefer STATUS: OK with a close approximation. Use STATUS: ERROR only when no valid query is possible.

RULES:
1. Use ONLY ALLOWED_KEYS ({len(allowed_keys)} keys). Exact snake_case. No OR, parentheses, JOIN, or comparing two fields. symbol is not filterable.
2. Numeric keys: > >= < <= = != <> BETWEEN. Text keys: = != <> IN (...) CONTAINS LIKE.
3. Always include ORDER BY and LIMIT (default {spec['limit_default']}, max {spec['limit_max']}).
4. Map user terms via ALIASES. If the user asks for unsupported data, do NOT fail — omit that filter, substitute the closest allowed field, and explain in Summary.
5. Use practical thresholds so the screen can return results on the first try.
6. Never invent field keys. Never filter by symbol.

NUMERIC_KEYS: {", ".join(numeric_keys)}
TEXT_KEYS: {", ".join(text_keys)}
TEXT_HINTS: {text_hints or "none"}
ALIASES(user term=canonical): {"; ".join(alias_pairs[:60]) or "none"}
UNSUPPORTED (substitute or omit — do not use in query): {", ".join(spec["unsupported_user_terms"][:12])}
ALLOWED_KEYS: {", ".join(allowed_keys)}

RESPONSE (pick one):

STATUS: OK  ← default whenever a reasonable query is possible
Summary:
- 2-3 short bullets: what this screen finds and how it ranks
- Limitation: (required when you dropped or substituted anything) We don't have <missing>; this uses <substitute> — close, not exact.
Query:
```
WHERE ...
ORDER BY field_key DESC
LIMIT {spec['limit_default']}
```

STATUS: ERROR  ← rare; only when no valid query can be built at all
Reason:
- one short bullet explaining the blocker
"""


def build_retry_user_message(
    original_message: str,
    *,
    failure_type: str,
    failure_detail: str,
    previous_query: str = "",
    attempt_number: int = 1,
) -> str:
    query_block = previous_query.strip() or "(none)"
    return f"""PREVIOUS ATTEMPT FAILED — generate a corrected query (attempt {attempt_number}).

Original user request:
{original_message.strip()}

Failure type: {failure_type}
Failure detail:
{failure_detail.strip()}

Previous query:
```
{query_block}
```

Instructions:
- Return STATUS: OK with the best corrected query in one shot.
- Stay relevant to the original user request; substitute closest allowed fields when needed.
- If zero rows before: relax filters slightly so related stocks can match.
- Add a Limitation bullet when you approximated or dropped unsupported parts.
- Do not repeat the same invalid query.
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


def _call_nvidia_chat(
    system_prompt: str,
    user_message: str,
    *,
    conversation: Optional[List[Dict[str, str]]] = None,
) -> str:
    settings = _nvidia_settings()
    if not settings["api_key"]:
        raise ScreenerAiError("NVIDIA_API_KEY is not configured on the server.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ScreenerAiError("openai package is not installed on the server.") from exc

    client = OpenAI(base_url=settings["base_url"], api_key=settings["api_key"])
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if conversation:
        messages.extend(conversation)
    messages.append({"role": "user", "content": user_message})

    request_kwargs: Dict[str, Any] = {
        "model": settings["model"],
        "messages": messages,
        "temperature": settings["temperature"],
        "top_p": settings["top_p"],
        "max_tokens": settings["max_tokens"],
        "stream": False,
    }
    if settings["enable_thinking"]:
        request_kwargs["extra_body"] = {
            "chat_template_kwargs": {
                "thinking": True,
                "reasoning_effort": settings["reasoning_effort"],
            },
        }

    try:
        completion = client.chat.completions.create(**request_kwargs)
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        if "maximum context length" in message.lower():
            raise ScreenerAiError(
                "AI prompt exceeds the configured NVIDIA model context window. "
                "Use a larger-context model or lower NVIDIA_MAX_TOKENS.",
            ) from exc
        raise ScreenerAiError(f"NVIDIA AI request failed: {message}") from exc

    if not completion.choices:
        raise ScreenerAiError("AI returned no completion choices.")

    message = completion.choices[0].message
    content = (message.content or "").strip()
    reasoning = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
    if not content and reasoning:
        content = str(reasoning).strip()
    if not content:
        raise ScreenerAiError("AI returned empty content.")
    return content


def generate_and_validate_screener_query(
    user_message: str,
    *,
    conversation: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Call NVIDIA AI, parse STATUS response, and strictly validate query syntax."""
    cleaned = (user_message or "").strip()
    if not cleaned:
        raise ScreenerAiError("Message is required.")

    system_prompt = build_ai_system_prompt()
    raw_response = _call_nvidia_chat(system_prompt, cleaned, conversation=conversation)
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


async def execute_ai_screener_with_retries(
    user_message: str,
    screener_runner: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
    *,
    max_retries: int = MAX_AI_SCREENER_RETRIES,
) -> Dict[str, Any]:
    """
    Loop: LLM → validate → run screener.
    On parse/execution error or zero rows, feed failure back to LLM (max retries).
    """
    original = (user_message or "").strip()
    if not original:
        raise ScreenerAiError("Message is required.")

    retry_context: List[Dict[str, Any]] = []
    attempt_log: List[Dict[str, Any]] = []
    conversation: List[Dict[str, str]] = []
    last_error: Optional[ScreenerAiError] = None

    for attempt in range(1, max_retries + 1):
        if attempt == 1:
            prompt = original
        else:
            last = retry_context[-1]
            prompt = build_retry_user_message(
                original,
                failure_type=str(last.get("failure_type", "unknown")),
                failure_detail=str(last.get("failure_detail", "")),
                previous_query=str(last.get("generated_query", "")),
                attempt_number=attempt,
            )

        try:
            ai_payload = await asyncio.to_thread(
                generate_and_validate_screener_query,
                prompt,
                conversation=conversation.copy() if conversation else None,
            )
        except ScreenerAiError as exc:
            last_error = exc
            entry = {
                "attempt": attempt,
                "failure_type": exc.status,
                "failure_detail": str(exc),
                "generated_query": exc.generated_query,
                "raw_response": exc.raw_response,
            }
            attempt_log.append(entry)
            retry_context.append(entry)
            if attempt >= max_retries:
                break
            conversation.append({"role": "user", "content": prompt})
            conversation.append({"role": "assistant", "content": exc.raw_response or str(exc)})
            continue

        try:
            screen_payload = await screener_runner(ai_payload["parsed_query"])
        except Exception as exc:
            last_error = ScreenerAiError(
                f"Screener execution failed: {exc}",
                status="execution_error",
                generated_query=ai_payload["generated_query"],
                raw_response=ai_payload.get("ai_raw_response", ""),
            )
            entry = {
                "attempt": attempt,
                "failure_type": "execution_error",
                "failure_detail": str(exc),
                "generated_query": ai_payload["generated_query"],
                "raw_response": ai_payload.get("ai_raw_response", ""),
            }
            attempt_log.append(entry)
            retry_context.append(entry)
            if attempt >= max_retries:
                break
            conversation.append({"role": "user", "content": prompt})
            conversation.append({"role": "assistant", "content": ai_payload.get("ai_raw_response", "")})
            continue

        matched = int((screen_payload.get("stats") or {}).get("matched", len(screen_payload.get("results") or [])))
        if matched == 0 and attempt < max_retries:
            detail = (
                f"Query ran successfully but matched 0 stocks out of "
                f"{(screen_payload.get('stats') or {}).get('loaded', '?')} loaded symbols."
            )
            entry = {
                "attempt": attempt,
                "failure_type": "zero_rows",
                "failure_detail": detail,
                "generated_query": ai_payload["generated_query"],
                "raw_response": ai_payload.get("ai_raw_response", ""),
            }
            attempt_log.append(entry)
            retry_context.append(entry)
            conversation.append({"role": "user", "content": prompt})
            conversation.append({"role": "assistant", "content": ai_payload.get("ai_raw_response", "")})
            continue

        summary = ai_payload["ai_summary"]
        if attempt > 1:
            summary = (
                f"{summary}\n\n- Refined after {attempt - 1} retry attempt(s) "
                f"({matched} stock(s) matched)."
            ).strip()
        elif matched == 0:
            summary = (
                f"{summary}\n\n- No stocks matched after {attempt} attempt(s). "
                "Try broadening your request."
            ).strip()

        return {
            **screen_payload,
            "ai_status": "ok",
            "ai_summary": summary,
            "generated_query": ai_payload["generated_query"],
            "parsed_query": ai_payload["parsed_query"],
            "ai_raw_response": ai_payload.get("ai_raw_response", ""),
            "ai_retry_count": attempt - 1,
            "ai_attempts": attempt_log,
        }

    if last_error:
        last_error.status = last_error.status or "error"
        raise last_error

    raise ScreenerAiError(f"AI screener failed after {max_retries} attempts.")


def test_nvidia_connection() -> Dict[str, Any]:
    """Quick connectivity check for NVIDIA API (used by scripts/tests)."""
    settings = _nvidia_settings()
    raw = _call_nvidia_chat(
        "You are a helpful assistant. Reply briefly.",
        "Reply with exactly: OK",
    )
    return {
        "model": settings["model"],
        "base_url": settings["base_url"],
        "response_preview": raw[:200],
    }
