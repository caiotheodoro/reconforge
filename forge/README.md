# ReconForge Forge

Measurement core for ReconForge: seeded synthetic task generator, canonical
verifier-as-oracle, pilot benchmark scoring, and signature-based contamination
monitor for financial back-office reconciliation agents.

```bash
uv venv
uv sync
uv run pytest -q

uv run python -m reconforge_forge.cli pilot --tasks 300 --seed 7
uv run python -m reconforge_forge.cli contamination --seed 7
```

Artifacts land in `docs/validation/` (shared): `pilot-<seed>.json`,
`contamination-roc.json`. Everything takes a `--seed`; the same seed reproduces
byte-identical artifacts.

## macOS note (UF_HIDDEN)

If `import reconforge_forge` fails with `ModuleNotFoundError` while
`site-packages` exists, macOS may have set the hidden file flag on the venv
(`ls -lO .venv` shows `hidden`), which makes CPython 3.11+ site.py skip the
editable `.pth` file ("Skipping hidden .pth file"). Fix:

```bash
chflags -R nohidden .venv
```

