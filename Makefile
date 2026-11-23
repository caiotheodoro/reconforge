.PHONY: validate sync forge-test knowledge-test model-test system-test study compose-up compose-down paper paper-test

PY = uv run python

# macOS workaround: uv hides new venvs in Finder (UF_HIDDEN), and CPython
# 3.11+ skips .pth files under hidden dirs, silently breaking editable
# installs. Tests use pytest `pythonpath = ["src"]` (no .pth involved);
# the chflags is for CLI runs and cross-workstream imports.
sync:
	for d in forge knowledge model system; do cd $$d && uv sync --no-editable && chflags -R nohidden .venv && cd ..; done

validate: forge-test knowledge-test model-test system-test paper-test

forge-test:
	cd forge && uv run pytest -q

knowledge-test:
	cd knowledge && uv run pytest -q

model-test:
	cd model && uv run pytest -q

system-test:
	cd system && uv run pytest -q -m "not integration"

study:
	cd forge && $(PY) -m reconforge_forge.cli pilot --tasks 400 --seed 7

compose-up:
	docker compose up -d

compose-down:
	docker compose down

# The paper: numbers, tables and figures are generated from docs/validation/*.json;
# paper-test fails if the prose carries a figure that does not trace to an artifact or if
# the rendered PDF has lost text. Needs tectonic and pdftotext for the render checks.
paper:
	cd paper && uv run python build_assets.py && uv run python export_metadata.py && tectonic reconforge.tex

paper-test:
	cd paper && uv run pytest -q
