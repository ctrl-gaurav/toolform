"""``python -m toolform.serve [options]`` is ``toolform serve [options]``."""

from __future__ import annotations

import sys

from ..app.cli import main

if __name__ == "__main__":
    main(["serve", *sys.argv[1:]])
