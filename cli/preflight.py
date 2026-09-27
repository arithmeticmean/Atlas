"""Verify a candidate configuration before it is written to disk.

``atlas init`` accepts any model name as free text -- a hardcoded menu can only
ever list a fraction of what a provider offers, and goes stale. The cost of
that freedom is that a typo must be caught somewhere, so it is caught here,
immediately, rather than at the next ``atlas serve``.

Each check performs a *real* call against the configured provider, because that
is the only thing that proves all three of: the endpoint is reachable, the
credentials are accepted, and the named model actually exists. For Ollama the
model list is consulted first, so "you never pulled this" can be reported as
itself instead of as a generic failure.
"""

import asyncio
from dataclasses import dataclass

from service.config import Settings

_PROBE_TEXT = "dimension probe"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """The outcome of one provider check."""

    name: str
    ok: bool
    detail: str
    hint: str = ""


async def _ollama_models(base_url: str) -> list[str] | None:
    """Model names this Ollama has pulled, or ``None`` if it is unreachable."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return None
    return [m["name"] for m in payload.get("models", []) if "name" in m]


def _ollama_hint(base_url: str) -> str:
    return (
        f"Is Ollama running and reachable at {base_url}? Start it with "
        "`ollama serve`. If it lives on another host, in a VM or under WSL, "
        "pass --ollama-base-url with its address and start it with "
        "OLLAMA_HOST=0.0.0.0."
    )


def _missing_model_hint(model: str, available: list[str]) -> str:
    listed = ", ".join(sorted(available)) if available else "none"
    return (
        f"Ollama is reachable but has not pulled {model!r}. "
        f"Run `ollama pull {model}`. Currently pulled: {listed}."
    )


async def check_embedding(settings: Settings) -> CheckResult:
    """Embed one short string with the configured embedding model.

    Success also yields the vector dimension, which is what gets recorded in
    the index lock file -- so this doubles as the value the user should see
    before committing to a model they cannot change without a full reindex.
    """
    name = (
        f"embedding: {settings.embedding_provider}"
        f"/{settings.embedding_model}"
    )

    if settings.embedding_provider == "ollama":
        available = await _ollama_models(settings.ollama_base_url)
        if available is None:
            return CheckResult(
                name, False, "cannot reach Ollama",
                _ollama_hint(settings.ollama_base_url),
            )
        if not _model_present(settings.embedding_model, available):
            return CheckResult(
                name, False, "model not pulled",
                _missing_model_hint(settings.embedding_model, available),
            )

    from service.ingest.embeddings import build_embeddings

    try:
        vector = await build_embeddings(settings).aembed_query(_PROBE_TEXT)
    except Exception as exc:
        return CheckResult(name, False, str(exc), _key_hint(settings))
    return CheckResult(name, True, f"{len(vector)} dimensions")


async def check_llm(settings: Settings) -> CheckResult:
    """Send one token-cheap prompt to the configured chat model."""
    name = f"llm: {settings.llm_provider}/{settings.llm_model}"

    if settings.llm_provider == "ollama":
        available = await _ollama_models(settings.ollama_base_url)
        if available is None:
            return CheckResult(
                name, False, "cannot reach Ollama",
                _ollama_hint(settings.ollama_base_url),
            )
        if not _model_present(settings.llm_model, available):
            return CheckResult(
                name, False, "model not pulled",
                _missing_model_hint(settings.llm_model, available),
            )

    from service.core.llm import build_chat_model

    try:
        await build_chat_model(settings).ainvoke("ping")
    except Exception as exc:
        return CheckResult(name, False, str(exc), _key_hint(settings))
    return CheckResult(name, True, "responded")


def _model_present(model: str, available: list[str]) -> bool:
    """Whether Ollama has this model.

    Ollama reports tagged names (``llama3.1:latest``); users type the untagged
    form far more often than not, so an exact miss falls back to matching the
    part before the tag.
    """
    if model in available:
        return True
    base = model.split(":", 1)[0]
    return any(a.split(":", 1)[0] == base for a in available)


def _key_hint(settings: Settings) -> str:
    if settings.llm_provider == "anthropic" and not settings.anthropic_api_key:
        return "No Anthropic API key was supplied."
    if settings.llm_provider == "openai" and not (
        settings.llm_api_key or settings.openai_api_key
    ):
        return "No API key was supplied for the OpenAI-compatible endpoint."
    return (
        "Check the model name is spelled as the provider names it, and that "
        "the API key is valid for it."
    )


async def run_checks(settings: Settings) -> list[CheckResult]:
    """Run every provider check concurrently."""
    return list(
        await asyncio.gather(check_embedding(settings), check_llm(settings))
    )
