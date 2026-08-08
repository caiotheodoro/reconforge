.PHONY: validate sync forge-test knowledge-test model-test system-test study compose-up compose-down

PY = uv run python

# macOS workaround: editable installs drop .pth files that CPython skips when
# the venv dir carries the hidden flag (iCloud/Spotlight). Non-editable
# installs avoid .pth entirely -> hermetic and repeatable.
sync:
	cd forge && uv sync --no-editable
	cd knowledge && uv sync --no-editable
	cd model && uv sync --no-editable
	cd system && uv sync --no-editable

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
