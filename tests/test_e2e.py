"""The backend end to end: a real server process, real HTTP, real SQLite and
LanceDB. Only the AI models are fake."""

import io
import json
import sqlite3
import time
import uuid
import zipfile
from collections.abc import Iterator

import httpx
import pytest

from tests.conftest import AtlasServer, FakeProvider

pytestmark = pytest.mark.e2e

Headers = dict[str, str]
LEASE = b"The lease says pets need written consent from the landlord.\n\n" * 12


@pytest.fixture(scope="module")
def client(server: AtlasServer) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=server.base, timeout=30) as http:
        yield http


@pytest.fixture(scope="module")
def owner(server: AtlasServer, client: httpx.Client) -> Headers:
    assert client.get("/setup/status").json()["needs_setup"]
    account = {"email": "owner@example.com", "password": "ownerpass1"}
    wrong = client.post("/setup", json={"token": "wrong", **account})
    assert wrong.status_code == 403

    response = client.post(
        "/setup", json={"token": server.setup_token(), **account}
    )
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "owner"
    client.cookies.clear()
    return _bearer(response.json()["access_token"])


@pytest.fixture(autouse=True)
def fresh_provider(provider: FakeProvider) -> Iterator[None]:
    provider.reset()
    yield
    provider.reset()


@pytest.fixture
def project(client: httpx.Client, owner: Headers) -> str:
    name = f"Project {uuid.uuid4().hex[:8]}"
    response = client.post("/projects", headers=owner, json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def _bearer(token: str) -> Headers:
    return {"Authorization": f"Bearer {token}"}


def _join(
    client: httpx.Client, owner: Headers, project_id: str | None = None
) -> tuple[str, Headers]:
    grants = (
        [{"project_id": project_id, "role": "member"}] if project_id else []
    )
    invite = client.post("/invites", headers=owner, json={"projects": grants})
    name = f"user{uuid.uuid4().hex[:8]}"
    accepted = client.post(
        "/invites/accept",
        json={
            "token": invite.json()["token"],
            "email": f"{name}@example.com",
            "username": name,
            "password": "memberpass1",
        },
    )
    assert accepted.status_code == 201, accepted.text
    client.cookies.clear()
    body = accepted.json()
    return body["user"]["id"], _bearer(body["access_token"])


def _upload(
    client: httpx.Client,
    headers: Headers,
    project_id: str,
    name: str = "lease.txt",
    content: bytes = LEASE,
    **data: object,
) -> httpx.Response:
    return client.post(
        f"/projects/{project_id}/documents",
        headers=headers,
        files={"file": (name, content, "text/plain")},
        data=data,
    )


def _indexed(
    client: httpx.Client, headers: Headers, project_id: str, document_id: str
) -> dict:
    url = f"/projects/{project_id}/documents/{document_id}"
    for _ in range(150):
        document = client.get(url, headers=headers).json()
        if document["status"] in ("indexed", "failed"):
            assert document["status"] == "indexed"
            return document
        time.sleep(0.1)
    raise AssertionError("the document was never indexed")


def _ready_document(
    client: httpx.Client, headers: Headers, project_id: str
) -> dict:
    uploaded = _upload(client, headers, project_id)
    assert uploaded.status_code == 202, uploaded.text
    return _indexed(client, headers, project_id, uploaded.json()["id"])


def _new_chat(client: httpx.Client, headers: Headers, project_id: str) -> str:
    response = client.post(
        f"/projects/{project_id}/chats", headers=headers, json={}
    )
    assert response.status_code == 201
    return response.json()["id"]


def _send(
    client: httpx.Client,
    headers: Headers,
    project_id: str,
    chat_id: str,
    content: str,
) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name = ""
    with client.stream(
        "POST",
        f"/projects/{project_id}/chats/{chat_id}/messages",
        headers=headers,
        json={"content": content},
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                events.append((name, json.loads(line.removeprefix("data: "))))
    return events


def _event(events: list[tuple[str, dict]], name: str) -> dict:
    return next(data for kind, data in events if kind == name)


def test_requests_need_a_session(client: httpx.Client, owner: Headers) -> None:
    response = httpx.get(f"{client.base_url}projects")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith(
        "application/problem+json"
    )
    assert response.json()["request_id"] == response.headers["x-request-id"]

    again = client.post(
        "/setup",
        json={"token": "x", "email": "b@example.com", "password": "password1"},
    )
    assert again.status_code == 409


def test_upload_index_and_chat_with_citations(
    client: httpx.Client,
    owner: Headers,
    project: str,
    provider: FakeProvider,
) -> None:
    document = _ready_document(client, owner, project)
    duplicate = _upload(client, owner, project, name="copy.txt")
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == document["id"]

    chat = _new_chat(client, owner, project)
    events = _send(client, owner, project, chat, "Do pets need consent?")
    kinds = [kind for kind, _ in events]
    assert kinds[:2] == ["message.created", "retrieval"]
    assert kinds[-2:] == ["message.completed", "chat.updated"]

    answer = _event(events, "message.completed")["message"]
    assert answer["content"] == "Pets need written consent [1]."
    assert [c["n"] for c in answer["citations"]] == [1]
    assert answer["citations"][0]["document_title"] == "lease.txt"
    assert _event(events, "chat.updated")["chat"]["title"] == "Lease rules"

    # A follow-up costs one model call and carries the conversation.
    provider.chat_calls.clear()
    _send(client, owner, project, chat, "and for cats?")
    assert len(provider.chat_calls) == 1
    assert "Do pets need consent?" in str(provider.chat_calls[0]["messages"])

    stored = client.get(
        f"/projects/{project}/chats/{chat}/messages", headers=owner
    ).json()["items"]
    assert len(stored) == 4
    assert all(message["status"] == "complete" for message in stored)


def test_normal_conversation_has_no_sources(
    client: httpx.Client,
    owner: Headers,
    project: str,
    provider: FakeProvider,
) -> None:
    _ready_document(client, owner, project)
    provider.reply = "Hello! How can I help?"
    chat = _new_chat(client, owner, project)

    events = _send(client, owner, project, chat, "hi there")

    assert _event(events, "retrieval")["citations"]  # the model saw them
    answer = _event(events, "message.completed")["message"]
    assert answer["content"] == "Hello! How can I help?"
    assert answer["citations"] == []


def test_chat_works_in_an_empty_project(
    client: httpx.Client, owner: Headers, project: str, provider: FakeProvider
) -> None:
    provider.reply = "Paris is the capital of France."
    chat = _new_chat(client, owner, project)
    events = _send(client, owner, project, chat, "Capital of France?")
    answer = _event(events, "message.completed")["message"]
    assert answer["content"] == provider.reply


def test_model_failure_is_saved_and_explained(
    client: httpx.Client, owner: Headers, project: str, provider: FakeProvider
) -> None:
    provider.fail = True
    chat = _new_chat(client, owner, project)
    events = _send(client, owner, project, chat, "Will this fail?")
    error = _event(events, "error")
    assert "secret detail" not in error["message"]
    assert "provider" in error["message"].lower()
    newest = client.get(
        f"/projects/{project}/chats/{chat}/messages",
        headers=owner,
        params={"limit": 1},
    ).json()["items"][0]
    assert newest["status"] == "failed"


@pytest.mark.parametrize(
    ("name", "content"),
    [
        (".env", b"SECRET=value\n"),
        ("server.pem", b"-----BEGIN PRIVATE KEY-----\nabc\n"),
    ],
)
def test_credential_files_are_refused(
    client: httpx.Client,
    owner: Headers,
    project: str,
    name: str,
    content: bytes,
) -> None:
    response = _upload(client, owner, project, name=name, content=content)
    assert response.status_code == 415


def test_a_disguised_file_is_refused(
    client: httpx.Client, owner: Headers, project: str
) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("inner.txt", "x" * 300)
    response = _upload(
        client, owner, project, name="notes.txt", content=archive.getvalue()
    )
    assert response.status_code == 415


def test_access_control(
    client: httpx.Client, owner: Headers, project: str
) -> None:
    _, member = _join(client, owner, project)
    _, outsider = _join(client, owner)

    assert client.get(f"/projects/{project}", headers=member).is_success
    assert (
        client.get(f"/projects/{project}", headers=outsider).status_code == 404
    )
    assert client.get("/system/settings", headers=member).status_code == 403
    assert (
        client.post(
            f"/projects/{project}/connectors",
            headers=member,
            json={
                "type": "url",
                "name": "x",
                "config": {"urls": ["http://x"]},
            },
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/users/lookup", headers=member, params={"q": "example"}
        ).status_code
        == 403
    )

    chat = _new_chat(client, owner, project)
    url = f"/projects/{project}/chats/{chat}"
    assert client.get(url, headers=member).status_code == 404


def test_project_admin_lookup_stays_in_their_projects(
    client: httpx.Client, owner: Headers, project: str
) -> None:
    admin_id, admin = _join(client, owner, project)
    teammate_id, _ = _join(client, owner, project)
    outsider_id, _ = _join(client, owner)
    promoted = client.patch(
        f"/projects/{project}/members/{admin_id}",
        headers=owner,
        json={"role": "admin"},
    )
    assert promoted.status_code == 200

    found = client.get(
        "/users/lookup", headers=admin, params={"q": "example"}
    ).json()
    ids = {user["id"] for user in found}
    assert teammate_id in ids
    assert outsider_id not in ids


def test_tags_filter_and_pagination(
    client: httpx.Client, owner: Headers, project: str
) -> None:
    for index in range(3):
        response = _upload(
            client,
            owner,
            project,
            name=f"file-{index}.txt",
            content=f"Unique document number {index}.\n".encode() * 5,
            tags=["Legal", " legal "] if index == 0 else ["other"],
        )
        assert response.status_code == 202, response.text

    url = f"/projects/{project}/documents"
    first = client.get(url, headers=owner, params={"limit": 2}).json()
    assert len(first["items"]) == 2 and first["next_cursor"] == "2"
    rest = client.get(
        url, headers=owner, params={"limit": 2, "cursor": "2"}
    ).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None

    tagged = client.get(url, headers=owner, params={"tag": "LEGAL"}).json()
    assert [d["title"] for d in tagged["items"]] == ["file-0.txt"]
    assert tagged["items"][0]["tags"] == ["legal"]
    counts = client.get(f"/projects/{project}/tags", headers=owner).json()
    assert counts == [
        {"name": "legal", "count": 1},
        {"name": "other", "count": 2},
    ]


def test_api_keys_stay_secret_and_with_their_address(
    client: httpx.Client,
    server: AtlasServer,
    owner: Headers,
    provider: FakeProvider,
    other_provider: FakeProvider,
) -> None:
    secret = "sk-e2e-very-secret"
    saved = client.patch(
        "/system/settings",
        headers=owner,
        json={"secrets": {"llm_api_key": secret}},
    )
    assert saved.status_code == 200
    assert secret not in saved.text
    assert "llm_api_key" in saved.json()["secrets_set"]
    with sqlite3.connect(server.data / "db" / "atlas.db") as db:
        stored = db.execute("select secrets from instance_settings").fetchone()
    assert secret not in stored[0]

    # Listing models on its own address uses the saved key...
    provider.auth_headers.clear()
    listed = client.post(
        "/system/settings/models",
        headers=owner,
        json={"provider": "openai_compatible", "base_url": provider.url},
    )
    assert listed.json()["models"] == ["model-a", "model-b"]
    assert any(secret in header for header in provider.auth_headers)

    # ...and never on another one.
    other_provider.reset()
    client.post(
        "/system/settings/models",
        headers=owner,
        json={"provider": "openai_compatible", "base_url": other_provider.url},
    )
    assert other_provider.auth_headers
    assert not any(secret in h for h in other_provider.auth_headers)

    for path, method in (
        ("/system/settings", client.patch),
        ("/system/settings/test", client.post),
    ):
        other_provider.reset()
        moved = method(
            path,
            headers=owner,
            json={"values": {"llm_base_url": other_provider.url}},
        )
        assert moved.status_code == 422
        assert moved.json()["code"] == "api_key_required"
        assert not other_provider.auth_headers


def test_errors_are_plain_language(
    client: httpx.Client, owner: Headers
) -> None:
    responses = [
        client.patch(
            "/system/settings",
            headers=owner,
            json={"values": {"chunk_overlap": 99999}},
        ),
        client.patch(
            "/system/settings",
            headers=owner,
            json={"values": {"retrieval_k": "many"}},
        ),
        client.post("/projects", headers=owner, json={"name": ""}),
        client.post("/auth/login", json={"email": "a"}),
    ]
    for response in responses:
        assert response.status_code == 422
        text = response.text.lower()
        for leak in ("pydantic", "validation error", "input_value", "ctx"):
            assert leak not in text
    assert responses[0].json()["errors"] == [
        {
            "field": "chunk_overlap",
            "message": "Must be smaller than the chunk size.",
        }
    ]


def test_restart_keeps_everything(
    client: httpx.Client,
    server: AtlasServer,
    owner: Headers,
    project: str,
) -> None:
    document = _ready_document(client, owner, project)

    server.stop()
    server.start()

    assert not client.get("/setup/status").json()["needs_setup"]
    assert client.get("/auth/me", headers=owner).status_code == 200
    chat = _new_chat(client, owner, project)
    events = _send(client, owner, project, chat, "Do pets need consent?")
    citation = _event(events, "message.completed")["message"]["citations"][0]
    assert citation["document_id"] == document["id"]
