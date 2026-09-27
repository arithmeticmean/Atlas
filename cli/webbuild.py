"""Building the web UI, and deciding when that is Atlas's job.

``atlas serve`` builds the SPA when it is missing, so running the application
from a checkout is one command rather than two. That only makes sense in a
checkout: an installed wheel already carries the built UI as package data,
has no ``web/`` sources beside it and no reason to need npm. Everything here is
therefore conditional on finding real Vite sources next to the package, and
every failure degrades to "serve the API headless" rather than refusing to
start -- a missing UI should never stop the server the UI talks to.
"""

import shutil
import subprocess
from pathlib import Path

# cli/ and service/ are siblings, so the repository root is one level up.
_REPO_ROOT = Path(__file__).resolve().parent.parent

SOURCE_DIR = _REPO_ROOT / "web"
OUTPUT_DIR = _REPO_ROOT / "service" / "web"


def has_sources() -> bool:
    """Whether Vite sources sit beside the package -- i.e. a checkout."""
    return (SOURCE_DIR / "package.json").is_file()


def is_built(output: Path | None = None) -> bool:
    return (output or OUTPUT_DIR).joinpath("index.html").is_file()


def npm() -> str | None:
    """Resolve npm, or ``None``.

    ``shutil.which`` rather than the bare string: on Windows npm is ``npm.cmd``
    and handing ``subprocess`` the plain name fails there.
    """
    return shutil.which("npm")


def build(*, force: bool = False, quiet: bool = False) -> bool:
    """Build the SPA into the package. Returns whether it is built afterwards.

    Never raises: the caller is usually ``serve``, and a UI that will not build
    is a reason to warn, not a reason to refuse to serve the API.
    """

    def say(message: str) -> None:
        if not quiet:
            print(message, flush=True)

    if is_built() and not force:
        return True

    if not has_sources():
        # An installed wheel: the UI either shipped inside it or it did not,
        # and there is nothing here to build from either way.
        return is_built()

    tool = npm()
    if tool is None:
        say(
            "! npm not found, so the web UI cannot be built. Serving the API "
            "headless; install Node.js (https://nodejs.org) and restart to "
            "get the UI."
        )
        return False

    if not (SOURCE_DIR / "node_modules").is_dir():
        lockfile = (SOURCE_DIR / "package-lock.json").is_file()
        say("building the web UI (installing npm dependencies first)…")
        if not _run(tool, "ci" if lockfile else "install"):
            say("! npm install failed; serving the API headless.")
            return False
    else:
        say("building the web UI…")

    if not _run(tool, "run", "build"):
        say("! the web UI build failed; serving the API headless.")
        return False

    if not is_built():
        say(
            "! the build reported success but produced no index.html; "
            "check outDir in web/vite.config.js."
        )
        return False

    say(f"web UI built -> {OUTPUT_DIR}")
    return True


def _run(tool: str, *args: str) -> bool:
    try:
        return subprocess.run([tool, *args], cwd=SOURCE_DIR).returncode == 0
    except OSError:
        return False
