"""Decide a file's format.

A file's name is only a claim, so Magika checks it against the content. When
they disagree, the content wins.
"""

import io
import mimetypes
from functools import lru_cache
from pathlib import PurePath
from typing import TYPE_CHECKING, BinaryIO

from atlas.core.parsing.errors import UnsupportedFile
from atlas.core.parsing.formats import FORMATS, FileFormat

if TYPE_CHECKING:
    from magika import Magika

# Never indexed, even though they look like text: search and chat would hand
# the credentials to everyone in the project.
_CREDENTIAL_EXTENSIONS = frozenset({".pem", ".key", ".p12", ".pfx"})


def detect_format(
    content: BinaryIO,
    *,
    filename: str | None = None,
    mime_type: str | None = None,
) -> FileFormat:
    path = PurePath((filename or "").lower())
    if _is_credential(path):
        raise UnsupportedFile("credential files are not indexed")

    content.seek(0)
    detected = _magika().identify_stream(_MagikaStream(content)).output
    if detected.label == "empty":
        raise UnsupportedFile("file is empty")

    claimed = FORMATS.get(path.suffix) or FORMATS.get(_extension_of(mime_type))
    if claimed and claimed.matches(detected):
        return claimed
    for extension in detected.extensions:
        if found := FORMATS.get(f".{extension}"):
            return found
    raise UnsupportedFile(f"unsupported file type: {detected.label}")


@lru_cache
def _magika() -> "Magika":
    # Imported here so only code that parses files pays for onnxruntime.
    from magika import Magika

    return Magika()


class _MagikaStream(io.BufferedIOBase, BinaryIO):
    """Magika only accepts ``BufferedIOBase``, which the spooled temp files
    of real uploads are not. Closing this leaves the wrapped file open."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def read(self, size: int | None = -1, /) -> bytes:
        return self._stream.read(-1 if size is None else size)

    def seek(self, offset: int, whence: int = 0, /) -> int:
        return self._stream.seek(offset, whence)

    def tell(self) -> int:
        return self._stream.tell()


def _is_credential(path: PurePath) -> bool:
    is_dotenv = f"{path.name}.".startswith(".env.")
    return is_dotenv or path.suffix in _CREDENTIAL_EXTENSIONS


def _extension_of(mime_type: str | None) -> str:
    essence = (mime_type or "").split(";", 1)[0].strip().lower()
    return mimetypes.guess_extension(essence) or ""
