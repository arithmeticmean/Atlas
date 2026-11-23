"""What gets into the index, and what must never get in."""

import io
import zipfile

import pytest

from atlas.core.parsing.errors import ParsingError, UnsupportedFile
from atlas.core.parsing.pipeline import (
    FileChunker,
    FileInput,
    ensure_supported,
)
from tests.conftest import minimal_pdf


def _file(content: bytes, name: str) -> FileInput:
    return FileInput(io.BytesIO(content), filename=name)


def _chunker(batch_size: int = 16) -> FileChunker:
    return FileChunker(chunk_size=100, chunk_overlap=10, batch_size=batch_size)


def test_pdf_text_keeps_its_page_number() -> None:
    chunks = _chunker().invoke(
        _file(minimal_pdf("Pets need consent"), "a.pdf")
    )
    assert "Pets need consent" in chunks[0].page_content
    assert chunks[0].metadata == {"page": 1, "file_type": ".pdf"}


def test_code_is_split_as_code() -> None:
    source = "\n\n".join(
        f"def function_{n}():\n    return {n}\n" for n in range(20)
    )
    chunks = _chunker().invoke(_file(source.encode(), "module.py"))
    assert len(chunks) > 1
    assert chunks[0].metadata["file_type"] == ".py"
    assert chunks[0].page_content.startswith("def function_0")


def test_large_files_arrive_in_small_batches() -> None:
    text = ("A sentence that repeats through the document. " * 3 + "\n\n") * 90
    batches = list(
        _chunker(batch_size=8).stream(_file(text.encode(), "a.txt"))
    )
    assert len(batches) > 1
    assert all(len(batch) <= 8 for batch in batches)


@pytest.mark.parametrize(
    "name",
    [".env", ".env.production", "server.pem", "id.key", "cert.p12", "a.pfx"],
)
def test_credential_files_are_never_read(name: str) -> None:
    with pytest.raises(UnsupportedFile):
        ensure_supported(_file(b"SECRET=value\n", name))


def test_content_beats_a_false_extension() -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("inner.txt", "x" * 300)
    with pytest.raises(UnsupportedFile):
        ensure_supported(_file(archive.getvalue(), "notes.txt"))


def test_empty_file_is_refused() -> None:
    with pytest.raises(UnsupportedFile):
        ensure_supported(_file(b"", "empty.txt"))


def test_damaged_pdf_is_a_clean_error() -> None:
    whole = minimal_pdf("text")
    damaged = whole[: len(whole) // 2]
    with pytest.raises(ParsingError):
        _chunker().invoke(_file(damaged, "broken.pdf"))
