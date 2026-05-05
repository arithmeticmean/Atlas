"""Disk-backed implementation of the DocumentStore port.

Streams each document's raw bytes to a single file under a base directory,
named by its ``document_id``. Size and sha256 are computed in the same
streaming pass, so the payload is read only once. I/O runs in a thread so it
never blocks the event loop.
"""

import asyncio
import hashlib
from pathlib import Path
from typing import BinaryIO

from storage.store.document import DocumentStore, StoredBlob

_READ_SIZE = 1024 * 1024


class DiskDocumentStore(DocumentStore):
    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)

    def _path(self, document_id: str) -> Path:
        return self._base / document_id

    async def add(self, document_id: str, source: BinaryIO) -> StoredBlob:
        return await asyncio.to_thread(
            self._write, self._path(document_id), source
        )

    async def delete(self, document_id: str) -> None:
        await asyncio.to_thread(
            self._path(document_id).unlink, missing_ok=True
        )

    @staticmethod
    def _write(path: Path, source: BinaryIO) -> StoredBlob:
        path.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        size = 0
        with path.open("wb") as dst:
            while chunk := source.read(_READ_SIZE):
                dst.write(chunk)
                hasher.update(chunk)
                size += len(chunk)
        return StoredBlob(
            path=str(path),
            size_bytes=size,
            content_hash=hasher.hexdigest(),
        )
