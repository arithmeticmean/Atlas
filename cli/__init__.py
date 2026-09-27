"""Command-line interface — the only entry point into the application.

``main`` is what the ``atlas`` console script resolves to. It is deliberately
import-light: nothing here pulls in the API, the database, or a model provider
at module scope, so ``atlas init`` can run on a machine that has no
configuration and no data directory yet.
"""

from cli.main import main

__all__ = ["main"]
