"""Turn validation failures into messages a person can act on.

The library's own wording, error types and class names never leave the server.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError

from atlas.services.errors import InvalidInput

_SOURCES = {"body", "query", "path", "form", "header", "cookie"}
_NAMES = {"urls": "URLs", "url": "URL", "api": "API"}
_FALLBACK = "This value isn't valid."
_MESSAGES = {
    "missing": "This is required.",
    "string_too_short": "Enter at least {min_length} characters.",
    "string_too_long": "Use at most {max_length} characters.",
    "too_short": "Add at least {min_length}.",
    "too_long": "Add at most {max_length}.",
    "greater_than": "Must be more than {gt}.",
    "greater_than_equal": "Must be {ge} or more.",
    "less_than": "Must be less than {lt}.",
    "less_than_equal": "Must be {le} or less.",
    "int_parsing": "Enter a whole number.",
    "int_type": "Enter a whole number.",
    "int_from_float": "Enter a whole number.",
    "float_parsing": "Enter a number.",
    "float_type": "Enter a number.",
    "bool_parsing": "Choose yes or no.",
    "bool_type": "Choose yes or no.",
    "string_type": "Enter some text.",
    "literal_error": "Choose one of the available options.",
    "json_invalid": "The request couldn't be read.",
}


def field_errors(errors: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """One plain message per field, keyed by the field's name."""
    fields: dict[str, str] = {}
    for error in errors:
        parts = [str(p) for p in error["loc"] if p not in _SOURCES]
        fields.setdefault(".".join(parts), _message(error))
    return fields


def summary(fields: Mapping[str, str]) -> str:
    """The first problem as a sentence, for places without a form."""
    field, message = next(iter(fields.items()))
    extra = len(fields) - 1
    more = f" ({extra} more to fix)" if extra else ""
    return f"{_label(field)}: {message}{more}" if field else message + more


def invalid(exc: ValidationError, *, code: str) -> InvalidInput:
    fields = field_errors(exc.errors())
    return InvalidInput(summary(fields), code=code, fields=fields)


def _message(error: Mapping[str, Any]) -> str:
    kind, context = error["type"], error.get("ctx") or {}
    if kind == "value_error":  # raised by our own validators
        return str(context.get("error", _FALLBACK))
    if kind.startswith("url"):
        return "Enter a full address, like https://example.com."
    if kind == "string_too_short" and context.get("min_length") == 1:
        return "This can't be empty."
    return _MESSAGES.get(kind, _FALLBACK).format(**context)


def _label(field: str) -> str:
    name = next(
        (p for p in reversed(field.split(".")) if not p.isdigit()), field
    )
    words = [_NAMES.get(word, word) for word in name.split("_")]
    label = " ".join(words)
    return label[0].upper() + label[1:] if label else label
