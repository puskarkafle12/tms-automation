"""Generate Strategy Query Language plans via NVIDIA integrate API (retry loop)."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional

from utils.external_data_sources.nepse_alpha.ai_query import _call_nvidia_chat, build_retry_user_message
from utils.strategy_builder.strategy_llm_prompt import build_strategy_query_llm_prompt
from utils.strategy_builder.strategy_parser import StrategyQueryError, format_strategy_query, parse_strategy_query
from utils.strategy_builder.side_detection import validate_instruction_side
from utils.strategy_builder.strategy_validator import validate_strategy_plan

MAX_AI_STRATEGY_RETRIES = int(os.getenv("NVIDIA_AI_MAX_RETRIES", "5"))


class StrategyQueryAiError(Exception):
    def __init__(self, message: str, *, status: str = "error", raw_response: str = "", generated_query: str = ""):
        super().__init__(message)
        self.status = status
        self.raw_response = raw_response
        self.generated_query = generated_query


def build_strategy_ai_system_prompt(*, side: str = "buy", form_symbol: Optional[str] = None) -> str:
    base = build_strategy_query_llm_prompt(side=side, form_symbol=form_symbol)
    return f"""{base}

When responding to the user, use EXACTLY this format:

STATUS: OK
Summary:
- short bullet points about the plan
Query:
```
STRATEGY_VERSION 1
SIDE {side.upper()}
...
```

If you cannot produce a valid plan (unsupported indicator, missing data, parse error, or preflight would block scheduling):
STATUS: ERROR
Reason:
- Start with: This query is not supported — when applicable
- Name the missing field/function or explain why monitoring would fail
- Suggest a registered alternative from the FIELD REGISTRY when possible

Rules for Query block:
- Output only Strategy Query Language inside the fenced block.
- No markdown inside the query block.
- Every RULE must have FOR SYMBOL, a condition (WHEN or ELIGIBILITY+SIGNAL with optional REQUIRE), and ORDER.
- Use only fields and functions from the registries above (same rules as validator and schedule preflight).
- If the user omits quantity, omit ORDER QUANTITY so the runtime default applies.
"""


def _extract_summary(text: str) -> str:
    match = re.search(r"Summary:\s*(.+?)(?:\nQuery:|\nSTATUS:|\Z)", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    lines = [line.strip().lstrip("-• ").strip() for line in match.group(1).splitlines()]
    bullets = [line for line in lines if line and not line.startswith("```")]
    return "\n".join(f"- {line}" for line in bullets)


def _extract_error_reason(text: str) -> str:
    match = re.search(r"Reason:\s*(.+?)(?:\nQuery:|\Z)", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip() or "AI could not map the request to a valid strategy query."


def _extract_query_block(text: str) -> str:
    labeled = re.search(r"Query:\s*```(?:\w+)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if labeled:
        return labeled.group(1).strip()

    for match in re.finditer(r"```(?:\w+)?\s*(.*?)```", text, flags=re.DOTALL):
        block = match.group(1).strip()
        if block.upper().startswith("STRATEGY_VERSION"):
            return block

    lines: List[str] = []
    capture = False
    for line in text.splitlines():
        upper = line.strip().upper()
        if upper.startswith("STRATEGY_VERSION"):
            capture = True
        if capture:
            if upper.startswith("STATUS:"):
                break
            lines.append(line.rstrip())
    return "\n".join(lines).strip()


def parse_ai_strategy_response(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise StrategyQueryAiError("AI returned an empty response.")

    has_error = bool(re.search(r"STATUS:\s*ERROR", raw, flags=re.IGNORECASE))
    has_ok = bool(re.search(r"STATUS:\s*OK", raw, flags=re.IGNORECASE))

    if has_error and not has_ok:
        raise StrategyQueryAiError(_extract_error_reason(raw), status="error", raw_response=raw)

    if not has_ok:
        # Fallback: accept raw STRATEGY_VERSION block without STATUS wrapper.
        query = _extract_query_block(raw)
        if query.upper().startswith("STRATEGY_VERSION"):
            return {"status": "ok", "summary": "", "query": query, "raw_response": raw}
        raise StrategyQueryAiError(
            "AI response missing STATUS: OK. Refusing to use an unvalidated query.",
            raw_response=raw,
        )

    query = _extract_query_block(raw)
    if not query:
        raise StrategyQueryAiError(
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


def generate_and_validate_strategy_query(
    user_message: str,
    *,
    side: str = "buy",
    form_symbol: Optional[str] = None,
    strategy_type: Optional[str] = None,
    conversation: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    cleaned = (user_message or "").strip()
    if not cleaned:
        raise StrategyQueryAiError("Message is required.")

    side_mismatch = validate_instruction_side(cleaned, side)
    if side_mismatch:
        raise StrategyQueryAiError(side_mismatch, status="side_mismatch")

    system_prompt = build_strategy_ai_system_prompt(side=side, form_symbol=form_symbol)
    raw_response = _call_nvidia_chat(system_prompt, cleaned, conversation=conversation)
    parsed_ai = parse_ai_strategy_response(raw_response)

    try:
        plan = parse_strategy_query(parsed_ai["query"])
    except StrategyQueryError as exc:
        raise StrategyQueryAiError(
            f"AI query failed parser validation: {exc}",
            status="parse_error",
            raw_response=raw_response,
            generated_query=parsed_ai["query"],
        ) from exc

    validation = validate_strategy_plan(
        plan,
        strategy_type=strategy_type,
        form_symbol=form_symbol,
    )
    if not validation.valid:
        first_error = validation.errors[0].message if validation.errors else "Validation failed."
        status = validation.status if validation.status != "ok" else "validation_error"
        if status == "unsupported_data":
            suggestions = [issue.symbol or issue.message for issue in validation.suggestions]
            raise StrategyQueryAiError(
                validation.message or first_error,
                status="unsupported_data",
                raw_response=raw_response,
                generated_query=parsed_ai["query"],
            ) from None
        raise StrategyQueryAiError(
            f"AI query failed validation: {first_error}",
            status=status,
            raw_response=raw_response,
            generated_query=parsed_ai["query"],
        )

    return {
        "ai_status": "ok",
        "ai_summary": parsed_ai["summary"],
        "generated_query": format_strategy_query(plan),
        "compiled_plan": plan.model_dump(),
        "validation": validation.model_dump(),
        "ai_raw_response": raw_response,
    }


async def execute_strategy_query_ai_with_retries(
    user_message: str,
    *,
    side: str = "buy",
    form_symbol: Optional[str] = None,
    strategy_type: Optional[str] = None,
    max_retries: int = MAX_AI_STRATEGY_RETRIES,
) -> Dict[str, Any]:
    original = (user_message or "").strip()
    if not original:
        raise StrategyQueryAiError("Message is required.")

    retry_context: List[Dict[str, Any]] = []
    attempt_log: List[Dict[str, Any]] = []
    conversation: List[Dict[str, str]] = []
    last_error: Optional[StrategyQueryAiError] = None

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
            payload = await asyncio.to_thread(
                generate_and_validate_strategy_query,
                prompt,
                side=side,
                form_symbol=form_symbol,
                strategy_type=strategy_type,
                conversation=conversation.copy() if conversation else None,
            )
            summary = payload["ai_summary"]
            if attempt > 1:
                summary = (
                    f"{summary}\n\n- Refined after {attempt - 1} retry attempt(s)."
                ).strip()
            return {
                **payload,
                "ai_summary": summary,
                "ai_retry_count": attempt - 1,
                "ai_attempts": attempt_log,
                "valid": True,
            }
        except StrategyQueryAiError as exc:
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

    if last_error:
        raise last_error
    raise StrategyQueryAiError(f"AI strategy query failed after {max_retries} attempts.")
