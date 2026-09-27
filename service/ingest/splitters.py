"""Text splitter factory — the single import site for langchain splitters."""

from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    TextSplitter,
)

from service.config import settings


def build_splitter() -> TextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
