"""Evaluation: load base model + LoRA adapter, generate verdicts over an eval
JSONL, compute metrics, and write the artifact to docs/validation/.

Metrics: verdict accuracy, severity-weighted recall (CONTRACTS.md), per-class
confusion matrix, JSON parse rate, mean tokens per verdict. Also computes ECE
on the confidence field (full calibration lives in calib.py).
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import metrics
from .schema import SYSTEM_PROMPT, parse_verdict, render_user_message

DEFAULT_BASE = "mlx-community/Qwen3-1.7B-4bit"
SHARED_ARTIFACTS = Path("/Users/caiotheodoro/Documents/personal/reconforge/docs/validation")


def load_eval_records(path: str) -> list[dict]:
    """Load eval records from dataset-format JSONL (with `messages`) or from
    raw task JSONL (with `ledger`/`statement`/`expected`)."""
    records = []
    with open(path) as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            records.append(rec)
    return records


def record_task_dict(rec: dict) -> dict:
    """Recover the CONTRACTS task dict for an eval record."""
    if "expected" in rec:
        return rec
    task = {
        "task_id": rec.get("task_id", "unknown"),
        "difficulty": rec.get("difficulty", 0.5),
        "ledger": rec.get("ledger"),
        "statement": rec.get("statement"),
        "expected": parse_verdict(rec["messages"][-1]["content"]),
    }
    return task


def build_prompt_messages(task: dict) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": render_user_message(task)},
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.py", description="Evaluate a fine-tuned worker")
    parser.add_argument("--base-model", default=DEFAULT_BASE)
    parser.add_argument("--adapter-path", required=True, help="dir with adapters.safetensors")
    parser.add_argument("--eval-file", required=True, help="eval JSONL (dataset or task format)")
    parser.add_argument("--run", default="smoke", help="run id used in the artifact filename")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--out-dir", type=str, default=str(SHARED_ARTIFACTS))
    opts = parser.parse_args(argv)

    from mlx_lm.lora import load

    records = load_eval_records(opts.eval_file)
    tasks = [record_task_dict(r) for r in records]

    t0 = time.perf_counter()
    model, tokenizer = load(opts.base_model, adapter_path=opts.adapter_path,
                            tokenizer_config={"trust_remote_code": True})
    for attr in ("has_thinking", "enable_thinking"):
        if hasattr(tokenizer, attr):
            setattr(tokenizer, attr, False)

    predictions: list[dict | None] = []
    outputs = []
    total_tokens = 0
    gen_seconds = 0.0
    for task in tasks:
        messages = build_prompt_messages(task)
        prompt = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, enable_thinking=False, return_dict=False
        )
        g0 = time.perf_counter()
        text = _generate(model, tokenizer, prompt, max_new_tokens=opts.max_new_tokens)
        gen_seconds += time.perf_counter() - g0
        total_tokens += len(tokenizer.encode(text))
        pred = parse_verdict(text)
        predictions.append(pred)
        expected = task["expected"]
        outputs.append(
            {
                "task_id": task["task_id"],
                "difficulty": task["difficulty"],
                "expected": expected,
                "predicted": pred,
                "correct": bool(metrics.is_correct(expected, pred)),
                "caught": bool(metrics.is_caught(expected, pred)),
                "confidence": pred["confidence"] if pred else None,
                "n_tokens": len(tokenizer.encode(text)),
            }
        )
        if len(outputs) % 20 == 0:
            print(f"[eval] {len(outputs)}/{len(tasks)}", flush=True)

    acc = metrics.accuracy(tasks, predictions)
    swr = metrics.severity_weighted_recall(tasks, predictions)
    cm = metrics.confusion_matrix(tasks, predictions)
    pr = metrics.parse_rate(predictions)
    confidences = [o["confidence"] if o["confidence"] is not None else 0.0 for o in outputs]
    correctness = [1 if o["correct"] else 0 for o in outputs]
    cal = metrics.ece(confidences, correctness, n_bins=10)
    mean_tokens = round(total_tokens / max(len(tasks), 1), 2)

    metrics_out = {
        **acc,
        **pr,
        "severity_weighted_recall": swr,
        "ece": cal["ece"],
        "mean_tokens_per_verdict": mean_tokens,
        "generation_seconds": round(gen_seconds, 1),
        "generation_tokens_per_sec": round(total_tokens / max(gen_seconds, 1e-9), 1),
    }

    artifact = {
        "run": opts.run,
        "base_model": opts.base_model,
        "adapter_path": opts.adapter_path,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n": len(tasks),
        "metrics": metrics_out,
        "severity_weighted_recall_detail": swr,
        "confusion_matrix": cm,
        "confusion_summary": metrics.summarize_confusion(cm),
        "per_prediction": outputs,
    }
    out_dir = Path(opts.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = out_dir / f"model-eval-{opts.run}.json"
    artifact_path.write_text(json.dumps(artifact, indent=2) + "\n")

    print()
    print("=" * 64)
    print(f"run: {opts.run} | n={len(tasks)} | base={opts.base_model}")
    print(f"adapter: {opts.adapter_path}")
    print(f"accuracy            : {metrics_out['accuracy']:.4f}")
    print(f"severity-weighted R : {swr['severity_weighted_recall']:.4f}")
    print(f"parse rate          : {metrics_out['parse_rate']:.4f}")
    print(f"ECE (10 bins)       : {metrics_out['ece']:.4f}")
    print(f"mean tokens/verdict : {mean_tokens}")
    print(f"wall (generation)   : {metrics_out['generation_seconds']}s")
    print()
    print("per-type recall:")
    for t, v in sorted(swr["per_type"].items()):
        print(f"  {t:24s} n={v['n']:4d} recall={v['recall']:.3f}")
    print("=" * 64)
    print(f"artifact -> {artifact_path}")
    return 0


def _generate(model, tokenizer, prompt, max_new_tokens: int) -> str:
    """Greedy generation (temperature 0). Kept as a helper so we can swap in
    batched generation later without touching the loop above."""
    from mlx_lm.generate import generate
    from mlx_lm.sample_utils import make_sampler

    return generate(
        model,
        tokenizer,
        prompt,
        max_tokens=max_new_tokens,
        sampler=make_sampler(temp=0.0),
    )


if __name__ == "__main__":
    raise SystemExit(main())
