"""LanceDB vector store adapter.

Re-exports LangChain's LanceDB vector store unchanged. It already subclasses
the aliased ``storage.store.VectorStore`` base, so no wrapper is needed — this
module is simply the single import site for the concrete backend.
"""

from langchain_community.vectorstores import LanceDB

__all__ = ["LanceDB"]
