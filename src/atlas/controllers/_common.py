"""HTTP plumbing shared by every controller: the service container, the
caller, list pagination, error documentation and SSE responses."""

from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from typing import Annotated, Any, Generic, TypeVar

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from atlas.container import Container
from atlas.repository.base import Paged, PageRequest
from atlas.services.access import Caller
from atlas.services.errors import InvalidInput, InvalidToken

# The refresh token travels only in this cookie, scoped to the auth routes,
# so page JavaScript never sees it and no other route receives it.
REFRESH_COOKIE = "atlas_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # don't let nginx buffer the stream
}


class ResponseModel(BaseModel):
    """Built directly from entities and service results."""

    model_config = ConfigDict(from_attributes=True)


# --- errors -----------------------------------------------------------------


class FieldError(BaseModel):
    field: str
    message: str


class Problem(BaseModel):
    """RFC 9457 problem details: the body of every error response."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    code: str = Field(examples=["project_not_found", "email_taken"])
    errors: list[FieldError] | None = None
    request_id: str | None = None


_PROBLEM_DESCRIPTIONS = {
    400: "Bad request",
    401: "Not authenticated",
    403: "Not allowed",
    404: "Not found, or not visible to the caller",
    409: "Conflicts with the current state",
    413: "Too large",
    415: "Unsupported file type",
    422: "Validation failed",
    501: "Not available yet",
    502: "The model provider could not answer",
    503: "Not ready; see Retry-After",
}


def problems(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Document the error statuses a route can answer with."""
    return {
        code: {
            "model": Problem,
            "description": _PROBLEM_DESCRIPTIONS[code],
            "content": {"application/problem+json": {}},
        }
        for code in codes
    }


# --- lists ------------------------------------------------------------------

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)


class Page(BaseModel, Generic[T]):
    """Every list: never a bare array, so fields can be added later."""

    items: list[T]
    next_cursor: str | None = None


class PageQuery(BaseModel):
    """Cursor pagination; list endpoints extend this with their filters."""

    cursor: str | None = None
    limit: int = Field(default=25, ge=1, le=100)


def page_request(query: PageQuery) -> PageRequest:
    cursor = query.cursor or "0"
    if not cursor.isdecimal():
        raise InvalidInput("invalid cursor", code="invalid_cursor")
    return PageRequest(offset=int(cursor), limit=query.limit)


def to_page(model: type[M], paged: Paged[Any]) -> Page[M]:
    """A service's page of results, each validated as ``model``."""
    page: type[Page[M]] = Page[model]  # type: ignore[valid-type]
    offset = paged.next_offset
    return page(
        items=[model.model_validate(item) for item in paged.items],
        next_cursor=None if offset is None else str(offset),
    )


# --- dependencies -----------------------------------------------------------


def _get_services(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


Services = Annotated[Container, Depends(_get_services)]

# auto_error=False so a missing header gets the same 401 as a bad token.
_bearer = HTTPBearer(auto_error=False)
_Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def _get_caller(services: Services, credentials: _Credentials) -> Caller:
    if credentials is None:
        raise InvalidToken("missing bearer token", code="not_authenticated")
    return services.auth.authenticate(credentials.credentials)


def _get_optional_caller(
    services: Services, credentials: _Credentials
) -> Caller | None:
    """For routes that work both signed in and signed out."""
    if credentials is None:
        return None
    return services.auth.authenticate(credentials.credentials)


CurrentCaller = Annotated[Caller, Depends(_get_caller)]
OptionalCaller = Annotated[Caller | None, Depends(_get_optional_caller)]


def require_ready(services: Services) -> None:
    """Gate for routes that depend on the vector index."""
    services.ai.require_ready()


# --- streaming --------------------------------------------------------------


async def sse_response(
    events: AsyncGenerator[T, None],
    encode: Callable[[T], tuple[str, str]],
) -> StreamingResponse:
    """Stream ``events`` as SSE. The first one is pulled before responding,
    so a failed precondition can still be a proper error status."""
    first = await anext(events)

    def frame(event: T) -> str:
        name, data = encode(event)
        return f"event: {name}\ndata: {data}\n\n"

    async def body() -> AsyncGenerator[str, None]:
        async with aclosing(events):
            yield frame(first)
            async for event in events:
                yield frame(event)

    return StreamingResponse(
        body(), media_type="text/event-stream", headers=_SSE_HEADERS
    )
