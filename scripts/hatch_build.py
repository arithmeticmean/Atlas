"""Build hook: compile the web UI into the package before it is packaged.

The UI is part of the product, so building it is the build backend's job, not
the CLI's: ``uv build`` (and ``uv sync``, which builds an editable install)
run ``npm`` here, and the built files land in ``src/atlas/static`` where the
wheel picks them up and FastAPI serves them.

* **Release builds** (sdist, wheel) always rebuild, so a stale bundle left in
  ``static/`` can never ship. A failed npm build fails the Python build.
* **Editable installs** (``uv sync``) build only when ``static/`` is empty, so
  a fresh checkout gets a working UI from ``uv sync`` alone while later syncs
  stay fast. To see UI changes, use ``npm run dev`` in ``web/``.
* **Building from an sdist** finds no ``web/`` beside it -- the sdist already
  carries the built UI -- and skips npm, so installing from source needs no
  Node.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebBuildHook(BuildHookInterface):  # type: ignore[misc]
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        web = root / "web"
        static = root / "src" / "atlas" / "static"

        if not (web / "package.json").is_file():
            return  # building from an sdist: the UI is already in it
        if version == "editable" and (static / "index.html").is_file():
            return

        npm = shutil.which("npm")
        if npm is None:
            raise RuntimeError(
                "building Atlas needs npm to compile the web UI (web/). "
                "Install Node.js and try again."
            )
        self.app.display_info("building the web UI (npm)")
        if not (web / "node_modules").is_dir() or version != "editable":
            subprocess.run([npm, "ci"], cwd=web, check=True)
        subprocess.run([npm, "run", "build"], cwd=web, check=True)
