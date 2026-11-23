"""The one place that says what each error means over HTTP.

Every error leaves as RFC 9457 ``application/problem+json``. A new service
error needs one line in ``_STATUS_BY_ERROR``.
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from atlas.core.parsing.errors import UnreadableFile, UnsupportedFile
from atlas.core.providers.factory import ProviderError
from atlas.repository.base import Conflict
from atlas.services import errors as service
from atlas.services.validation import field_errors, summary

logger = logging.getLogger(__name__)

_RETRY_AFTER_SECONDS = "30"
_STATUS_BY_ERROR: dict[type[service.ServiceError], int] = {
    service.InvalidCredentials: 401,
    service.InvalidToken: 401,
    service.PermissionDenied: 403,
    service.AccountDisabled: 403,
    service.NotFound: 404,
    service.AlreadyExists: 409,
    service.Busy: 409,
    service.FileTooLarge: 413,
    service.InvalidInput: 422,
    service.NotReady: 503,
}


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(service.ServiceError, _service_error)
    app.add_exception_handler(UnsupportedFile, _unsupported_file)
    app.add_exception_handler(UnreadableFile, _unreadable_file)
    app.add_exception_handler(Conflict, _conflict)
    app.add_exception_handler(ProviderError, _provider_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(NotImplementedError, _not_implemented)
    app.add_exception_handler(Exception, _unexpected)


def _problem(
    request: Request,
    status: int,
    code: str,
    detail: str | None,
    *,
    errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "code": code,
        "request_id": getattr(request.state, "request_id", None),
    }
    if errors:
        body["errors"] = errors
    return JSONResponse(
        body,
        status_code=status,
        headers=headers,
        media_type="application/problem+json",
    )


async def _service_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, service.ServiceError)
    status = next(
        code
        for kind, code in _STATUS_BY_ERROR.items()
        if isinstance(exc, kind)
    )
    headers: dict[str, str] = {}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if status == 503:
        headers["Retry-After"] = _RETRY_AFTER_SECONDS
    fields = exc.fields if isinstance(exc, service.InvalidInput) else {}
    return _problem(
        request,
        status,
        exc.code,
        exc.detail,
        errors=_field_list(fields),
        headers=headers,
    )


async def _unsupported_file(request: Request, exc: Exception) -> JSONResponse:
    return _problem(request, 415, "unsupported_file", str(exc))


async def _unreadable_file(request: Request, exc: Exception) -> JSONResponse:
    return _problem(request, 422, "unreadable_file", str(exc))


async def _conflict(request: Request, exc: Exception) -> JSONResponse:
    return _problem(request, 409, "conflict", "conflicts with existing data")


async def _provider_error(request: Request, exc: Exception) -> JSONResponse:
    return _problem(request, 502, "provider_error", str(exc))


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields = field_errors(exc.errors())
    return _problem(
        request,
        422,
        "validation_failed",
        summary(fields),
        errors=_field_list(fields),
    )


def _field_list(fields: dict[str, str]) -> list[dict[str, str]]:
    return [{"field": f, "message": m} for f, m in fields.items()]


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    code = HTTPStatus(exc.status_code).name.lower()
    return _problem(
        request,
        exc.status_code,
        code,
        str(exc.detail),
        headers=dict(exc.headers or {}),
    )


async def _not_implemented(request: Request, exc: Exception) -> JSONResponse:
    return _problem(request, 501, "not_implemented", str(exc))


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled error", exc_info=exc)
    return _problem(request, 500, "internal_error", "something went wrong")
