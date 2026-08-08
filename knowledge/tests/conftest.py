"""Test bootstrap.

Inserts the package src/ dir into sys.path as a robustness net: the
uv-managed CPython 3.11.15 on macOS skips .pth files with the UF_HIDDEN flag
(uv marks venv files hidden), so editable-install pth files are not always
processed. The shim makes `uv run pytest` hermetic regardless.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
