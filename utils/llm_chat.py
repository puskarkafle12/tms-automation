"""OpenAI-compatible multi-provider LLM chat with primary/fallback routing."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

try:
    import config.db_config  # noqa: F401 — loads .env
except Exception:
    pass

PROVIDER_ALIASES = {
    "grok": "groq",
    "groq": "groq",
    "nvidia": "nvidia",
    "gemini": "gemini",
    "google": "gemini",
    "cohere": "cohere",
}

PROVIDER_ENV_KEYS = {
    "groq": "GROQ_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "cohere": "COHERE_API_KEY",
}


class LlmChatError(Exception):
    """Raised when all configured LLM providers fail."""


def _normalize_provider(name: str) -> str:
    cleaned = (name or "").strip().lower()
    return PROVIDER_ALIASES.get(cleaned, cleaned)


def _groq_settings() -> Dict[str, Any]:
    return {
        "provider": "groq",
        "api_key": os.getenv("GROQ_API_KEY", "").strip(),
        "base_url": os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip(),
        "model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip(),
        "temperature": float(os.getenv("GROQ_TEMPERATURE", "0.2")),
        "top_p": float(os.getenv("GROQ_TOP_P", "1")),
        "max_tokens": int(os.getenv("GROQ_MAX_TOKENS", "1024")),
        "enable_thinking": False,
        "reasoning_effort": "",
        "use_compact_prompt": True,
    }


def _nvidia_settings() -> Dict[str, Any]:
    return {
        "provider": "nvidia",
        "api_key": os.getenv("NVIDIA_API_KEY", "").strip(),
        "base_url": os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip(),
        "model": os.getenv("NVIDIA_MODEL", "deepseek-ai/deepseek-v4-flash").strip(),
        "temperature": float(os.getenv("NVIDIA_TEMPERATURE", "1")),
        "top_p": float(os.getenv("NVIDIA_TOP_P", "0.95")),
        "max_tokens": int(os.getenv("NVIDIA_MAX_TOKENS", "16384")),
        "enable_thinking": os.getenv("NVIDIA_ENABLE_THINKING", "true").lower() == "true",
        "reasoning_effort": (os.getenv("NVIDIA_REASONING_EFFORT", "high") or "high").strip().lower(),
        "use_compact_prompt": False,
    }


def _gemini_settings() -> Dict[str, Any]:
    return {
        "provider": "gemini",
        "api_key": os.getenv("GEMINI_API_KEY", "").strip(),
        "base_url": os.getenv(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ).strip(),
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        "temperature": float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
        "top_p": float(os.getenv("GEMINI_TOP_P", "0.95")),
        "max_tokens": int(os.getenv("GEMINI_MAX_TOKENS", "4096")),
        "enable_thinking": False,
        "reasoning_effort": "",
        "use_compact_prompt": False,
    }


def _cohere_settings() -> Dict[str, Any]:
    return {
        "provider": "cohere",
        "api_key": os.getenv("COHERE_API_KEY", "").strip(),
        "base_url": "https://api.cohere.com",
        "model": os.getenv("COHERE_MODEL", "command-r7b-12-2024").strip(),
        "temperature": float(os.getenv("COHERE_TEMPERATURE", "0.1")),
        "top_p": float(os.getenv("COHERE_TOP_P", "1")),
        "max_tokens": int(os.getenv("COHERE_MAX_TOKENS", "4096")),
        "enable_thinking": False,
        "reasoning_effort": "",
        "use_compact_prompt": False,
    }


def _provider_settings(provider: str) -> Dict[str, Any]:
    normalized = _normalize_provider(provider)
    if normalized == "groq":
        return _groq_settings()
    if normalized == "nvidia":
        return _nvidia_settings()
    if normalized == "gemini":
        return _gemini_settings()
    if normalized == "cohere":
        return _cohere_settings()
    raise LlmChatError(f"Unknown LLM provider: {provider}")


def _provider_chain() -> List[str]:
    explicit = os.getenv("AI_LLM_PROVIDERS", "").strip()
    if explicit:
        chain: List[str] = []
        for raw in explicit.split(","):
            provider = _normalize_provider(raw)
            if provider and provider not in chain:
                chain.append(provider)
        return chain

    primary = _normalize_provider(os.getenv("AI_LLM_PRIMARY", "gemini"))
    fallback = _normalize_provider(os.getenv("AI_LLM_FALLBACK", "cohere"))
    tertiary = _normalize_provider(os.getenv("AI_LLM_TERTIARY", "groq"))
    chain: List[str] = []
    for provider in (primary, fallback, tertiary):
        if provider and provider not in chain:
            chain.append(provider)
    return chain


def is_auth_llm_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "401" in message
        or "403" in message
        or "unauthorized" in message
        or "authentication failed" in message
        or "invalid api key" in message
        or "api key not valid" in message
    )


def is_retryable_llm_error(exc: Exception) -> bool:
    message = str(exc).lower()
    name = exc.__class__.__name__.lower()
    if "429" in message or "too many requests" in message:
        return True
    if "413" in message or "request too large" in message:
        return True
    if "404" in message or "not found" in message:
        return True
    if "400" in message or "bad request" in message:
        return True
    if "tokens per minute" in message or " tpm" in message:
        return True
    if "rate limit" in message or "rate_limit" in name:
        return True
    if "quota" in message and "exceeded" in message:
        return True
    if any(code in message for code in ("500", "502", "503", "504")):
        return True
    if "overloaded" in message or "temporarily unavailable" in message:
        return True
    if "model request failed" in message:
        return True
    if "empty content" in message:
        return True
    if "context window" in message or "maximum context length" in message:
        return True
    return False


def should_fallback_llm_error(exc: Exception) -> bool:
    """Fallback to the next provider on any model/provider failure."""
    if isinstance(exc, LlmChatError):
        return True
    return is_retryable_llm_error(exc) or is_auth_llm_error(exc)


def _resolve_system_prompt(
    settings: Dict[str, Any],
    system_prompt: str,
    *,
    compact_system_prompt: Optional[str] = None,
) -> str:
    if settings.get("use_compact_prompt") and compact_system_prompt:
        return compact_system_prompt
    return system_prompt


def _extract_cohere_text(response: Any) -> str:
    message = getattr(response, "message", None)
    if not message or not getattr(message, "content", None):
        return ""
    parts: List[str] = []
    for block in message.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text).strip())
    return "\n".join(part for part in parts if part).strip()


def _call_cohere_chat(
    settings: Dict[str, Any],
    system_prompt: str,
    user_message: str,
    *,
    conversation: Optional[List[Dict[str, str]]] = None,
) -> str:
    provider = settings["provider"]
    try:
        import cohere
    except ImportError as exc:
        raise LlmChatError("cohere package is not installed on the server.") from exc

    client = cohere.ClientV2(api_key=settings["api_key"])
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if conversation:
        messages.extend(conversation)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat(
            model=settings["model"],
            messages=messages,
            temperature=settings["temperature"],
            max_tokens=settings["max_tokens"],
        )
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        raise LlmChatError(f"{provider} AI request failed: {message}") from exc

    content = _extract_cohere_text(response)
    if not content:
        raise LlmChatError(f"{provider} AI returned empty content.")
    return content


def _call_openai_compatible_chat(
    settings: Dict[str, Any],
    system_prompt: str,
    user_message: str,
    *,
    conversation: Optional[List[Dict[str, str]]] = None,
) -> str:
    provider = settings["provider"]
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LlmChatError("openai package is not installed on the server.") from exc

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
        lowered = message.lower()
        if "maximum context length" in lowered:
            raise LlmChatError(
                f"{provider} AI prompt exceeds the configured model context window. "
                "Use a larger-context model or lower max tokens.",
            ) from exc
        if "413" in message or "request too large" in lowered or "tokens per minute" in lowered:
            raise LlmChatError(
                f"{provider} AI request too large for the configured token limit: {message}",
            ) from exc
        raise LlmChatError(f"{provider} AI request failed: {message}") from exc

    if not completion.choices:
        raise LlmChatError(f"{provider} AI returned no completion choices.")

    message = completion.choices[0].message
    content = (message.content or "").strip()
    reasoning = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
    if not content and reasoning:
        content = str(reasoning).strip()
    if not content:
        raise LlmChatError(f"{provider} AI returned empty content.")
    return content


def _call_provider_chat(
    settings: Dict[str, Any],
    system_prompt: str,
    user_message: str,
    *,
    conversation: Optional[List[Dict[str, str]]] = None,
) -> str:
    provider = settings["provider"]
    if not settings["api_key"]:
        env_key = PROVIDER_ENV_KEYS.get(provider, f"{provider.upper()}_API_KEY")
        raise LlmChatError(f"{env_key} is not configured on the server.")

    if provider == "cohere":
        return _call_cohere_chat(
            settings,
            system_prompt,
            user_message,
            conversation=conversation,
        )
    return _call_openai_compatible_chat(
        settings,
        system_prompt,
        user_message,
        conversation=conversation,
    )


def call_llm_chat(
    system_prompt: str,
    user_message: str,
    *,
    conversation: Optional[List[Dict[str, str]]] = None,
    compact_system_prompt: Optional[str] = None,
) -> Tuple[str, str]:
    """Call configured LLM providers in order, falling back on any provider failure."""
    chain = _provider_chain()
    if not chain:
        raise LlmChatError("No LLM providers configured.")

    errors: List[str] = []
    for index, provider in enumerate(chain):
        settings = _provider_settings(provider)
        active_prompt = _resolve_system_prompt(
            settings,
            system_prompt,
            compact_system_prompt=compact_system_prompt,
        )
        try:
            content = _call_provider_chat(
                settings,
                active_prompt,
                user_message,
                conversation=conversation,
            )
            return content, provider
        except LlmChatError as exc:
            errors.append(str(exc))
            if index < len(chain) - 1 and should_fallback_llm_error(exc):
                continue
            raise LlmChatError(" | ".join(errors)) from exc

    raise LlmChatError(" | ".join(errors) if errors else "LLM request failed.")


def test_llm_connection(provider: Optional[str] = None) -> Dict[str, Any]:
    """Quick connectivity check for a provider (defaults to first in chain)."""
    chain = _provider_chain()
    selected = _normalize_provider(provider or (chain[0] if chain else "groq"))
    settings = _provider_settings(selected)
    raw = _call_provider_chat(
        settings,
        "You are a helpful assistant. Reply briefly.",
        "Reply with exactly: OK",
    )
    return {
        "provider": selected,
        "model": settings["model"],
        "base_url": settings.get("base_url", ""),
        "response_preview": raw[:200],
    }
