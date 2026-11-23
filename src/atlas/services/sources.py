"""Where connectors fetch documents from.

A source type is a config model (its JSON Schema draws the UI form), the
names of the fields that are secrets, and a class that fetches. Adding one
is one class plus one entry in ``SOURCE_TYPES``.

Downloads stream into a spooled temp file, so a large file never sits whole
in memory. A failed item is yielded with ``error`` set rather than raised,
so one bad URL does not stop the rest.
"""

import mimetypes
import tempfile
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Annotated, Any, BinaryIO, cast
from urllib.parse import unquote, urlparse

import httpx
from pydantic import BaseModel, Field, ValidationError

from atlas.services.errors import InvalidInput
from atlas.services.validation import invalid

_SPOOL_IN_MEMORY = 16 * 1024 * 1024
_DRIVE_API = "https://www.googleapis.com/drive/v3"
# Google-native files cannot be downloaded as they are; they are exported.
_DRIVE_EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
}


@dataclass(slots=True)
class Fetched:
    """One item from a source: its content (the caller closes it), or the
    reason it could not be fetched."""

    name: str
    mime_type: str | None
    content: BinaryIO | None = None
    error: str | None = None


class Source(ABC):
    @abstractmethod
    def fetch(self) -> AsyncIterator[Fetched]: ...

    @abstractmethod
    async def check(self) -> tuple[bool, str]:
        """Reachable, and the credentials work: (ok, what was found)."""


async def _spool(response: httpx.Response) -> BinaryIO:
    spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_IN_MEMORY)
    async for chunk in response.aiter_bytes():
        spool.write(chunk)
    spool.seek(0)
    return cast(BinaryIO, spool)


def _mime(response: httpx.Response) -> str | None:
    value = response.headers.get("content-type", "").split(";")[0].strip()
    return value or None


# --- URLs -------------------------------------------------------------------

HttpUrl = Annotated[str, Field(pattern=r"^https?://\S+$")]


class UrlConfig(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, description="Pages or files")


def _url_name(url: str, mime: str | None) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    if "." not in name:
        name = (name or "download") + (
            mimetypes.guess_extension(mime or "") or ""
        )
    return name


class UrlSource(Source):
    def __init__(self, config: UrlConfig) -> None:
        self._urls = config.urls

    async def fetch(self) -> AsyncIterator[Fetched]:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=60
        ) as client:
            for url in self._urls:
                try:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        mime = _mime(response)
                        item = Fetched(
                            _url_name(url, mime), mime, await _spool(response)
                        )
                except httpx.HTTPError as exc:
                    item = Fetched(_url_name(url, None), None, error=str(exc))
                yield item

    async def check(self) -> tuple[bool, str]:
        failing: list[str] = []
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=15
        ) as client:
            for url in self._urls:
                try:
                    (await client.head(url)).raise_for_status()
                except httpx.HTTPError as exc:
                    failing.append(f"{url}: {exc}")
        if failing:
            return False, "; ".join(failing)
        return True, f"{len(self._urls)} URL(s) reachable"


# --- Google Drive -----------------------------------------------------------


class DriveConfig(BaseModel):
    file_ids: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    access_token: str = Field(min_length=1, description="OAuth access token")
    base_url: str = _DRIVE_API


class DriveSource(Source):
    """Files by id, with a caller-supplied OAuth token."""

    def __init__(self, config: DriveConfig) -> None:
        self._config = config

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self._config.access_token}"},
            timeout=60,
        )

    async def fetch(self) -> AsyncIterator[Fetched]:
        async with self._client() as client:
            for file_id in self._config.file_ids:
                try:
                    item = await self._fetch_one(client, file_id)
                except httpx.HTTPError as exc:
                    item = Fetched(file_id, None, error=str(exc))
                yield item

    @staticmethod
    async def _fetch_one(client: httpx.AsyncClient, file_id: str) -> Fetched:
        meta = await client.get(
            f"/files/{file_id}", params={"fields": "name,mimeType"}
        )
        meta.raise_for_status()
        info = meta.json()
        name, kind = info.get("name") or file_id, info.get("mimeType") or ""
        mime: str | None
        if kind.startswith("application/vnd.google-apps."):
            if kind not in _DRIVE_EXPORTS:
                return Fetched(name, None, error=f"cannot export {kind}")
            mime, ext = _DRIVE_EXPORTS[kind]
            request = client.stream(
                "GET", f"/files/{file_id}/export", params={"mimeType": mime}
            )
            name = name if name.endswith(ext) else name + ext
        else:
            mime = kind or None
            request = client.stream(
                "GET", f"/files/{file_id}", params={"alt": "media"}
            )
        async with request as response:
            response.raise_for_status()
            return Fetched(name, mime, await _spool(response))

    async def check(self) -> tuple[bool, str]:
        async with self._client() as client:
            try:
                response = await client.get(
                    f"/files/{self._config.file_ids[0]}",
                    params={"fields": "id"},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                return False, str(exc)
        return True, "token valid; file reachable"


# --- the registry -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceType:
    key: str
    name: str
    description: str
    config_model: type[BaseModel]
    secret_fields: tuple[str, ...]
    build: Callable[[dict[str, Any]], Source]


SOURCE_TYPES: dict[str, SourceType] = {
    "url": SourceType(
        key="url",
        name="Web pages and files",
        description="Downloads each URL.",
        config_model=UrlConfig,
        secret_fields=(),
        build=lambda c: UrlSource(UrlConfig.model_validate(c)),
    ),
    "google_drive": SourceType(
        key="google_drive",
        name="Google Drive",
        description="Files by id; Google Docs are exported first.",
        config_model=DriveConfig,
        secret_fields=("access_token",),
        build=lambda c: DriveSource(DriveConfig.model_validate(c)),
    ),
}


def source_type(type_: str) -> SourceType:
    if type_ not in SOURCE_TYPES:
        raise InvalidInput(
            f"unknown connector type {type_!r}", code="unknown_type"
        )
    return SOURCE_TYPES[type_]


def build_source(type_: str, settings: dict[str, Any]) -> Source:
    """``settings`` is the config and the secrets together."""
    try:
        return source_type(type_).build(settings)
    except ValidationError as exc:
        raise invalid(exc, code="invalid_config") from exc
