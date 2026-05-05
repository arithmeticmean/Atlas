"""Loader resolution — the single import site for langchain document loaders.

Maps a stored blob to the langchain loader that can read it. Because blobs are
stored under an opaque ``document_id`` with no file extension, the stored path
carries no format hint; resolution therefore works off, in order of trust:

1. the ``mime_type`` recorded at upload time (the browser/client's content
   type),
2. the extension of the original ``filename`` (``DocumentMetadata.title``),
3. a magic-byte sniff of the bytes on disk (``python-magic``).

Adding a new format is a one-line entry in ``_LOADERS`` (and ``_EXT_TO_MIME``
if the extension fallback should recognise it).
"""

from collections.abc import Callable
from pathlib import Path

import magic
from langchain_community.document_loaders import (
    BSHTMLLoader,
    Docx2txtLoader,
    PyPDFLoader,
    TextLoader,
)
from langchain_core.document_loaders import BaseLoader

LoaderFactory = Callable[[str], BaseLoader]

_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


class UnsupportedMimeType(Exception):
    """Raised when no loader is wired up for a document's type."""


def _text_loader(path: str) -> BaseLoader:
    return TextLoader(path, autodetect_encoding=True)


def _html_loader(path: str) -> BaseLoader:
    # Use the stdlib parser so we don't need lxml as a dependency.
    return BSHTMLLoader(path, bs_kwargs={"features": "html.parser"})


# mime type -> how to build a loader for a blob at ``path``.
_LOADERS: dict[str, LoaderFactory] = {
    "text/plain": _text_loader,
    "text/markdown": _text_loader,
    "text/html": _html_loader,
    "application/pdf": PyPDFLoader,
    _DOCX_MIME: Docx2txtLoader,
}

# Extension -> mime, used when the recorded mime type is missing or generic.
_EXT_TO_MIME: dict[str, str] = {
    ".txt": "text/plain",
    ".text": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
    ".docx": _DOCX_MIME,
}


def _resolve_mime(
    source_path: str, mime_type: str | None, filename: str | None
) -> str | None:
    """Best-effort mime resolution; returns a supported mime or ``None``."""
    if mime_type in _LOADERS:
        return mime_type

    if filename:
        by_ext = _EXT_TO_MIME.get(Path(filename).suffix.lower())
        if by_ext in _LOADERS:
            return by_ext

    try:
        sniffed = magic.from_file(source_path, mime=True)
    except Exception:
        sniffed = None
    if sniffed in _LOADERS:
        return sniffed
    return None


def resolve_loader(
    source_path: str | Path,
    mime_type: str | None,
    *,
    filename: str | None = None,
) -> BaseLoader:
    """Loader for a stored blob, or raise ``UnsupportedMimeType``."""
    path = str(source_path)
    mime = _resolve_mime(path, mime_type, filename)
    if mime is None:
        raise UnsupportedMimeType(
            f"no loader for mime {mime_type!r} / filename {filename!r}"
        )
    return _LOADERS[mime](path)
