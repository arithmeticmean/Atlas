"""Read a file as ``(page, text)`` sections, one at a time.

A page of 0 means the format has no pages. Large PDFs and text files are never
held whole in memory; HTML is, because BeautifulSoup needs the full document.
"""

import codecs
import io
from collections.abc import Iterator
from functools import partial
from typing import BinaryIO

import chardet
from bs4 import BeautifulSoup
from pypdf import PdfReader

from atlas.core.parsing.errors import UnreadableFile

Section = tuple[int, str]

_BLOCK_SIZE = 1024 * 1024
_NON_CONTENT_TAGS = ("script", "style", "noscript", "template")


def read_text(content: BinaryIO) -> Iterator[Section]:
    text = io.TextIOWrapper(
        content, encoding=_detect_encoding(content), errors="replace"
    )
    try:
        # Finish the current line, so a block never ends halfway through it.
        while section := text.read(_BLOCK_SIZE) + text.readline(_BLOCK_SIZE):
            if "\0" in section:
                raise UnreadableFile("file contains binary data")
            yield 0, section
    finally:
        text.detach()  # otherwise closing the wrapper closes the caller's file


def read_pdf(content: BinaryIO) -> Iterator[Section]:
    for number, page in enumerate(PdfReader(content).pages, start=1):
        yield number, page.extract_text() or ""


def read_html(content: BinaryIO) -> Iterator[Section]:
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(_NON_CONTENT_TAGS):
        tag.decompose()
    yield 0, soup.get_text("\n", strip=True)


def _detect_encoding(content: BinaryIO) -> str:
    """UTF-8 if the whole file decodes as it, otherwise chardet's guess."""
    encoding: str | None = "utf-8-sig"
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    try:
        for block in iter(partial(content.read, _BLOCK_SIZE), b""):
            decoder.decode(block)
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        content.seek(0)
        encoding = chardet.detect(content.read(_BLOCK_SIZE))["encoding"]
    content.seek(0)
    return encoding or "latin-1"
