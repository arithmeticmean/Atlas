"""Chat-model factory — the single import site for langchain chat models.

Config-driven (``settings.llm_provider``). Default is local Ollama; hosted
providers are bring-your-own-key. The LLM is stateless: unlike the embedding
model it can be swapped freely (edit config, restart) with no reindex.

Used by the answer/generation path (not by ingestion). Provider packages are
imported lazily so an unselected provider need not be installed.
"""

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from config import settings


def build_chat_model() -> BaseChatModel:
    provider = settings.llm_provider

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
        )

    if provider == "anthropic":
        key = settings.anthropic_api_key
        if not key:
            raise ValueError(
                "llm_provider=anthropic requires anthropic_api_key"
            )
        from langchain_anthropic import ChatAnthropic

        # ChatAnthropic's model field is aliased "model_name"; timeout/stop
        # are typed as required though they default at runtime.
        return ChatAnthropic(
            model_name=settings.llm_model,  # e.g. "claude-sonnet-5"
            api_key=SecretStr(key),
            timeout=None,
            stop=None,
        )

    if provider == "openai":
        # Also serves any OpenAI-compatible endpoint via llm_base_url
        # (OpenRouter, Moonshot/Kimi, Groq, DeepSeek, …).
        key = settings.llm_api_key or settings.openai_api_key
        if not key:
            raise ValueError(
                "llm_provider=openai requires llm_api_key (or openai_api_key)"
            )
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.llm_model,
            api_key=SecretStr(key),
            base_url=settings.llm_base_url or None,
        )

    raise ValueError(f"unknown llm_provider: {provider!r}")


async def check_chat_model() -> None:
    """Startup fail-fast: build the chat model and make one tiny call.

    Surfaces a bad key / model name / endpoint immediately (in the container
    logs) instead of only when the first answer is requested. Raises
    ``RuntimeError`` with the underlying reason.
    """
    try:
        model = build_chat_model()
        await model.ainvoke("ping")
    except Exception as exc:
        raise RuntimeError(
            f"LLM provider {settings.llm_provider!r} "
            f"(model {settings.llm_model!r}) failed its startup check: {exc}"
        ) from exc
