"""Build the configured models, check they work, and list what's available.

A saved API key is only ever sent to the endpoint it was saved for. With a
custom URL, the provider-wide key (``openai_api_key``...) is never used.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, Literal, NamedTuple
from urllib.parse import urlparse

import httpx
from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr, ValidationError

from atlas.config import SECRET_FIELDS, Settings

__all__ = [
    "PROVIDERS",
    "ModelKind",
    "ProviderError",
    "ProviderHealth",
    "ProviderInfo",
    "chat_model_from",
    "check_chat_model",
    "check_embeddings",
    "describe_error",
    "embeddings_from",
    "endpoint_for",
    "list_models",
]

logger = logging.getLogger(__name__)

ModelKind = Literal["chat", "embedding"]

_TIMEOUT_SECONDS = 30
_MOONSHOT_HOSTS = {"api.moonshot.ai", "api.moonshot.cn"}


class ProviderError(Exception):
    """A provider could not answer. The message is safe to show."""


class ProviderHealth(NamedTuple):
    ok: bool
    detail: str


class ProviderInfo(NamedTuple):
    key: str
    name: str
    langchain_name: str
    supports_embeddings: bool = True
    needs_api_key: bool = False
    needs_base_url: bool = False
    default_base_url: str | None = None


PROVIDERS: dict[str, ProviderInfo] = {
    info.key: info
    for info in (
        ProviderInfo("ollama", "Ollama", "ollama"),
        ProviderInfo("openai", "OpenAI", "openai", needs_api_key=True),
        ProviderInfo(
            "anthropic",
            "Anthropic",
            "anthropic",
            supports_embeddings=False,
            needs_api_key=True,
        ),
        ProviderInfo("google", "Google", "google_genai", needs_api_key=True),
        ProviderInfo(
            "openai_compatible",
            "OpenAI-compatible",
            "openai",
            needs_base_url=True,
        ),
    )
}


class _Endpoint(NamedTuple):
    provider: str
    model: str
    api_key: str | None
    base_url: str | None


def chat_model_from(*, settings: Settings) -> BaseChatModel:
    """The chat model. A wrong name or key only surfaces on first use."""
    endpoint = _endpoint(settings, "chat")
    params = _connection(endpoint)
    if _has_thinking_switch(endpoint) and not settings.llm_thinking:
        params["extra_body"] = {"thinking": {"type": "disabled"}}
    return init_chat_model(
        endpoint.model,
        model_provider=PROVIDERS[endpoint.provider].langchain_name,
        configurable_fields=None,
        **params,
    )


def embeddings_from(*, settings: Settings) -> Embeddings:
    """The embedding model. Like the chat model, it connects on first use."""
    if settings.embedding_provider == "fake":
        return DeterministicFakeEmbedding(size=settings.fake_embedding_dim)
    endpoint = _endpoint(settings, "embedding")
    params = _connection(endpoint)
    if endpoint.provider == "openai_compatible":
        params["check_embedding_ctx_length"] = False  # send text, not tokens
    return init_embeddings(
        endpoint.model,
        provider=PROVIDERS[endpoint.provider].langchain_name,
        **params,
    )


async def check_chat_model(*, settings: Settings) -> ProviderHealth:
    """Make one real call to the chat model."""

    async def call() -> str:
        await chat_model_from(settings=settings).ainvoke("ping")
        return "ok"

    return await _check(settings, call)


async def check_embeddings(*, settings: Settings) -> ProviderHealth:
    """Make one real call to the embedding model."""

    async def call() -> str:
        embeddings = embeddings_from(settings=settings)
        vector = await embeddings.aembed_query("ping")
        return f"ok, {len(vector)} dimensions"

    return await _check(settings, call)


async def list_models(
    *,
    settings: Settings,
    provider: str,
    kind: ModelKind,
    api_key: str | None = None,
    base_url: str | None = None,
) -> list[str]:
    """The models ``provider`` offers. Without ``api_key`` the saved one is
    used, but never for a URL it was not saved for."""
    info = PROVIDERS.get(provider)
    if info is None:
        raise ProviderError("That provider isn't available.")
    if kind == "embedding" and not info.supports_embeddings:
        raise ProviderError(f"{info.name} has no embedding models.")
    key, url = _listing_target(settings, info, kind, api_key, base_url)
    if info.needs_api_key and not key:
        raise ProviderError(f"{info.name} needs an API key.")
    if info.needs_base_url and not url:
        raise ProviderError(f"{info.name} needs a base URL.")
    try:
        return await asyncio.wait_for(
            _LISTERS[provider](provider, kind, key, url), _TIMEOUT_SECONDS
        )
    except Exception as exc:
        logger.warning(
            "listing %s models failed: %s",
            info.name,
            _redacted(str(exc), settings, key),
        )
        raise ProviderError(describe_error(exc)) from exc


def describe_error(exc: BaseException) -> str:
    """What went wrong with a provider, in words safe to show anyone. Raw
    errors can hold request bodies, library internals or a key."""
    for link in _causes(exc):
        if isinstance(link, ProviderError):
            return str(link)
        if isinstance(link, ValidationError):
            return "Some connection details are missing or invalid."
        status = getattr(link, "status_code", None) or getattr(
            link, "code", None
        )
        if isinstance(status, int) and (message := _for_status(status)):
            return message
        if isinstance(link, TimeoutError | httpx.TimeoutException):
            return "The provider took too long to answer. Try again."
        if isinstance(link, ConnectionError | httpx.TransportError):
            return (
                "Couldn't connect. Check the address and that the service "
                "is running."
            )
    return "The provider returned an unexpected error."


def endpoint_for(*, settings: Settings, kind: ModelKind) -> tuple[Any, ...]:
    """Who a model call would reach and how; equal means nothing changed."""
    return _endpoint(settings, kind)


def _for_status(status: int) -> str | None:
    if status in (401, 403):
        return "The provider rejected this API key."
    if status == 404:
        return "The provider doesn't have that model, or the address is wrong."
    if status == 429:
        return "The provider's rate limit or quota has been reached."
    if status >= 500:
        return "The provider is having problems. Try again shortly."
    if status >= 400:
        return "The provider refused the request. Check the model name."
    return None


def _causes(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    link: BaseException | None = exc
    while link is not None and id(link) not in seen:
        seen.add(id(link))
        yield link
        link = link.__cause__ or link.__context__


def _endpoint(settings: Settings, kind: ModelKind) -> _Endpoint:
    provider: str
    if kind == "chat":
        provider, model = settings.llm_provider, settings.llm_model
        own_key, url = settings.llm_api_key, settings.llm_base_url
    else:
        provider, model = settings.embedding_provider, settings.embedding_model
        own_key, url = settings.embedding_api_key, settings.embedding_base_url
    if provider == "ollama":
        return _Endpoint(
            provider, model, None, url or settings.ollama_base_url
        )
    key = own_key if url else own_key or _provider_key(settings, provider)
    return _Endpoint(provider, model, _plain(key), url)


def _has_thinking_switch(endpoint: _Endpoint) -> bool:
    """Models that think by default and accept being told not to. Unknown
    servers can reject an unknown field, so this list stays explicit."""
    host = urlparse(endpoint.base_url or "").hostname
    return host in _MOONSHOT_HOSTS and endpoint.model.startswith("kimi-k2.6")


def _provider_key(settings: Settings, provider: str) -> SecretStr | None:
    keys = {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "google": settings.google_api_key,
    }
    return keys.get(provider)


def _connection(endpoint: _Endpoint) -> dict[str, Any]:
    info = PROVIDERS[endpoint.provider]
    if info.needs_api_key and not endpoint.api_key:
        raise ProviderError(f"{info.name} needs an API key.")
    if info.needs_base_url and not endpoint.base_url:
        raise ProviderError(f"{info.name} needs a base URL.")
    params: dict[str, Any] = {}
    if endpoint.base_url:
        params["base_url"] = endpoint.base_url
    if endpoint.provider == "google":
        params["google_api_key"] = endpoint.api_key
    elif endpoint.provider == "openai_compatible":
        params["api_key"] = endpoint.api_key or "not-needed"
    elif endpoint.api_key:
        params["api_key"] = endpoint.api_key
    return params


def _listing_target(
    settings: Settings,
    info: ProviderInfo,
    kind: ModelKind,
    api_key: str | None,
    base_url: str | None,
) -> tuple[str | None, str | None]:
    """The key and URL to list with. A saved key stays with its own URL."""
    if info.key == "ollama":
        return None, base_url or settings.ollama_base_url
    configured = _endpoint(settings, kind)
    if info.key == configured.provider:
        url = base_url or configured.base_url
        saved = configured.api_key if url == configured.base_url else None
    else:
        url = base_url
        saved = None if url else _plain(_provider_key(settings, info.key))
    return api_key or saved, url


async def _list_openai(
    provider: str, kind: ModelKind, key: str | None, url: str | None
) -> list[str]:
    from openai import AsyncOpenAI

    async with AsyncOpenAI(
        api_key=key or "not-needed", base_url=url
    ) as client:
        ids = sorted([model.id async for model in client.models.list()])
    if provider == "openai_compatible":
        return ids  # these servers name their models freely
    return [i for i in ids if ("embed" in i) == (kind == "embedding")]


async def _list_anthropic(
    _provider: str, _kind: ModelKind, key: str | None, _url: str | None
) -> list[str]:
    from anthropic import AsyncAnthropic

    async with AsyncAnthropic(api_key=key) as client:
        return [model.id async for model in client.models.list()]


async def _list_google(
    _provider: str, kind: ModelKind, key: str | None, _url: str | None
) -> list[str]:
    from google import genai

    action = "embedContent" if kind == "embedding" else "generateContent"
    pager = await genai.Client(api_key=key).aio.models.list()
    return [
        model.name.removeprefix("models/")
        async for model in pager
        if model.name and action in (model.supported_actions or [])
    ]


async def _list_ollama(
    _provider: str, _kind: ModelKind, _key: str | None, url: str | None
) -> list[str]:
    from ollama import AsyncClient

    response = await AsyncClient(host=url).list()
    return [model.model for model in response.models if model.model]


_LISTERS: dict[
    str,
    Callable[[str, ModelKind, str | None, str | None], Awaitable[list[str]]],
] = {
    "ollama": _list_ollama,
    "openai": _list_openai,
    "openai_compatible": _list_openai,
    "anthropic": _list_anthropic,
    "google": _list_google,
}


async def _check(
    settings: Settings, call: Callable[[], Awaitable[str]]
) -> ProviderHealth:
    try:
        detail = await asyncio.wait_for(call(), _TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning(
            "provider check failed: %s", _redacted(str(exc), settings)
        )
        return ProviderHealth(False, describe_error(exc))
    return ProviderHealth(True, detail)


def _redacted(
    message: str, settings: Settings, extra_key: str | None = None
) -> str:
    """Provider errors sometimes echo the key they were given."""
    saved = (_plain(getattr(settings, field)) for field in SECRET_FIELDS)
    for key in (*saved, extra_key):
        if key:
            message = message.replace(key, "***")
    return message


def _plain(secret: SecretStr | None) -> str | None:
    return secret.get_secret_value() if secret else None
