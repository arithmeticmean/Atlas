"""``atlas`` command-line entry point.

Every command imports its dependencies *inside* the function body. That is
not stylistic: ``atlas init`` has to run on a machine with no instance
directory and no configuration, and importing the API package pulls in
settings, a database engine, and the model-provider factories. Keeping this
module import-light means ``atlas --help`` stays fast and cannot fail on a
half-configured instance.
"""

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="atlas",
    help="Self-hosted, source-grounded RAG over your own documents.",
    add_completion=False,
)

HomeOption = Annotated[
    Path | None,
    typer.Option(
        "--home",
        help="Instance directory (default: $ATLAS_HOME, else ~/.atlas). "
        "Holds config, the database, the index, and your documents.",
    ),
]


def _apply_home(home: Path | None) -> None:
    """Point every later path lookup at ``home``.

    Set in the environment rather than passed around: ``service.config.paths``
    reads ``ATLAS_HOME``, so this reaches settings, the database URL, and the
    blob store without threading an argument through all of them.
    """
    if home is not None:
        import os

        from service.config import paths

        os.environ[paths.ENV_HOME] = str(home)


@app.command()
def init(
    home: HomeOption = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite existing configuration. Your documents, database "
            "and index are left alone.",
        ),
    ] = False,
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="Take everything from the options below, never prompt.",
        ),
    ] = False,
    skip_checks: Annotated[
        bool,
        typer.Option(
            "--skip-checks",
            help="Write the configuration without verifying that the "
            "embedding and chat models exist and respond. Use when setting "
            "up a machine before the provider is running.",
        ),
    ] = False,
    embedding_provider: str = "ollama",
    embedding_model: str = "nomic-embed-text",
    llm_provider: str = "ollama",
    llm_model: str = "llama3.1",
    llm_base_url: str | None = None,
    llm_api_key: str | None = None,
    openai_api_key: str | None = None,
    anthropic_api_key: str | None = None,
    ollama_base_url: str = "http://localhost:11434",
    owner_email: str | None = None,
    owner_password: str | None = None,
) -> None:
    """Create a local instance: configuration, database, and owner account.

    Model names are free text -- whatever your provider calls them. Both models
    are contacted before anything is written, so a typo or an unreachable
    provider fails here rather than at the first `atlas serve`.
    """
    from cli import _ui
    from cli.init import (
        ConfigValues,
        InitError,
        gather_interactive,
        run_init,
    )

    _apply_home(home)

    try:
        if non_interactive:
            if not owner_email or not owner_password:
                raise InitError(
                    "--non-interactive requires --owner-email and "
                    "--owner-password"
                )
            values: ConfigValues = {
                "embedding_provider": embedding_provider,
                "embedding_model": embedding_model,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "ollama_base_url": ollama_base_url,
                "llm_base_url": llm_base_url,
                "llm_api_key": llm_api_key,
                "openai_api_key": openai_api_key,
                "anthropic_api_key": anthropic_api_key,
            }
            email, password = owner_email, owner_password
        else:
            _ui.banner()
            values, email, password = gather_interactive()

        run_init(
            values,
            email,
            password,
            home=home,
            force=force,
            quiet=non_interactive,
            skip_checks=skip_checks,
        )
    except InitError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        typer.echo("\naborted", err=True)
        raise typer.Exit(code=130) from None


def _run_server(
    *,
    home: Path | None,
    host: str | None,
    port: int | None,
    reload: bool,
    build_ui: bool,
) -> None:
    """Start the server, building the web UI first when it is missing."""
    _apply_home(home)

    import os

    import uvicorn

    from service.config import get_settings, paths, reload_settings

    if not paths.is_initialized():
        typer.secho(
            f"no instance at {paths.atlas_home()} -- run `atlas init` first.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    if build_ui:
        # Running from a checkout with no built UI is the common case after a
        # clean, and having to remember a second command for it is friction
        # with no upside. A wheel has nothing to build and skips this.
        from cli import webbuild

        webbuild.build()

    settings = get_settings()
    bound_host = host or settings.host
    bound_port = port or settings.port

    # Record what we are really binding, so anything that reports reachability
    # reads the truth rather than the configured default. Env has the highest
    # precedence in Settings, and it survives the re-exec that --reload does.
    os.environ["ATLAS_HOST"] = bound_host
    os.environ["ATLAS_PORT"] = str(bound_port)
    # The Settings read above is already cached, so it predates those two
    # variables; re-read so this process reports the address it really bound
    # and not the configured default. (The env vars alone would only reach a
    # --reload child, not this process.)
    reload_settings()

    uvicorn.run(
        "service.api.app:app",
        host=bound_host,
        port=bound_port,
        reload=reload,
    )


@app.callback(invoke_without_command=True)
def default(ctx: typer.Context) -> None:
    """Run the Atlas server when no command is given.

    `atlas` and `atlas serve` do the same thing; the subcommand exists for the
    flags. Anything else (`atlas init`, `atlas home`, …) dispatches normally.
    """
    if ctx.invoked_subcommand is None:
        _run_server(
            home=None, host=None, port=None, reload=False, build_ui=True
        )


@app.command()
def serve(
    home: HomeOption = None,
    host: Annotated[
        str | None,
        typer.Option(
            help="Interface to bind. Loopback by default -- pass 0.0.0.0 to "
            "expose the instance on your network."
        ),
    ] = None,
    port: Annotated[
        int | None, typer.Option(help="Port to listen on.")
    ] = None,
    reload: Annotated[
        bool,
        typer.Option("--reload", help="Auto-reload on code changes (dev)."),
    ] = False,
    no_build: Annotated[
        bool,
        typer.Option(
            "--no-build",
            help="Don't build the web UI even if it is missing. Serves the "
            "API headless.",
        ),
    ] = False,
) -> None:
    """Run the Atlas server (API + web UI on one origin)."""
    _run_server(
        home=home,
        host=host,
        port=port,
        reload=reload,
        build_ui=not no_build,
    )


@app.command("build-web")
def build_web(
    force: Annotated[
        bool,
        typer.Option("--force", help="Rebuild even if it is already built."),
    ] = False,
) -> None:
    """Build the web UI into the package (what `serve` does automatically)."""
    from cli import webbuild

    if not webbuild.has_sources():
        typer.secho(
            "no web/ sources beside this installation -- nothing to build.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=1)
    if not webbuild.build(force=force):
        raise typer.Exit(code=1)


@app.command()
def migrate(home: HomeOption = None) -> None:
    """Apply pending database migrations.

    ``atlas serve`` does this itself on startup, so this exists for the cases
    that startup cannot cover: inspecting or repairing an instance, or a
    deployment that sets ``auto_migrate = false``.
    """
    _apply_home(home)

    from service.storage.sql.migrate import current_revision, upgrade_to_head

    before = current_revision()
    upgrade_to_head()
    after = current_revision()
    if before == after:
        typer.echo(f"already at {after}")
    else:
        typer.echo(f"{before or '(empty)'} -> {after}")


@app.command()
def home(home: HomeOption = None) -> None:
    """Print the instance directory and what is in it."""
    _apply_home(home)

    from service.config import paths

    root = paths.atlas_home()
    typer.echo(str(root))
    if not root.exists():
        typer.echo("  (does not exist yet -- run `atlas init`)")
        return
    for label, path in (
        ("config ", paths.config_file()),
        ("secrets", paths.secrets_file()),
        ("database", paths.database_path()),
        ("index  ", paths.vector_path()),
        ("blobs  ", paths.blob_path()),
    ):
        mark = "✓" if path.exists() else "·"
        typer.echo(f"  {mark} {label}  {path.name}")


@app.command()
def version() -> None:
    """Print the installed Atlas version."""
    # Read from distribution metadata rather than a constant in the source, so
    # pyproject.toml is the only place the version is written down. stdlib
    # only, so `atlas version` stays instant.
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as dist_version

    try:
        typer.echo(dist_version("atlas"))
    except PackageNotFoundError:
        typer.echo("unknown (atlas is not installed as a distribution)")


def main() -> None:
    app()
