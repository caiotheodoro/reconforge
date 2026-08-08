"""Full benchmark eval: fine-tuned model vs held-out benchmark tasks.

Adds **self-consistency confidence** (per the Foundry philosophy: self-report
is measured only as a baseline, never trusted as a feature): for each task we
sample the model N times at temperature 0.6 and take the majority verdict;
confidence = majority fraction. ECE is computed on that distribution.

Scores with forge's `score_verdicts` (severity-weighted recall, confusion
matrix, escalation precision) so the numbers are directly comparable to the
DeepSeek head-to-head. Artifact -> docs/validation/bench-eval-{run}.json.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import metrics
from .schema import parse_verdict, render_user_message, SYSTEM_PROMPT

SHARED_ARTIFACTS = Path("/Users/caiotheodoro/Documents/personal/reconforge/docs/validation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmark_eval.py")
    parser.add_argument("--base-model", default="mlx-community/Qwen3-1.7B-4bit")
    parser.add_argument("--adapter-path", required=True)
    parser.add_argument("--tasks-file", required=True, help="task-format JSONL (ledger/statement/expected)")
    parser.add_argument("--run", default="full")
    parser.add_argument("--samples", type=int, default=5, help="self-consistency samples")
    parser.add_argument("--temp", type=float, default=0.6)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--out-dir", type=str, default=str(SHARED_ARTIFACTS))
    opts = parser.parse_args(argv)

    from mlx_lm.generate import generate
    from mlx_lm.lora import load
    from mlx_lm.sample_utils import make_sampler

    from reconforge_forge.benchmark import score_verdicts
    from reconforge_forge.task import Task

    tasks = [Task.from_dict(json.loads(line)) for line in Path(opts.tasks_file).read_text().splitlines() if line.strip()]

    t0 = time.perf_counter()
    model, tokenizer = load(
        opts.base_model,
        adapter_path=opts.adapter_path,
        tokenizer_config={"trust_remote_code": True},
    )
    for attr in ("has_thinking", "enable_thinking"):
        if hasattr(tokenizer, attr):
            setattr(tokenizer, attr, False)

    sampler = make_sampler(temp=opts.temp)
    predictions: list[dict | None] = []
    per_task = []
    n_parse_fail = 0
    total_tokens = 0
    for i, task in enumerate(tasks):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": render_user_message(task.to_dict())},
        ]
        prompt = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, enable_thinking=False, return_dict=False
        )
        samples: list[dict | None] = []
        for _ in range(opts.samples):
            text = generate(model, tokenizer, prompt, max_tokens=opts.max_new_tokens, sampler=sampler)
            total_tokens += len(tokenizer.encode(text))
            samples.append(parse_verdict(text))
        valid = [s for s in samples if s is not None]
        n_parse_fail += opts.samples - len(valid)
        majority = _majority(valid) if valid else None
        confidence = round((len([s for s in valid if s == majority]) / len(valid)), 4) if valid else 0.0
        predictions.append(majority)
        per_task.append(
            {
                "task_id": task.task_id,
                "difficulty": task.difficulty,
                "expected": task.expected,
                "predicted": majority,
                "self_consistency_confidence": confidence,
                "samples": samples,
            }
        )
        if (i + 1) % 25 == 0:
            print(f"[bench-eval] {i + 1}/{len(tasks)}", flush=True)

    task_dicts = [t.to_dict() for t in tasks]
    scored = score_verdicts(tasks, predictions)
    acc = metrics.accuracy(task_dicts, predictions)
    pr = metrics.parse_rate(predictions)
    confidences = [p["self_consistency_confidence"] for p in per_task]
    correctness = [1 if p["predicted"] and metrics.is_correct(t.expected, p["predicted"]) else 0 for t, p in zip(tasks, per_task)]
    cal = metrics.ece(confidences, correctness, n_bins=10)

    artifact = {
        "run": opts.run,
        "benchmark": "reconforge-bench",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_model": opts.base_model,
        "adapter_path": opts.adapter_path,
        "self_consistency": {"samples": opts.samples, "temp": opts.temp},
        "n": len(tasks),
        "metrics": {
            **acc,
            **pr,
            "severity_weighted_recall": scored["severity_weighted_recall"],
            "per_type_recall": scored["severity_recall_by_severity"],
            "escalation_precision": scored["escalation_precision"],
            "n_escalations": scored["n_escalations"],
            "ece_self_consistency": cal["ece"],
            "parse_fail_samples": n_parse_fail,
            "mean_tokens_per_verdict_sample": round(total_tokens / max(len(tasks) * opts.samples, 1), 2),
            "wall_seconds": round(time.perf_counter() - t0, 1),
        },
        "scoring": scored,
        "per_task": per_task,
    }
    out = Path(opts.out_dir) / f"bench-eval-{opts.run}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2) + "\n")

    print()
    print("=" * 64)
    print(f"run: {opts.run} | n={len(tasks)} | self-consistency x{opts.samples}")
    print(f"accuracy            : {acc['accuracy']:.4f}")
    print(f"severity-weighted R : {scored['severity_weighted_recall']:.4f}")
    print(f"escalation precision: {scored['escalation_precision']:.4f} ({scored['n_escalations']} escalations)")
    print(f"parse rate          : {pr['parse_rate']:.4f}")
    print(f"ECE (self-cons.)    : {cal['ece']:.4f}")
    print(f"wall                : {artifact['metrics']['wall_seconds']}s")
    print("=" * 64)
    print(f"artifact -> {out}")
    return 0


def _majority(samples: list[dict]) -> dict:
    """Majority verdict; ties broken by first occurrence."""
    best, best_n = samples[0], 1
    for s in samples[1:]:
        n = sum(1 for o in samples if o == s)
        if n > best_n:
            best, best_n = s, n
    return best


if __name__ == "__main__":
    raise SystemExit(main())
