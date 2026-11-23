"""The AI engine: everything that involves a model or a vector.

Services call this package; it never touches HTTP, the repository, or global
settings. Configuration is passed in, and persisted data arrives as arguments.

Public API, by module (nothing is re-exported, so importing ``atlas.core``
loads no model or parsing library):

``atlas.core.providers.factory``
    ``chat_model_from(settings=)``, ``embeddings_from(settings=)``,
    ``check_chat_model(settings=)``, ``check_embeddings(settings=)``,
    ``list_models(...)``, ``PROVIDERS``, ``ProviderHealth``, ``ProviderError``

``atlas.core.parsing.pipeline``
    ``FileInput``, ``FileChunker``, ``ensure_supported(file)``,
    ``supported_file_types()``

``atlas.core.parsing.errors``
    ``ParsingError``, ``UnsupportedFile``, ``UnreadableFile``

``atlas.core.vector_store``
    ``build_vector_store(settings=, embeddings=)``,
    ``confirm_embedding_model(settings=)``, ``index_document(...)``,
    ``search(...)``, ``project_retriever(...)``, ``document_chunks(...)``,
    ``chunk_count(store)``, ``document_filter(id)``, ``project_filter(id)``

``atlas.core.chat``
    ``answer(...)``, ``title(...)``, ``AnswerEvent``

Typical wiring, once at startup::

    embeddings = embeddings_from(settings=settings)
    llm = chat_model_from(settings=settings)
    store, needs_reindex = build_vector_store(
        settings=settings, embeddings=embeddings
    )
    chunker = FileChunker(
        chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
    )

Ingesting a document::

    file = FileInput(content, filename=name, mime_type=mime_type)
    count = await index_document(
        store,
        project_id=project_id,
        document_id=document_id,
        batches=chunker.astream(file),
    )

Answering a question::

    async for kind, data in answer(
        llm=llm, store=store, chat=chat, question=question
    ):
        ...  # ("retrieval", {...}) once, then ("token", text) pieces
"""
