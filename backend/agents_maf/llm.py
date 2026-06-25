"""Shared LLM client builder for the MAF agentic layer.

Only Ollama Cloud is supported. MAF's OpenAIChatCompletionClient talks to the
OpenAI-compatible Ollama Cloud endpoint via base_url — see Settings.llm_* properties.

We use OpenAIChatCompletionClient (the Chat Completions API), NOT OpenAIChatClient
(the Responses API): Ollama Cloud's compatibility layer implements Chat Completions.

Fallback: run_agent_with_fallback() retries on rate-limit/429 using the configured
fallback model, transparently swapping primary -> fallback.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from config import settings

logger = logging.getLogger(__name__)


def _client_for(model: str):
    from agent_framework.openai import OpenAIChatCompletionClient  # type: ignore[import]

    if settings.llm_provider != "ollama_cloud":
        raise RuntimeError(
            "Only LLM_PROVIDER=ollama_cloud is supported. "
            "Set LLM_PROVIDER=ollama_cloud and configure Ollama Cloud credentials."
        )
    if not settings.llm_api_key:
        raise RuntimeError(
            "OLLAMA_CLOUD_API_KEY is not set. Set it in the backend environment."
        )
    return OpenAIChatCompletionClient(
        model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )


def build_chat_client(use_fallback: bool = False):
    """Build a chat client for the primary (or fallback) model of the active provider."""
    model = settings.llm_model_fallback if use_fallback else settings.llm_model_primary
    return _client_for(model)


def is_rate_limit(exc: BaseException) -> bool:
    """True if an exception looks like a provider rate-limit / quota error."""
    text = str(exc).lower()
    return any(s in text for s in ("429", "rate limit", "rate_limit", "quota", "resource_exhausted"))


async def run_agent_with_fallback(build_agent: Callable[[bool], Any], prompt: str):
    """Run ``build_agent(use_fallback).run(prompt)``, swapping to the fallback model on 429.

    ``build_agent`` must accept a single bool (use_fallback) and return a MAF agent.
    """
    try:
        return await build_agent(False).run(prompt)
    except Exception as exc:  # noqa: BLE001 — provider failure, decide on fallback
        if is_rate_limit(exc) and settings.llm_model_fallback != settings.llm_model_primary:
            logger.warning(
                "Primary model '%s' rate-limited (%s) — retrying with fallback '%s'",
                settings.llm_model_primary, type(exc).__name__, settings.llm_model_fallback,
            )
            return await build_agent(True).run(prompt)
        raise
