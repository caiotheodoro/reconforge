"""Put src/ on sys.path for tests (see pyproject.toml [tool.uv] package=false
comment: uv venv .pth files are hidden on macOS and silently skipped by
site.addpackage, so we don't editable-install the project)."""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
