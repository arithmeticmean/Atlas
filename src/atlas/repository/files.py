"""Where uploaded files live: local disk, S3, GCS, Azure or memory, by URL.

Two rules keep files and database rows in step, and both are just ordering:

* **save the file first, then the row.** A write is atomic -- an interrupted
  upload leaves nothing behind -- so a row never points at a missing file.
  If the request fails after the file is written, an unused file is left.
* **delete the row first (and commit), then the file.** Deleting the file
  first would lose it for good if the request then failed and the row came
  back.

``sweep`` removes the unused files either rule can leave behind.
"""

import asyncio
import hashlib
import tempfile
from collections.abc import AsyncGenerator, AsyncIterator, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath
from typing import BinaryIO, Protocol, cast

import obstore as obs
from obstore.exceptions import NotFoundError
from obstore.store import ObjectStore, from_url

_CHUNK = 1024 * 1024
# Reads up to this size stay in memory; larger ones spill to a temp file.
_SPOOL_IN_MEMORY = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class StoredFile:
    key: str
    size_bytes: int
    content_hash: str  # sha256, hex


class FileStore(Protocol):
    async def put(self, key: str, source: BinaryIO) -> StoredFile:
        """Write ``source`` under ``key``, hashing it in the same pass."""
        ...

    def open(self, key: str) -> AbstractAsyncContextManager[BinaryIO]:
        """A local, seekable copy: PDF and DOCX parsers seek constantly,
        which against a remote store would be a request per seek."""
        ...

    async def delete(self, key: str) -> None:
        """No error if absent."""
        ...

    async def sweep(self, *, keep: Iterable[str], before: datetime) -> int:
        """Delete files written before ``before`` whose key is not in
        ``keep``. Returns how many."""
        ...


class ObjectFileStore:
    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    @classmethod
    def from_url(cls, url: str) -> "ObjectFileStore":
        """``file:///path``, ``s3://bucket/prefix``, ``gs://``, ``az://``,
        ``memory://``."""
        if url.startswith("file:"):
            return cls(from_url(url, mkdir=True))
        return cls(from_url(url))

    @staticmethod
    def _key(key: str) -> str:
        # Keys are flat names. Taking the last component keeps every key
        # inside the store, and resolves the full paths older rows stored.
        name = PurePath(key).name
        if not name or name.startswith("."):
            raise ValueError(f"invalid file key: {key!r}")
        return name

    async def put(self, key: str, source: BinaryIO) -> StoredFile:
        hasher = hashlib.sha256()
        size = 0

        async def chunks() -> AsyncIterator[bytes]:
            nonlocal size
            while chunk := await asyncio.to_thread(source.read, _CHUNK):
                hasher.update(chunk)
                size += len(chunk)
                yield chunk

        await obs.put_async(self._store, self._key(key), chunks())
        return StoredFile(key, size, hasher.hexdigest())

    @asynccontextmanager
    async def open(self, key: str) -> AsyncGenerator[BinaryIO, None]:
        try:
            result = await obs.get_async(self._store, self._key(key))
        except NotFoundError as exc:
            raise FileNotFoundError(key) from exc
        spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_IN_MEMORY)
        try:
            async for chunk in result.stream(min_chunk_size=_CHUNK):
                await asyncio.to_thread(spool.write, chunk)
            spool.seek(0)
            yield cast(BinaryIO, spool)
        finally:
            spool.close()

    async def delete(self, key: str) -> None:
        try:
            await obs.delete_async(self._store, self._key(key))
        except (FileNotFoundError, NotFoundError):
            pass  # the local store raises the builtin, remote ones their own

    async def sweep(self, *, keep: Iterable[str], before: datetime) -> int:
        kept = {PurePath(key).name for key in keep}
        unused = [
            meta["path"]
            async for batch in obs.list(self._store)
            for meta in batch
            # Only flat names are Atlas keys; anything nested is not ours.
            if "/" not in meta["path"]
            and meta["path"] not in kept
            and meta["last_modified"] < before
        ]
        for key in unused:
            await self.delete(key)
        return len(unused)
