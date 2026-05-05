"""Raw-document store port.

The bytes of an ingested document as they landed on disk (or any blob
backend). Metadata about the document lives in
:mod:`storage.store.document_meta`; this port only owns the raw payload. The
concrete implementation lives in ``storage/blob``.

The port accepts a binary stream (``BinaryIO``) rather than the web
framework's upload type, so storage stays framework-agnostic. Because the
payload is written in a single streaming pass, the store also reports the
blob's physical facts (``StoredBlob``) computed during that pass — no second
read to hash or size it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO


@dataclass(slots=True)
class StoredBlob:
    path: str
    size_bytes: int
    content_hash: str  # sha256 hex digest


class DocumentStore(ABC):
    @abstractmethod
    async def add(self, document_id: str, source: BinaryIO) -> StoredBlob:
        """Persist the bytes read from ``source``; return the stored blob."""

    @abstractmethod
    async def delete(self, document_id: str) -> None:
        """Remove the stored bytes for ``document_id`` (no error if absent)."""
