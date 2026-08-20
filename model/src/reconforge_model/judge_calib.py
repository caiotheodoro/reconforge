"""C1/C2 judge calibration study: golden-set kappa vs the verifier oracle.

Generates a golden set (default seed 333, matching the original C1 study for
comparability), scores it against the DeepSeek judge and the local
fine-tuned worker-as-judge, and reports Cohen's kappa for each against the
verifier-oracle label. Reuses forge's `cohens_kappa` (unit tested) rather
than reimplementing it.

Pass `--prompt judge` (default) to use schema.JUDGE_SYSTEM_PROMPT (explicit
matching rules for VALUE_DATE_MISMATCH / PARTIAL_MATCH / FIELD_CORRUPTION /
DUPLICATE — the C2 rubric fix) or `--prompt worker` to reproduce the
original C1 run with schema.SYSTEM_PROMPT for a clean before/after diff.

Artifacts -> docs/validation/golden-100{-local-judge}{suffix}.jsonl +
docs/validation/judge-calib-{run}.json (kappa summary + confusion tables).
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .schema import JUDGE_SYSTEM_PROMPT, SYSTEM_PROMPT, parse_verdict, render_user_message

SHARED_ARTIFACTS = Path("/Users/caiotheodoro/Documents/personal/reconforge/docs/validation")
DEFAULT_BASE = "mlx-community/Qwen3-1.7B-4bit"


def _label(verdict: dict | None) -> str:
    """Collapse a verdict dict to the single-category label used for kappa:
    exception_type if any, else MATCH, else UNPARSEABLE on a parse miss."""
    if verdict is None:
        return "UNPARSEABLE"
    return verdict.get("exception_type") or "MATCH"


def _confusion(labels: list[str], judges: list[str]) -> dict[str, int]:
    counts: collections.Counter = collections.Counter()
    for label, judge in zip(labels, judges):
        if label != judge:
            counts[f"{label}->{judge}"] += 1
    return dict(counts.most_common())


def _run_deepseek(tasks: list, system_prompt: str) -> list[str]:
    from openai import OpenAI

    base_url = os.environ.get("MODEL_PROVIDER_BASE_URL", "https://api.deepseek.com")
    model_id = os.environ.get("MODEL_PROVIDER_MODEL_ID", "deepseek-v4-flash")
    api_key = os.environ.get("MODEL_PROVIDER_API_KEY")
    if not api_key:
        raise SystemExit("MODEL_PROVIDER_API_KEY not set")
    client = OpenAI(base_url=base_url, api_key=api_key)

    judges = []
    for i, task in enumerate(tasks):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": render_user_message(task.to_dict())},
        ]
        text = ""
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=model_id, messages=messages, temperature=0.1, max_tokens=1024
                )
                text = resp.choices[0].message.content or ""
            except Exception:  # noqa: BLE001
                text = ""
            if text.strip():
                break
            time.sleep(1.5 * (attempt + 1))
        judges.append(_label(parse_verdict(text)))
        if (i + 1) % 20 == 0:
            print(f"[deepseek-judge] {i + 1}/{len(tasks)}", flush=True)
    return judges


def _run_local(tasks: list, system_prompt: str, adapter_path: str, base_model: str) -> list[str]:
    from mlx_lm.generate import generate
    from mlx_lm.lora import load
    from mlx_lm.sample_utils import make_sampler

    model, tokenizer = load(base_model, adapter_path=adapter_path, tokenizer_config={"trust_remote_code": True})
    for attr in ("has_thinking", "enable_thinking"):
        if hasattr(tokenizer, attr):
            setattr(tokenizer, attr, False)
    sampler = make_sampler(temp=0.0)

    judges = []
    for i, task in enumerate(tasks):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": render_user_message(task.to_dict())},
        ]
        prompt = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, enable_thinking=False, return_dict=False
        )
        text = generate(model, tokenizer, prompt, max_tokens=256, sampler=sampler)
        judges.append(_label(parse_verdict(text)))
        if (i + 1) % 20 == 0:
            print(f"[local-judge] {i + 1}/{len(tasks)}", flush=True)
    return judges


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="judge_calib.py")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=333, help="333 matches the original C1 golden set")
    parser.add_argument("--prompt", choices=["judge", "worker"], default="judge",
                         help="judge = JUDGE_SYSTEM_PROMPT (C2 rubric fix); worker = SYSTEM_PROMPT (C1 reproduction)")
    parser.add_argument("--run", default="rubric-v2")
    parser.add_argument("--base-model", default=DEFAULT_BASE)
    parser.add_argument("--adapter-path", default="adapters/champion")
    parser.add_argument("--skip-local", action="store_true", help="DeepSeek judge only")
    parser.add_argument("--skip-deepseek", action="store_true", help="local judge only")
    parser.add_argument("--out-dir", type=str, default=str(SHARED_ARTIFACTS))
    opts = parser.parse_args(argv)

    from reconforge_forge.generator import generate_tasks

    system_prompt = JUDGE_SYSTEM_PROMPT if opts.prompt == "judge" else SYSTEM_PROMPT
    tasks = generate_tasks(opts.n, seed=opts.seed)
    labels = [_label(t.expected) for t in tasks]

    result: dict = {
        "run": opts.run,
        "prompt": opts.prompt,
        "seed": opts.seed,
        "n": len(tasks),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    out_dir = Path(opts.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not opts.skip_deepseek:
        ds_judges = _run_deepseek(tasks, system_prompt)
        from reconforge_forge.seams import cohens_kappa

        ds_kappa = cohens_kappa(labels, ds_judges)
        ds_agree = sum(1 for a, b in zip(labels, ds_judges) if a == b) / len(labels)
        result["deepseek"] = {"kappa": ds_kappa, "agreement": round(ds_agree, 4), "confusion": _confusion(labels, ds_judges)}
        ds_path = out_dir / f"golden-{opts.n}-{opts.run}.jsonl"
        with open(ds_path, "w") as fh:
            for t, label, judge in zip(tasks, labels, ds_judges):
                fh.write(json.dumps({"task_id": t.task_id, "label": label, "judge": judge}) + "\n")
        result["deepseek"]["artifact"] = str(ds_path)
        print(f"[deepseek-judge] kappa={ds_kappa:.4f} agreement={ds_agree:.4f}")

    if not opts.skip_local:
        local_judges = _run_local(tasks, system_prompt, opts.adapter_path, opts.base_model)
        from reconforge_forge.seams import cohens_kappa

        local_kappa = cohens_kappa(labels, local_judges)
        local_agree = sum(1 for a, b in zip(labels, local_judges) if a == b) / len(labels)
        result["local"] = {"kappa": local_kappa, "agreement": round(local_agree, 4), "confusion": _confusion(labels, local_judges)}
        local_path = out_dir / f"golden-{opts.n}-local-judge-{opts.run}.jsonl"
        with open(local_path, "w") as fh:
            for t, label, judge in zip(tasks, labels, local_judges):
                fh.write(json.dumps({"task_id": t.task_id, "label": label, "judge": judge}) + "\n")
        result["local"]["artifact"] = str(local_path)
        print(f"[local-judge] kappa={local_kappa:.4f} agreement={local_agree:.4f}")

    summary_path = out_dir / f"judge-calib-{opts.run}.json"
    summary_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
