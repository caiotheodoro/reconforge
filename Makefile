.PHONY: validate sync forge-test knowledge-test model-test system-test study compose-up compose-down

PY = uv run python

# macOS workaround: uv hides new venvs in Finder (UF_HIDDEN), and CPython
# 3.11+ skips .pth files under hidden dirs, silently breaking editable
# installs. Tests use pytest `pythonpath = ["src"]` (no .pth involved);
# the chflags is for CLI runs and cross-workstream imports.
sync:
	for d in forge knowledge model system; do cd $$d && uv sync --no-editable && chflags -R nohidden .venv && cd ..; done

validate: forge-test knowledge-test model-test system-test

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
