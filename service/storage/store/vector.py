"""Vector store port.
To keep ``langchain`` imports out of the rest of the codebase,
its base class is aliased here once and
re-exported under this name. already subclasses it, and all application code
depends on ``storage.store.VectorStore`` instead of importing langchain."""

from langchain_core.vectorstores import VectorStore

__all__ = ["VectorStore"]
