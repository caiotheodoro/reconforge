#!/usr/bin/env bash
# ReconForge model workstream — end-to-end smoke:
#   build small dataset (forge package or local stub) -> MLX-LoRA fine-tune
#   ~60-100 steps -> eval -> calib -> print metrics table.
#
# Expected wall time on M5: 10-30 min (model download excluded).
set -euo pipefail

MODEL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$(cd "$MODEL_DIR/.." && pwd)"
RUN="smoke-$(date +%Y%m%d)"
N_TASKS="${SMOKE_N_TASKS:-400}"
STEPS="${SMOKE_STEPS:-60}"
BATCH_SIZE="${SMOKE_BATCH_SIZE:-2}"
BASE_MODEL="${SMOKE_BASE_MODEL:-mlx-community/Qwen3-1.7B-4bit}"
OUT_DIR="$MODEL_DIR/adapters/lora-smoke"
DATA_DIR="$MODEL_DIR/data/smoke"
EVAL_ARTIFACT="$ROOT_DIR/docs/validation/model-eval-$RUN.json"
CALIB_ARTIFACT="$ROOT_DIR/docs/validation/model-calib-$RUN.json"

echo "== ReconForge model smoke [$RUN] =="
echo "== base: $BASE_MODEL | tasks: $N_TASKS | steps: $STEPS | batch: $BATCH_SIZE =="

cd "$MODEL_DIR"

if [ ! -d .venv ]; then
    echo "== creating venv + installing deps (first run) =="
    uv venv --python 3.11
    uv sync
fi
uv sync >/dev/null

# See pyproject.toml [tool.uv] package=false: uv venv .pth files are hidden on
# macOS and skipped by site.addpackage, so the project is not installed
# editable — put src/ on the path explicitly.
export PYTHONPATH="$MODEL_DIR/src"

echo "== [1/4] building dataset =="
uv run python -m reconforge_model.dataset_builder \
    --source auto --n "$N_TASKS" --seed 7 --train-frac 0.8 \
    --out-dir "$DATA_DIR"

echo "== [2/4] fine-tuning (LoRA rank 16 alpha 32, $STEPS steps) =="
MAX_ATTEMPTS=2
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT + 1))
    if uv run python -m reconforge_model.train \
        --data-dir "$DATA_DIR" \
        --out-dir "$OUT_DIR" \
        --base-model "$BASE_MODEL" \
        --quantize 4 \
        --steps "$STEPS" \
        --batch-size "$BATCH_SIZE" \
        --grad-checkpoint \
        --clear-cache-threshold 2g; then
        break
    fi
    echo "== training attempt $ATTEMPT failed =="
    if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
        echo "ERROR: training failed after $MAX_ATTEMPTS attempts (HF download issue?)" >&2
        exit 1
    fi
    echo "== retrying once (download?) =="
    sleep 5
done

echo "== [3/4] evaluating =="
uv run python -m reconforge_model.eval \
    --adapter-path "$OUT_DIR" \
    --base-model "$BASE_MODEL" \
    --eval-file "$DATA_DIR/val.jsonl" \
    --run "$RUN"

echo "== [4/4] calibration + threshold search =="
uv run python -m reconforge_model.calib \
    --eval-artifact "$EVAL_ARTIFACT" \
    --run "$RUN"

echo
echo "== smoke complete: $RUN =="
echo "  dataset   : $DATA_DIR"
echo "  adapter   : $OUT_DIR"
echo "  eval      : $EVAL_ARTIFACT"
echo "  calib     : $CALIB_ARTIFACT"
