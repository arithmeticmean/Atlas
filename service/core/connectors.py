"""Connectors: pull documents from external origins into intake.

A connector is just *fetch -> store*: a :class:`Source` yields the bytes of
each document it finds, and :class:`ConnectorService` hands each to
``DocumentService.store`` (persist + queue). Every origin reduces to the same
two steps -- which is why upload and connectors share one code path.

Sources are async (network I/O) and resilient: a per-item failure yields a
``FetchedDocument`` carrying an ``error`` instead of raising, so one bad URL or
Drive file does not sink the whole batch. ``ConnectorService`` stores each item
in its own unit of work and returns a per-item :class:`ImportResult`.
"""

import io
import mimetypes
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlparse

from service.core.document import DocumentService

DocumentServiceUoW = Callable[
    [], AbstractAsyncContextManager[DocumentService]
]


@dataclass(slots=True)
class FetchedDocument:
    """One document produced by a :class:`Source`.

    On success ``stream`` is set; on a per-item fetch failure ``error`` is set
    and ``stream`` is ``None``.
    """

    filename: str
    mime_type: str | None
    stream: BinaryIO | None = None
    error: str | None = None


@dataclass(slots=True)
class ImportResult:
    filename: str
    status: str  # a document status ("queued", ...) or "error"
    document_id: str | None = None
    error: str | None = None


class Source(ABC):
    @abstractmethod
    def fetch(self) -> AsyncIterator[FetchedDocument]:
        """Yield each document this source provides (success or error item)."""

    async def check_health(self) -> tuple[bool, str]:
        """Lightweight reachability / credential check. Default: assume ok."""
        return (True, "ok")


class LocalDirectorySource(Source):
    """Every file under a directory (recursively by default)."""

    def __init__(self, path: str | Path, *, pattern: str = "**/*") -> None:
        self._root = Path(path)
        self._pattern = pattern

    async def check_health(self) -> tuple[bool, str]:
        if self._root.is_dir():
            return (True, f"{self._root} exists")
        return (False, f"not a directory: {self._root}")

    async def fetch(self) -> AsyncIterator[FetchedDocument]:
        for entry in sorted(self._root.glob(self._pattern)):
            if not entry.is_file():
                continue
            mime, _ = mimetypes.guess_type(entry.name)
            yield FetchedDocument(
                filename=entry.name,
                mime_type=mime,
                stream=entry.open("rb"),
            )


class UrlSource(Source):
    """Documents downloaded from a list of HTTP(S) URLs."""

    def __init__(
        self, urls: list[str], *, timeout: float = 30.0
    ) -> None:
        self._urls = list(urls)
        self._timeout = timeout

    async def fetch(self) -> AsyncIterator[FetchedDocument]:
        import httpx

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=self._timeout
        ) as client:
            for url in self._urls:
                try:
                    yield await self._fetch_one(client, url)
                except Exception as exc:
                    yield FetchedDocument(
                        filename=_url_filename(url),
                        mime_type=None,
                        error=str(exc),
                    )

    async def check_health(self) -> tuple[bool, str]:
        import httpx

        bad: list[str] = []
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=self._timeout
        ) as client:
            for url in self._urls:
                try:
                    resp = await client.head(url)
                    if resp.status_code >= 400:
                        bad.append(f"{url} ({resp.status_code})")
                except Exception as exc:
                    bad.append(f"{url} ({exc})")
        if bad:
            return (False, "unreachable: " + "; ".join(bad))
        return (True, f"{len(self._urls)} url(s) reachable")

    async def _fetch_one(self, client: object, url: str) -> FetchedDocument:
        resp = await client.get(url)  # type: ignore[attr-defined]
        resp.raise_for_status()
        mime = (resp.headers.get("content-type") or "").split(";")[0].strip()
        return FetchedDocument(
            filename=_url_filename(url, mime or None),
            mime_type=mime or None,
            stream=io.BytesIO(resp.content),
        )


# Google-native types can't be downloaded directly; export to a format our
# loaders understand (see ingest/loaders.py).
_GOOGLE_EXPORT: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
}


class GoogleDriveSource(Source):
    """Files fetched from Google Drive by id, using a caller-supplied OAuth
    access token (bring-your-own-token; no server-side OAuth flow).

    Google-native docs are exported to a loader-friendly format; regular files
    are downloaded as-is. ``base_url`` is injectable for testing.
    """

    def __init__(
        self,
        *,
        access_token: str,
        file_ids: list[str],
        base_url: str = "https://www.googleapis.com/drive/v3",
        timeout: float = 60.0,
    ) -> None:
        self._token = access_token
        self._ids = list(file_ids)
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def fetch(self) -> AsyncIterator[FetchedDocument]:
        import httpx

        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=headers
        ) as client:
            for file_id in self._ids:
                try:
                    yield await self._fetch_one(client, file_id)
                except Exception as exc:
                    yield FetchedDocument(
                        filename=file_id, mime_type=None, error=str(exc)
                    )

    async def _fetch_one(
        self, client: object, file_id: str
    ) -> FetchedDocument:
        meta = await client.get(  # type: ignore[attr-defined]
            f"{self._base}/files/{file_id}",
            params={"fields": "id,name,mimeType"},
        )
        meta.raise_for_status()
        info = meta.json()
        name = info.get("name") or file_id
        gmime = info.get("mimeType") or ""

        if gmime.startswith("application/vnd.google-apps."):
            target = _GOOGLE_EXPORT.get(gmime)
            if target is None:
                return FetchedDocument(
                    filename=name,
                    mime_type=None,
                    error=f"unsupported Google type {gmime!r}",
                )
            export_mime, ext = target
            resp = await client.get(  # type: ignore[attr-defined]
                f"{self._base}/files/{file_id}/export",
                params={"mimeType": export_mime},
            )
            resp.raise_for_status()
            filename = name if name.endswith(ext) else name + ext
            return FetchedDocument(
                filename=filename,
                mime_type=export_mime,
                stream=io.BytesIO(resp.content),
            )

        resp = await client.get(  # type: ignore[attr-defined]
            f"{self._base}/files/{file_id}", params={"alt": "media"}
        )
        resp.raise_for_status()
        return FetchedDocument(
            filename=name,
            mime_type=gmime or None,
            stream=io.BytesIO(resp.content),
        )

    async def check_health(self) -> tuple[bool, str]:
        import httpx

        if not self._ids:
            return (False, "no file ids configured")
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=headers
        ) as client:
            try:
                resp = await client.get(
                    f"{self._base}/files/{self._ids[0]}",
                    params={"fields": "id"},
                )
                resp.raise_for_status()
                return (True, "token valid; file reachable")
            except Exception as exc:
                return (False, str(exc))


class ConnectorService:
    def __init__(self, *, documents_uow: DocumentServiceUoW) -> None:
        self._documents_uow = documents_uow

    async def import_from(
        self, source: Source, *, project_id: str
    ) -> list[ImportResult]:
        """Store every document from ``source`` into ``project_id``; one unit
        of work per item so a single failure neither rolls back the batch nor
        holds one long transaction. Returns a per-item outcome."""
        results: list[ImportResult] = []
        async for item in source.fetch():
            results.append(await self._store_one(item, project_id=project_id))
        return results

    async def _store_one(
        self, item: FetchedDocument, *, project_id: str
    ) -> ImportResult:
        if item.error is not None or item.stream is None:
            return ImportResult(
                filename=item.filename,
                status="error",
                error=item.error or "no content fetched",
            )
        try:
            with item.stream as stream:
                async with self._documents_uow() as documents:
                    meta = await documents.store(
                        project_id=project_id,
                        filename=item.filename,
                        mime_type=item.mime_type,
                        source=stream,
                    )
            return ImportResult(
                filename=item.filename,
                status=meta.status,
                document_id=meta.id,
            )
        except Exception as exc:
            return ImportResult(
                filename=item.filename, status="error", error=str(exc)
            )


def _url_filename(url: str, mime: str | None = None) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    if not name or "." not in name:
        ext = mimetypes.guess_extension(mime) if mime else None
        name = (name or "download") + (ext or "")
    return name
