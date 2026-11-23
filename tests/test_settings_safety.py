"""Keys, encryption, and what errors are allowed to say."""

from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field, SecretStr, ValidationError

from atlas.config import InstanceSettings, MasterKey, Settings
from atlas.core.providers.factory import (
    ProviderError,
    chat_model_from,
    describe_error,
    endpoint_for,
)
from atlas.services.validation import field_errors, invalid, summary

_MOONSHOT = "https://api.moonshot.ai/v1"


def _settings(**values: Any) -> Settings:
    return Settings(vector_path="/unused", jwt_secret="test", **values)


def test_shared_key_is_never_sent_to_a_custom_address() -> None:
    official = _settings(
        llm_provider="openai", openai_api_key=SecretStr("sk-openai")
    )
    custom = _settings(
        llm_provider="openai",
        openai_api_key=SecretStr("sk-openai"),
        llm_base_url="https://other.example/v1",
    )
    assert endpoint_for(settings=official, kind="chat").api_key == "sk-openai"
    assert endpoint_for(settings=custom, kind="chat").api_key is None


@pytest.mark.parametrize(
    ("url", "model", "thinking", "disabled"),
    [
        (_MOONSHOT, "kimi-k2.6", False, True),
        (_MOONSHOT, "kimi-k2.6", True, False),
        (_MOONSHOT, "kimi-k2.7-code", False, False),
        ("http://localhost:1234/v1", "kimi-k2.6", False, False),
    ],
)
def test_thinking_is_only_switched_off_where_supported(
    url: str, model: str, thinking: bool, disabled: bool
) -> None:
    settings = _settings(
        llm_provider="openai_compatible",
        llm_base_url=url,
        llm_model=model,
        llm_api_key=SecretStr("key"),
        llm_thinking=thinking,
    )
    extra = chat_model_from(settings=settings).extra_body  # type: ignore[attr-defined]
    expected = {"thinking": {"type": "disabled"}} if disabled else None
    assert extra == expected


def test_master_key_encrypts_and_separates_purposes() -> None:
    key = MasterKey("k" * 40)
    token = key.encrypt("sk-secret")
    assert "sk-secret" not in token
    assert key.decrypt(token) == "sk-secret"
    assert MasterKey("x" * 40).decrypt(token) is None
    assert key.jwt_secret != MasterKey("x" * 40).jwt_secret


class _Status(Exception):
    def __init__(self, status: int) -> None:
        super().__init__("raw body with sk-secret-value")
        self.status_code = status


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_Status(401), "rejected this API key"),
        (_Status(404), "doesn't have that model"),
        (_Status(429), "rate limit"),
        (_Status(503), "having problems"),
        (httpx.ConnectError("boom sk-secret-value"), "Couldn't connect"),
        (TimeoutError(), "took too long"),
        (ProviderError("OpenAI needs an API key."), "needs an API key"),
        (RuntimeError("sk-secret-value"), "unexpected error"),
    ],
)
def test_provider_errors_are_safe_to_show(
    error: Exception, expected: str
) -> None:
    message = describe_error(error)
    assert expected in message
    assert "sk-secret-value" not in message


def test_wrapped_provider_error_is_still_understood() -> None:
    try:
        try:
            raise _Status(401)
        except _Status as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        assert "API key" in describe_error(outer)


def test_library_validation_error_never_reaches_a_person() -> None:
    class Client(BaseModel):
        api_key: str

    with pytest.raises(ValidationError) as caught:
        Client.model_validate({})
    message = describe_error(caught.value)
    assert "validation" not in message.lower()
    assert "Client" not in message


def test_overlap_error_points_at_the_field() -> None:
    with pytest.raises(ValidationError) as caught:
        InstanceSettings(chunk_size=100, chunk_overlap=100)
    error = invalid(caught.value, code="invalid_settings")
    assert error.fields == {
        "chunk_overlap": "Must be smaller than the chunk size."
    }
    assert "pydantic" not in error.detail.lower()


def test_validation_messages_are_written_for_people() -> None:
    class Form(BaseModel):
        name: str = Field(min_length=1)
        count: int = Field(ge=2)
        missing: str

    with pytest.raises(ValidationError) as caught:
        Form.model_validate({"name": "", "count": 1})
    fields = field_errors(caught.value.errors())
    assert fields == {
        "name": "This can't be empty.",
        "count": "Must be 2 or more.",
        "missing": "This is required.",
    }
    assert summary(fields) == "Name: This can't be empty. (2 more to fix)"
