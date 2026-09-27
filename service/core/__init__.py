"""Application services: the orchestration layer.

Each module here coordinates the ports in ``service.storage`` and the model
providers to carry out one job -- authenticate a caller, ingest a document,
answer a question -- without knowing anything about HTTP. ``service.api`` calls
into this layer; nothing in this layer calls back out to ``service.api``.

Deliberately empty of re-exports, for the same reason ``service/__init__.py``
is: a barrel here would put every service (and through them langchain and
SQLAlchemy) on the import path of anything under ``service.core``. Import from
the module that defines the name.
"""
