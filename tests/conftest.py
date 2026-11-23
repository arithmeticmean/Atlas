"""Shared test tools.

Nothing here reaches a real model or your own data: every test runs in a
temporary folder, and "providers" are small fake servers on localhost.
"""

import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from atlas.config import BootstrapSettings
from atlas.repository.migrate import upgrade_to_head

DEFAULT_REPLY = "Pets need written consent [1]."
_safe_data_path: str | None = None


def pytest_configure() -> None:
    """Anything that forgets to pass a path still can't touch ~/.atlas."""
    global _safe_data_path
    _safe_data_path = tempfile.mkdtemp(prefix="atlas-tests-")
    os.environ["ATLAS_DATA_PATH"] = _safe_data_path


def pytest_unconfigure() -> None:
    if _safe_data_path:
        shutil.rmtree(_safe_data_path, ignore_errors=True)


class FakeProvider:
    """Speaks just enough of the OpenAI API, and records what it was sent."""

    def __init__(self) -> None:
        self.reply = DEFAULT_REPLY
        self.fail = False
        self.chat_calls: list[dict] = []
        self.auth_headers: list[str] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        threading.Thread(
            target=self._server.serve_forever, daemon=True
        ).start()
        self.url = f"http://127.0.0.1:{self._server.server_port}/v1"

    def reset(self) -> None:
        self.reply, self.fail = DEFAULT_REPLY, False
        self.chat_calls.clear()
        self.auth_headers.clear()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def _json(self, value: object, status: int = 200) -> None:
                body = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                provider.auth_headers.append(
                    self.headers.get("authorization", "")
                )
                models = [
                    {"id": m, "object": "model", "created": 1, "owned_by": "x"}
                    for m in ("model-a", "model-b")
                ]
                self._json({"object": "list", "data": models})

            def do_POST(self) -> None:
                length = int(self.headers["content-length"])
                body = json.loads(self.rfile.read(length))
                provider.auth_headers.append(
                    self.headers.get("authorization", "")
                )
                provider.chat_calls.append(body)
                if provider.fail:
                    self._json({"error": {"message": "secret detail"}}, 500)
                    return
                system = str(body["messages"][0]["content"])
                text = "Lease rules" if "short title" in system else None
                text = text or provider.reply
                if body.get("stream"):
                    self._stream(text)
                else:
                    self._json(_completion(text))

            def _stream(self, text: str) -> None:
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                for word in re.findall(r"\S+\s*", text):
                    self.wfile.write(_chunk({"content": word}))
                self.wfile.write(_chunk({}, "stop"))
                self.wfile.write(b"data: [DONE]\n\n")

        return Handler


def _completion(text: str) -> dict:
    message = {"role": "assistant", "content": text}
    return {
        "id": "c",
        "object": "chat.completion",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
        },
    }


def _chunk(delta: dict, finish: str | None = None) -> bytes:
    choice = {"index": 0, "delta": delta, "finish_reason": finish}
    event = {
        "id": "c",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [choice],
    }
    return f"data: {json.dumps(event)}\n\n".encode()


class AtlasServer:
    """The real server, as its own process, on a throwaway data folder."""

    def __init__(self, data: Path, provider: FakeProvider) -> None:
        self.data = data
        self.log = data / "server.log"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}/api/v1"
        self.env = {
            **{k: v for k, v in os.environ.items() if "ATLAS_" not in k},
            "ATLAS_DATA_PATH": str(data),
            "ATLAS_HOST": "127.0.0.1",
            "ATLAS_PORT": str(self.port),
            "PYTHONUNBUFFERED": "1",
        }
        self._seed(provider)
        self._process: subprocess.Popen[bytes] | None = None

    def _seed(self, provider: FakeProvider) -> None:
        bootstrap = BootstrapSettings(data_path=self.data)
        bootstrap.create_directories()
        upgrade_to_head(settings=bootstrap)
        values = {
            "embedding_provider": "fake",
            "embedding_model": "fake-a",
            "fake_embedding_dim": 32,
            "llm_provider": "openai_compatible",
            "llm_model": "fake-chat",
            "llm_base_url": provider.url,
            "ollama_base_url": "http://127.0.0.1:1",
            "chunk_size": 200,
            "chunk_overlap": 20,
        }
        with sqlite3.connect(bootstrap.database_path) as db:
            db.execute(
                'insert into instance_settings(id, "values", secrets) '
                "values (1, ?, '{}')",
                (json.dumps(values),),
            )

    def start(self) -> None:
        output = self.log.open("a")
        self._process = subprocess.Popen(
            [sys.executable, "-m", "atlas"],
            cwd=self.data,
            env=self.env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.base}/health/ready").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"Atlas did not start:\n{self.log.read_text()}")

    def stop(self) -> None:
        if self._process is not None:
            self._process.send_signal(signal.SIGINT)
            self._process.wait(20)
            self._process = None

    def setup_token(self) -> str:
        found = re.search(r"Setup token: (\S+)", self.log.read_text())
        assert found, "the server did not print a setup token"
        return found.group(1)


@pytest.fixture(scope="session")
def provider() -> Iterator[FakeProvider]:
    fake = FakeProvider()
    yield fake
    fake.close()


@pytest.fixture(scope="session")
def other_provider() -> Iterator[FakeProvider]:
    """A second address, to prove keys don't travel to it."""
    fake = FakeProvider()
    yield fake
    fake.close()


@pytest.fixture(scope="session")
def server(
    provider: FakeProvider, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[AtlasServer]:
    atlas = AtlasServer(tmp_path_factory.mktemp("atlas"), provider)
    atlas.start()
    yield atlas
    atlas.stop()


def minimal_pdf(text: str) -> bytes:
    """A small, valid one-page PDF containing ``text``."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % start
    return bytes(out)
