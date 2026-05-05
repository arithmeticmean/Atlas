"""Embedding model factory — the single import site for langchain embeddings.

Config-driven (``settings.embedding_provider``). Default is local Ollama with
no API key; ``fake`` is a deterministic offline embedding for tests. Provider
packages are imported lazily so an unselected provider need not be installed
and startup stays light.

The embedding *dimension* is not set here or in config -- it is probed from the
returned model at startup and recorded in the vector store's lock file
(see :mod:`service.embedding_index`).
"""

from langchain_core.embeddings import Embeddings
from pydantic import SecretStr

from config import settings


def build_embeddings() -> Embeddings:
    provider = settings.embedding_provider

    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=settings.embedding_model,
            base_url=settings.ollama_base_url,
        )

    if provider == "openai":
        key = settings.openai_api_key
        if not key:
            raise ValueError(
                "embedding_provider=openai requires openai_api_key"
            )
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=SecretStr(key),
        )

    if provider == "fake":
        from langchain_core.embeddings import DeterministicFakeEmbedding

        return DeterministicFakeEmbedding(size=settings.fake_embedding_dim)

    raise ValueError(f"unknown embedding_provider: {provider!r}")
