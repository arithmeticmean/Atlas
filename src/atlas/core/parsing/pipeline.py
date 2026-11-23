"""Turn a file into LangChain chunks, as a Runnable.

Configure it once, then give it only the file::

    chunker = FileChunker(chunk_size=1000, chunk_overlap=200)
    chunks = chunker.invoke(FileInput(content, filename="lease.pdf"))

For large files, loop over ``stream`` or ``astream``. They yield lists of
chunks because LCEL can join lists back into the ``invoke`` result.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any, BinaryIO

from langchain_core.documents import Document
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.utils.iter import batch_iterate

from atlas.core.parsing.detect import detect_format
from atlas.core.parsing.errors import ParsingError, UnreadableFile
from atlas.core.parsing.formats import FORMATS, FileFormat, FileKind

__all__ = [
    "FileChunker",
    "FileInput",
    "FileKind",
    "ensure_supported",
    "supported_file_types",
]


@dataclass(frozen=True, slots=True)
class FileInput:
    """A file to read. ``content`` must be a seekable binary stream."""

    content: BinaryIO
    filename: str | None = None
    mime_type: str | None = None


def ensure_supported(file: FileInput) -> None:
    """Raise ``UnsupportedFile`` unless Atlas can read this file, without
    reading it all. Blocking: use ``asyncio.to_thread`` in async code."""
    _detect(file)


def supported_file_types() -> dict[FileKind, list[str]]:
    """Supported extensions by group. Anything else is unsupported."""
    return {
        kind: sorted(f.extension for f in FORMATS.values() if f.kind is kind)
        for kind in FileKind
    }


def _detect(file: FileInput) -> FileFormat:
    return detect_format(
        file.content, filename=file.filename, mime_type=file.mime_type
    )


class FileChunker(Runnable[FileInput, list[Document]]):
    """Reads a file into LangChain chunks. See the module docstring."""

    def __init__(
        self, *, chunk_size: int, chunk_overlap: int, batch_size: int = 16
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._batch_size = batch_size

    def invoke(
        self,
        input: FileInput,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> list[Document]:
        return self._call_with_config(
            lambda file: list(self._chunks(file)), input, config
        )

    def stream(
        self,
        input: FileInput,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Iterator[list[Document]]:
        """An unsupported file raises here, a damaged one while iterating."""
        return batch_iterate(self._batch_size, self._chunks(input))

    async def astream(
        self,
        input: FileInput,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[list[Document]]:
        # Parsing blocks, so each step runs in a worker thread.
        batches = await asyncio.to_thread(self.stream, input, config)
        while batch := await asyncio.to_thread(next, batches, None):
            yield batch

    def _chunks(self, file: FileInput) -> Iterator[Document]:
        return self._split(file.content, _detect(file))

    def _split(
        self, content: BinaryIO, file_format: FileFormat
    ) -> Iterator[Document]:
        splitter = file_format.splitter(
            chunk_size=self._chunk_size, chunk_overlap=self._chunk_overlap
        )
        has_text = False
        try:
            for page, text in file_format.read(content):
                metadata = {"page": page, "file_type": file_format.extension}
                chunks = splitter.create_documents([text], [metadata])
                has_text = has_text or bool(chunks)
                yield from chunks
        except ParsingError:
            raise
        except Exception as exc:
            raise UnreadableFile(
                f"could not read {file_format.extension} file: {exc}"
            ) from exc
        if not has_text:
            raise UnreadableFile("file has no extractable text")
