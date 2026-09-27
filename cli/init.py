"""``atlas init`` -- create a local instance.

Writes two files into ``ATLAS_HOME`` and then makes the instance real:

* ``config.toml``  -- providers, models, server bind. Non-secret, so it can be
  read, diffed, or pasted into a bug report without leaking anything.
* ``secrets.toml`` -- API keys and a freshly generated token-signing secret,
  written 0600.

Then it creates the directory tree, applies migrations, and creates the owner
account. The owner's password is hashed into the database and the plaintext
discarded -- it is deliberately *not* a setting, so it never lands on disk in
readable form.

Re-running against an existing instance is safe: it refuses to overwrite
configuration without ``--force``, and account creation is idempotent.
"""

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cli import _ui
from cli.preflight import CheckResult
from service.config import paths


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """A selectable provider.

    ``suggested`` is only a prompt default -- the model name is free text.
    Providers are a closed set because each maps to a branch in the model
    factories; models are not, because any list would cover a fraction of what
    a provider offers and would go stale. A typo is caught by the preflight
    checks instead (see cli/preflight.py).
    """

    desc: str
    suggested: str
    key_field: str | None = None


EMBEDDING_PROVIDERS: dict[str, ProviderSpec] = {
    "ollama": ProviderSpec(
        desc="local, no API key", suggested="nomic-embed-text"
    ),
    "openai": ProviderSpec(
        desc="hosted, bring your own key",
        suggested="text-embedding-3-small",
        key_field="openai_api_key",
    ),
    "fake": ProviderSpec(
        desc="deterministic, offline -- for testing only",
        suggested="fake",
    ),
}

LLM_NATIVE: dict[str, ProviderSpec] = {
    "ollama": ProviderSpec(desc="local, no API key", suggested="llama3.1"),
    "openai": ProviderSpec(
        desc="GPT", suggested="gpt-4o", key_field="openai_api_key"
    ),
    "anthropic": ProviderSpec(
        desc="Claude",
        suggested="claude-sonnet-5",
        key_field="anthropic_api_key",
    ),
}

# Endpoints that speak the OpenAI API. The model name is typed either way.
COMPATIBLE_ENDPOINTS: list[tuple[str, str]] = [
    ("Moonshot / Kimi", "https://api.moonshot.ai/v1"),
    ("Groq", "https://api.groq.com/openai/v1"),
    ("DeepSeek", "https://api.deepseek.com/v1"),
    ("Together", "https://api.together.xyz/v1"),
    ("other (enter URL)", ""),
]

# One setting per key, names matching the fields on Settings. Heterogeneous by
# nature (strings, an int port, None for unset optionals), which is why the
# values are Any rather than a union that would have to be widened at every
# call site.
ConfigValues = dict[str, Any]

SECRET_FIELDS = frozenset(
    {"jwt_secret", "openai_api_key", "anthropic_api_key", "llm_api_key"}
)


class InitError(Exception):
    """Initialization cannot proceed (reported without a traceback)."""


# --- TOML output ------------------------------------------------------------


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    escaped = (
        str(value).replace("\\", "\\\\").replace('"', '\\"')
    )
    return f'"{escaped}"'


def _render_toml(header: str, values: ConfigValues) -> str:
    lines = [f"# {line}" for line in header.splitlines()]
    lines.append("")
    lines += [
        f"{key} = {_toml_value(value)}"
        for key, value in values.items()
        if value is not None
    ]
    return "\n".join(lines) + "\n"


_CONFIG_HEADER = """Atlas configuration -- written by `atlas init`.

Flat keys matching the field names in atlas/config/config.py. Anything here can
be overridden per-run by an ATLAS_-prefixed environment variable, e.g.
ATLAS_LLM_MODEL. Secrets live in secrets.toml beside this file."""

_SECRETS_HEADER = """Atlas secrets -- written by `atlas init`. Mode 0600.

Keep this file out of backups you share and out of bug reports. Rotating
jwt_secret invalidates every issued access and refresh token."""


def write_config(
    values: ConfigValues, *, home: Path | None = None
) -> tuple[Path, Path]:
    """Write config.toml and secrets.toml; return both paths."""
    if home is not None:
        # paths.* read ATLAS_HOME, so an explicit --home is applied by setting
        # it before anything resolves a path.
        import os

        os.environ[paths.ENV_HOME] = str(home)

    paths.ensure_home()
    config_values = {
        k: v for k, v in values.items() if k not in SECRET_FIELDS
    }
    secret_values = {k: v for k, v in values.items() if k in SECRET_FIELDS}

    config_path = paths.config_file()
    secrets_path = paths.secrets_file()

    config_path.write_text(_render_toml(_CONFIG_HEADER, config_values))
    # Create with the right mode from the start, rather than writing readable
    # and narrowing afterwards.
    secrets_path.touch(mode=0o600, exist_ok=True)
    secrets_path.chmod(0o600)
    secrets_path.write_text(_render_toml(_SECRETS_HEADER, secret_values))
    return config_path, secrets_path


# --- interactive gathering --------------------------------------------------


def gather_interactive() -> tuple[ConfigValues, str, str]:
    """Prompt for everything.

    Returns ``(settings, owner_email, owner_password)``.
    """
    values: ConfigValues = {}

    _ui.rule("Embedding model")
    print(
        "  "
        + _ui.gray(
            "bound to the index: changing it later triggers a full reindex"
        )
    )
    ekey = _ui.menu(
        "Embedding provider",
        [(k, v.desc) for k, v in EMBEDDING_PROVIDERS.items()],
        "ollama",
    )
    espec = EMBEDDING_PROVIDERS[ekey]
    values["embedding_provider"] = ekey
    values["embedding_model"] = _ui.ask(
        "Embedding model (as the provider names it)", espec.suggested
    )
    if espec.key_field:
        values[espec.key_field] = _ui.ask_secret("OpenAI API key")

    _ui.rule("Answering model (LLM)")
    providers = [(k, v.desc) for k, v in LLM_NATIVE.items()]
    providers.append(
        ("openai-compatible", "Kimi, Groq, DeepSeek, … (enter model name)")
    )
    lkey = _ui.menu("LLM provider", providers, "ollama")

    if lkey == "openai-compatible":
        values["llm_provider"] = "openai"
        endpoint = _ui.menu(
            "Endpoint",
            [
                (name, url or "enter your own")
                for name, url in COMPATIBLE_ENDPOINTS
            ],
            COMPATIBLE_ENDPOINTS[0][0],
        )
        url = dict(COMPATIBLE_ENDPOINTS)[endpoint]
        values["llm_base_url"] = url or _ui.ask("Base URL", "https://…/v1")
        values["llm_model"] = _ui.ask(
            "Model name (as the provider names it)"
        )
        values["llm_api_key"] = _ui.ask_secret(f"{endpoint} API key")
    else:
        spec = LLM_NATIVE[lkey]
        values["llm_provider"] = lkey
        values["llm_model"] = _ui.ask(
            "LLM model (as the provider names it)", spec.suggested
        )
        # Reuse a key already entered for the embedding side.
        if spec.key_field and not values.get(spec.key_field):
            values[spec.key_field] = _ui.ask_secret(f"{lkey} API key")

    if "ollama" in (values["embedding_provider"], values["llm_provider"]):
        _ui.rule("Ollama")
        values["ollama_base_url"] = _ui.ask(
            "Ollama base URL", "http://localhost:11434"
        )
        models = [
            str(values["embedding_model"])
            if values["embedding_provider"] == "ollama"
            else "",
            str(values["llm_model"])
            if values["llm_provider"] == "ollama"
            else "",
        ]
        needed = [m for m in dict.fromkeys(models) if m]
        print(
            "  "
            + _ui.gray("make sure these are pulled: ")
            + _ui.bold(", ".join(needed))
        )

    _ui.rule("Owner account")
    print(
        "  "
        + _ui.gray("the single admin who can create projects & invite users")
    )
    email = _ui.ask("Owner email", "owner@atlas.local")
    password = _ui.ask_secret("Owner password")
    if not password:
        raise InitError("an owner password is required")

    return values, email, password


# --- the instance itself ----------------------------------------------------


async def _provision(owner_email: str, owner_password: str) -> None:
    """Apply migrations and create the owner, against the new configuration."""
    from service.core.bootstrap import ensure_owner
    from service.storage.sql import dispose_engine, get_session
    from service.storage.sql.migrate import upgrade_to_head
    from service.storage.sql.user import SqlUserStore
    from service.storage.store import UserStore

    # Any engine built before the config was written points at the wrong URL.
    await dispose_engine()
    await asyncio.to_thread(upgrade_to_head)

    @asynccontextmanager
    async def user_store_uow() -> AsyncIterator[UserStore]:
        async with get_session() as session:
            yield SqlUserStore(session)

    await ensure_owner(
        user_store_uow=user_store_uow,
        email=owner_email,
        password=owner_password,
    )
    await dispose_engine()


def validate_providers(values: ConfigValues) -> list[CheckResult]:
    """Prove the configured models exist and answer, before writing anything.

    Raises :class:`InitError` if any check fails, so a failed ``atlas init``
    leaves no instance directory behind at all -- there is nothing to clean up
    and nothing that looks half-configured.
    """
    from pydantic import ValidationError

    from cli.preflight import run_checks
    from service.config import Settings

    try:
        candidate = Settings(
            **{k: v for k, v in values.items() if v is not None}
        )
    except ValidationError as exc:
        fields = ", ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        )
        raise InitError(f"invalid configuration -- {fields}") from exc

    results = asyncio.run(run_checks(candidate))

    for r in results:
        mark = _ui.green("\u2713") if r.ok else _ui.red("\u2717")
        print(f"  {mark} {r.name} {_ui.gray(r.detail)}", flush=True)
        if not r.ok and r.hint:
            print(f"    {_ui.yellow(r.hint)}", flush=True)

    if any(not r.ok for r in results):
        raise InitError(
            "provider checks failed -- nothing was written. Fix the model "
            "name, endpoint or key and run `atlas init` again, or pass "
            "--skip-checks to configure anyway."
        )
    return results


def run_init(
    values: ConfigValues,
    owner_email: str,
    owner_password: str,
    *,
    home: Path | None = None,
    force: bool = False,
    quiet: bool = False,
    skip_checks: bool = False,
) -> None:
    """Verify the providers, then write configuration and provision."""
    import os

    if home is not None:
        os.environ[paths.ENV_HOME] = str(home)

    if paths.is_initialized() and not force:
        raise InitError(
            f"{paths.config_file()} already exists. Re-run with --force to "
            "overwrite it (your documents and index are not touched)."
        )

    # Before anything is written: a wrong model name or an unreachable
    # provider is far cheaper to discover now than at the first `atlas serve`.
    checks: list[CheckResult] = []
    if skip_checks:
        print(
            "  "
            + _ui.yellow("! skipping provider checks (--skip-checks)")
        )
    else:
        _ui.rule("Checking providers")
        checks = validate_providers(values)

    # Generated, never defaulted: an instance whose signing key is predictable
    # has no authentication at all.
    values.setdefault("jwt_secret", secrets.token_urlsafe(48))

    config_path, secrets_path = write_config(values, home=home)

    # The cached Settings predates these files.
    from service.config import reload_settings

    reload_settings()

    asyncio.run(_provision(owner_email, owner_password))

    embedding_dim = next(
        (c.detail for c in checks if c.ok and c.name.startswith("embedding")),
        None,
    )

    if quiet:
        # Scriptable output: one line per artefact, no box drawing, no colour.
        print(f"config   {config_path}")
        print(f"secrets  {secrets_path} (0600)")
        print(f"data     {paths.atlas_home()}")
        print(f"owner    {owner_email}")
        if embedding_dim:
            print(f"embedding {embedding_dim}")
        return

    rows = [
        f"{_ui.gray(k):<34} "
        + (
            _ui.mag("••••••••")
            if k in SECRET_FIELDS and v
            else _ui.green(str(v))
        )
        for k, v in values.items()
    ]
    rows.append(f"{_ui.gray('owner_email'):<34} {_ui.green(owner_email)}")
    if embedding_dim:
        rows.append(
            f"{_ui.gray('embedding vector'):<34} {_ui.green(embedding_dim)}"
        )
    print()
    _ui.panel("Instance", rows)
    print(f"  {_ui.green('✓')} config   {config_path}")
    print(f"  {_ui.green('✓')} secrets  {secrets_path} {_ui.gray('(0600)')}")
    print(f"  {_ui.green('✓')} data     {paths.atlas_home()}")
    print(
        "\n  start it with:  "
        + _ui.bold("atlas serve")
        + _ui.gray("   → http://127.0.0.1:8000")
    )
