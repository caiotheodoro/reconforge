"""ReconForge Forge CLI.

Usage:
    uv run python -m reconforge_forge.cli pilot --tasks 300 --seed 7
    uv run python -m reconforge_forge.cli contamination --seed 7

Deterministic: same seed -> byte-identical artifacts in ``docs/validation/``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reconforge_forge.benchmark import run_pilot
from reconforge_forge.contamination import evaluate_monitor, leak_probe
from reconforge_forge.generator import generate_tasks

_DEFAULT_OUT = Path(__file__).resolve().parents[3] / "docs" / "validation"


def cmd_pilot(args: argparse.Namespace) -> int:
    tasks = generate_tasks(args.tasks, seed=args.seed)
    result = run_pilot(tasks, seed=args.seed, out_dir=args.out)

    print(f"\nReconForge pilot — seed {args.seed}, {args.tasks} tasks")
    print(f"  oracle agreement (verifier vs expected): {result['oracle_agreement']:.4f}")
    print(
        "  severity-weighted recall (verifier-as-perfect-model): "
        f"{result['severity_weighted_recall_verifier']:.4f}"
    )
    print(f"  verdict distribution: {result['verdict_distribution']}")
    print(f"  exception distribution: {result['exception_distribution']}")
    print(f"  difficulty mean: {result['difficulty']['mean']} "
          f"(min {result['difficulty']['min']}, max {result['difficulty']['max']})")

    scored = result["scoring"]
    sev = scored["severity_recall_by_severity"]
    print("\n  verifier scoring (must be perfect by construction):")
    print(f"    verdict accuracy: {scored['verdict_accuracy']:.4f}")
    print(f"    severity-weighted recall: {scored['severity_weighted_recall']:.4f}")
    print(f"    per-severity recall: HIGH={sev['HIGH']} MEDIUM={sev['MEDIUM']} LOW={sev['LOW']}")

    if result["oracle_disagreements"]:
        print(
            "\n  WARNING: oracle disagreement on "
            f"{len(result['oracle_disagreements'])} tasks — generator/verifier bug."
        )
        for d in result["oracle_disagreements"][:5]:
            print(f"    {d['task_id']}: expected={d['expected']['exception_type']} "
                  f"verifier={d['verifier']['exception_type']}")
    out = Path(args.out) / f"pilot-{args.seed}.json"
    print(f"\n  wrote {out}")
    return 0


def cmd_contamination(args: argparse.Namespace) -> int:
    train = generate_tasks(args.train, seed=args.seed)
    eval_clean = generate_tasks(args.eval, seed=args.seed + 10_000)
    probe = leak_probe(train, eval_clean)
    result = evaluate_monitor(train, eval_clean, seed=args.seed, out_dir=args.out)

    print(f"\nReconForge contamination monitor — seed {args.seed}")
    print(f"  train signatures: {result['n_train']}, clean eval signatures: {result['n_eval_clean']}")
    print(f"  leak probe on clean eval: overlap={probe['overlap']} fired={probe['fired']}")
    print("\n  ROC study (leak fraction -> fire-on-leaked / false-fire-on-clean):")
    for p in result["points"]:
        print(
            f"    leak {p['leak_fraction']:.2f}: "
            f"fire_on_leaked={p['fire_on_leaked']:.4f} "
            f"false_fire_on_clean={p['false_fire_on_clean']:.4f}"
            f"  (n_leaked={p['n_leaked']}, n_clean={p['n_clean']})"
        )
    out = Path(args.out) / "contamination-roc.json"
    print(f"\n  wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reconforge-forge", description="ReconForge forge CLI")
    p.add_argument("--out", default=str(_DEFAULT_OUT),
                   help=f"artifact output dir (default {_DEFAULT_OUT})")
    sub = p.add_subparsers(dest="cmd", required=True)

    pilot = sub.add_parser("pilot", help="generate a pilot set and run the oracle gate")
    pilot.add_argument("--tasks", type=int, default=300)
    pilot.add_argument("--seed", type=int, default=7)
    pilot.set_defaults(fn=cmd_pilot)

    cont = sub.add_parser("contamination", help="run the contamination ROC study")
    cont.add_argument("--seed", type=int, default=7)
    cont.add_argument("--train", type=int, default=400, help="train-set task count")
    cont.add_argument("--eval", type=int, default=400, help="clean eval-set task count")
    cont.set_defaults(fn=cmd_contamination)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
