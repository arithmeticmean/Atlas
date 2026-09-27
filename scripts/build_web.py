#!/usr/bin/env python3
"""Build the React UI into the Python package.

A thin wrapper: the implementation lives in ``cli/webbuild.py`` so that
``atlas serve`` (which builds the UI when it is missing) and this script can
never drift apart. Run it directly when you want to rebuild without starting
the server -- or use ``atlas build-web``, which is the same thing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cli import webbuild  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(0 if webbuild.build(force=True) else 1)
