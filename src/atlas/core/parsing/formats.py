"""Every supported file type, and how it is read and split.

To support another text type, add its extension to ``_TEXT_TYPES``.
"""

from collections.abc import Callable, Iterator
from enum import StrEnum
from typing import TYPE_CHECKING, BinaryIO, NamedTuple

from langchain_text_splitters import (
    Language,
    RecursiveCharacterTextSplitter,
    TextSplitter,
)

from atlas.core.parsing.readers import Section, read_html, read_pdf, read_text

if TYPE_CHECKING:
    from magika.types import ContentTypeInfo

Separators = tuple[str, ...]

_PARAGRAPHS: Separators = ("\n\n", "\n", " ", "")
_CONFIG_SECTIONS: Separators = ("\n[", *_PARAGRAPHS)
_ROWS: Separators = ("\n", " ", "")
_JSON: Separators = ("\n\n", "\n", ", ", " ", "")
_XML: Separators = ("\n\n", "\n", "><", " ", "")

_TEXT_TYPES: dict[Language | Separators, str] = {
    _PARAGRAPHS: ".txt .log .yaml .yml .css .sh .bash .sql .pl",
    _CONFIG_SECTIONS: ".toml .ini .cfg .conf",
    _ROWS: ".jsonl .csv .tsv",
    _JSON: ".json",
    _XML: ".xml",
    Language.MARKDOWN: ".md .markdown",
    Language.RST: ".rst",
    Language.LATEX: ".tex",
    Language.C: ".c",
    Language.CPP: ".h .cpp .cc .cxx .hpp .hh",
    Language.RUST: ".rs",
    Language.GO: ".go",
    Language.JAVA: ".java",
    Language.KOTLIN: ".kt",
    Language.SCALA: ".scala",
    Language.CSHARP: ".cs",
    Language.JS: ".js .mjs .cjs .jsx",
    Language.TS: ".ts .tsx",
    Language.PHP: ".php",
    Language.PYTHON: ".py",
    Language.RUBY: ".rb",
    Language.LUA: ".lua",
    Language.R: ".r",
    Language.POWERSHELL: ".ps1",
    Language.SWIFT: ".swift",
    Language.HASKELL: ".hs",
    Language.ELIXIR: ".ex .exs",
    Language.PROTO: ".proto",
    Language.SOL: ".sol",
    Language.COBOL: ".cob",
}


class FileKind(StrEnum):
    EXTRACTABLE = "extractable"  # parsed to get the text
    PLAIN_TEXT = "plain_text"  # already text


class FileFormat(NamedTuple):
    extension: str
    kind: FileKind
    read: Callable[[BinaryIO], Iterator[Section]]
    separators: Language | Separators = _PARAGRAPHS
    content_label: str | None = None  # required Magika label; None = any text

    def matches(self, detected: "ContentTypeInfo") -> bool:
        if self.content_label is None:
            return detected.is_text
        return detected.label == self.content_label

    def splitter(self, *, chunk_size: int, chunk_overlap: int) -> TextSplitter:
        if isinstance(self.separators, Language):
            return RecursiveCharacterTextSplitter.from_language(
                self.separators,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        return RecursiveCharacterTextSplitter(
            separators=list(self.separators),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )


FORMATS: dict[str, FileFormat] = {
    ".pdf": FileFormat(
        ".pdf", FileKind.EXTRACTABLE, read_pdf, content_label="pdf"
    ),
    ".html": FileFormat(".html", FileKind.EXTRACTABLE, read_html),
    ".htm": FileFormat(".htm", FileKind.EXTRACTABLE, read_html),
    **{
        extension: FileFormat(
            extension, FileKind.PLAIN_TEXT, read_text, separators
        )
        for separators, extensions in _TEXT_TYPES.items()
        for extension in extensions.split()
    },
}
