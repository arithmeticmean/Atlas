"""Chat and embedding models, built through LangChain.

Public API, in ``atlas.core.providers.factory``:

``PROVIDERS``
    Every selectable provider and what it needs.

``chat_model_from(settings=)``, ``embeddings_from(settings=)``
    The configured models. Neither makes a network call.

``check_chat_model(settings=)``, ``check_embeddings(settings=)``
    Make one real call and return a ``ProviderHealth(ok, detail)``.

``list_models(settings=, provider=, kind=, api_key=, base_url=)``
    The models a provider offers. Raises ``ProviderError`` if it can't say.

Provider packages load only when used.
"""
