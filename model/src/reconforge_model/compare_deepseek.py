"""Frontier head-to-head: DeepSeek API on the same benchmark tasks.

Concurrent (16 workers) with a per-task JSONL checkpoint, so a partial run is
never wasted: on restart, already-answered task_ids are skipped. Runs the
identical system prompt + payload as the local model, scores with forge's
`score_verdicts` — same yardstick both sides.

Artifact -> docs/validation/bench-deepseek-{run}.json.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from . import metrics
from .schema import parse_verdict, render_user_message, SYSTEM_PROMPT

SHARED_ARTIFACTS = Path("/Users/caiotheodoro/Documents/personal/reconforge/docs/validation")
WORKERS = 16
EMPTY_RETRIES = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compare_deepseek.py")
    parser.add_argument("--tasks-file", required=True, help="task-format JSONL")
    parser.add_argument("--run", default="full")
    parser.add_argument("--checkpoint", default=None, help="JSONL checkpoint path (default data/deepseek-{run}-cp.jsonl)")
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--out-dir", type=str, default=str(SHARED_ARTIFACTS))
    opts = parser.parse_args(argv)

    from openai import OpenAI

    from reconforge_forge.benchmark import score_verdicts
    from reconforge_forge.task import Task

    base_url = os.environ.get("MODEL_PROVIDER_BASE_URL", "https://api.deepseek.com")
    model_id = os.environ.get("MODEL_PROVIDER_MODEL_ID", "deepseek-v4-flash")
    api_key = os.environ.get("MODEL_PROVIDER_API_KEY")
    if not api_key:
        raise SystemExit("MODEL_PROVIDER_API_KEY not set")

    checkpoint = Path(opts.checkpoint or f"data/deepseek-{opts.run}-cp.jsonl")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)

    tasks = [Task.from_dict(json.loads(line)) for line in Path(opts.tasks_file).read_text().splitlines() if line.strip()]
    done: dict[str, dict] = {}
    if checkpoint.exists():
        for line in checkpoint.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["task_id"]] = rec
    pending = [t for t in tasks if t.task_id not in done]

    client = OpenAI(base_url=base_url, api_key=api_key)

    def run_one(task: Task) -> dict:
        if task.task_id in done:
            return done[task.task_id]
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": render_user_message(task.to_dict())},
        ]
        text = ""
        for attempt in range(EMPTY_RETRIES + 1):
            try:
                resp = client.chat.completions.create(
                    model=model_id, messages=messages, temperature=0.0, max_tokens=1024
                )
                text = resp.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001
                text = ""
            if text.strip():
                break
            time.sleep(1.5 * (attempt + 1))
        return {
            "task_id": task.task_id,
            "difficulty": task.difficulty,
            "expected": task.expected,
            "predicted": parse_verdict(text),
            "raw_empty": not text.strip(),
        }

    t0 = time.perf_counter()
    completed = 0
    with ThreadPoolExecutor(max_workers=opts.workers) as pool:
        futures = [pool.submit(run_one, t) for t in pending]
        with open(checkpoint, "a") as fh:
            for fut in as_completed(futures):
                rec = fut.result()
                done[rec["task_id"]] = rec
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                completed += 1
                if completed % 50 == 0:
                    print(f"[deepseek] {completed}/{len(pending)} (+{len(done) - len(pending)} resumed)", flush=True)

    ordered = [done[t.task_id] for t in tasks]
    predictions = [rec["predicted"] for rec in ordered]
    scored = score_verdicts(tasks, predictions)
    acc = metrics.accuracy([t.to_dict() for t in tasks], predictions)
    pr = metrics.parse_rate(predictions)
    n_empty = sum(1 for rec in ordered if rec["raw_empty"])

    artifact = {
        "run": opts.run,
        "benchmark": "reconforge-bench",
        "model": model_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n": len(tasks),
        "metrics": {
            **acc,
            **pr,
            "severity_weighted_recall": scored["severity_weighted_recall"],
            "per_type_recall": scored["severity_recall_by_severity"],
            "escalation_precision": scored["escalation_precision"],
            "n_escalations": scored["n_escalations"],
            "n_parse_misses": scored["n_parse_misses"],
            "n_empty_responses": n_empty,
            "wall_seconds": round(time.perf_counter() - t0, 1),
        },
        "scoring": scored,
        "per_task": ordered,
    }
    out = Path(opts.out_dir) / f"bench-deepseek-{opts.run}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2) + "\n")

    print()
    print("=" * 64)
    print(f"model: {model_id} | n={len(tasks)}")
    print(f"accuracy            : {acc['accuracy']:.4f}")
    print(f"severity-weighted R : {scored['severity_weighted_recall']:.4f}")
    print(f"escalation precision: {scored['escalation_precision']:.4f} ({scored['n_escalations']} escalations)")
    print(f"parse rate          : {pr['parse_rate']:.4f}")
    print(f"empty responses     : {n_empty}")
    print("=" * 64)
    print(f"artifact -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
