"""MLX-LoRA fine-tuning entrypoint for the ReconForge worker model.

Wraps mlx_lm.lora (train_model) with our defaults: rank 16, alpha 32
(=> scale = alpha/rank = 2.0), dropout 0.05, on a quantized Qwen3-1.7B base
for memory headroom on the 16GB M5. Non-thinking mode is enforced by
disabling the tokenizer's `has_thinking` (Qwen3 chat template with
enable_thinking=False).
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
import types
from pathlib import Path

from .dataset_builder import build_datasets, load_tasks

DEFAULT_BASE = "mlx-community/Qwen3-1.7B-4bit"

CONFIG_DEFAULTS = {
    "model": DEFAULT_BASE,
    "train": True,
    "test": False,
    "fine_tune_type": "lora",
    "optimizer": "adamw",
    "optimizer_config": {"adam": {}, "adamw": {}, "muon": {}, "sgd": {}, "adafactor": {}},
    "data": None,
    "seed": 7,
    "num_layers": 16,
    "batch_size": 4,
    "iters": 100,
    "val_batches": -1,
    "learning_rate": 1e-5,
    "steps_per_report": 10,
    "steps_per_eval": 50,
    "resume_adapter_file": None,
    "adapter_path": "adapters/lora",
    "save_every": 50,
    "max_seq_length": 2048,
    "grad_checkpoint": False,
    "grad_accumulation_steps": 1,
    "clear_cache_threshold": 0,
    "lr_schedule": None,
    "mask_prompt": False,
    "report_to": None,
    "project_name": None,
    "lora_parameters": {"rank": 16, "dropout": 0.05, "scale": 2.0},
    "quantization": None,
}


def build_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="train.py", description="MLX-LoRA fine-tune the ReconForge worker"
    )
    parser.add_argument("--base-model", default=DEFAULT_BASE, help="HF repo or local dir for the base model")
    parser.add_argument("--train-file", type=str, help="train.jsonl produced by the dataset builder")
    parser.add_argument("--val-file", type=str, help="val.jsonl produced by the dataset builder")
    parser.add_argument("--data-dir", type=str, help="directory with train.jsonl/val.jsonl (alternative to --train-file)")
    parser.add_argument("--steps", type=int, default=100, help="training iterations")
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=float, default=32.0)
    parser.add_argument("--dropout", type=float, default=0.05)
    parser.add_argument("--out-dir", type=str, default="adapters/lora", help="adapter output dir")
    parser.add_argument("--quantize", type=int, choices=[0, 4, 8], default=4,
                        help="quantize an unquantized base for QLoRA (0 = load base as-is)")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--num-layers", type=int, default=16)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--save-every", type=int, default=50, help="steps between adapter checkpoints")
    parser.add_argument("--grad-checkpoint", action="store_true",
                        help="recompute activations in backward to cut memory")
    parser.add_argument("--clear-cache-threshold", type=str, default=None,
                        help="clear the MLX allocator cache between steps when it exceeds this (e.g. 2g)")
    return parser.parse_args(argv)


def prepare_data_dir(opts: argparse.Namespace) -> str:
    """Ensure mlx-lm sees train.jsonl + valid.jsonl (its loader requires the
    literal `valid` name). Builds data in a staging dir under the out-dir."""
    stage = Path(opts.out_dir) / "data"
    stage.mkdir(parents=True, exist_ok=True)
    if opts.data_dir:
        src = Path(opts.data_dir)
        for name in ("train.jsonl", "val.jsonl"):
            target = stage / (name.replace("val.jsonl", "valid.jsonl"))
            shutil.copyfile(src / name, target)
        return str(stage)
    if not opts.train_file or not opts.val_file:
        raise SystemExit("provide --data-dir or both --train-file and --val-file")
    shutil.copyfile(opts.train_file, stage / "train.jsonl")
    shutil.copyfile(opts.val_file, stage / "valid.jsonl")
    return str(stage)


def main(argv: list[str] | None = None) -> int:
    opts = build_args(argv)

    from mlx_lm.lora import load, load_dataset, train_model
    from mlx_lm.tuner.trainer import evaluate
    from mlx_lm.tuner.datasets import CacheDataset
    import mlx.core as mx

    data_dir = prepare_data_dir(opts)

    args_dict = dict(CONFIG_DEFAULTS)
    args_dict.update(
        {
            "model": opts.base_model,
            "data": data_dir,
            "iters": opts.steps,
            "batch_size": opts.batch_size,
            "learning_rate": opts.learning_rate,
            "num_layers": opts.num_layers,
            "max_seq_length": opts.max_seq_length,
            "seed": opts.seed,
            "save_every": opts.save_every,
            "steps_per_eval": min(50, opts.steps),
            "adapter_path": opts.out_dir,
            "grad_checkpoint": opts.grad_checkpoint,
            "lora_parameters": {
                "rank": opts.rank,
                "dropout": opts.dropout,
                "scale": opts.alpha / opts.rank,
            },
        }
    )
    if opts.clear_cache_threshold:
        args_dict["clear_cache_threshold"] = _parse_size(opts.clear_cache_threshold)

    if opts.quantize and not opts.base_model.startswith("mlx-community"):
        # On-the-fly QLoRA quantization of a full-precision base.
        args_dict["quantization"] = {"group_size": 64, "bits": opts.quantize}
        model_config = {"quantization": args_dict["quantization"]}
    elif opts.quantize and opts.base_model.startswith("mlx-community"):
        print(f"[train] base {opts.base_model} is already quantized; --quantize {opts.quantize} ignored")
        model_config = None
    else:
        model_config = None

    args = types.SimpleNamespace(**args_dict)
    mx.random.seed(args.seed)

    print(f"[train] loading base model: {args.model}")
    t0 = time.perf_counter()
    model, tokenizer = load(
        args.model,
        tokenizer_config={"trust_remote_code": True},
        model_config=model_config,
    )
    # Enforce Qwen3 non-thinking mode (chat template enable_thinking=False).
    for attr in ("has_thinking", "enable_thinking"):
        if hasattr(tokenizer, attr):
            setattr(tokenizer, attr, False)

    train_set, valid_set, _ = load_dataset(args, tokenizer)
    print(f"[train] train={len(train_set)} valid={len(valid_set)}")

    print(f"[train] LoRA rank={opts.rank} alpha={opts.alpha} scale={opts.alpha / opts.rank:.2f} "
          f"dropout={opts.dropout} iters={opts.steps}")
    t_start = time.perf_counter()
    train_model(args, model, train_set, valid_set)
    train_seconds = time.perf_counter() - t_start

    # Final validation loss on the whole validation set.
    val_loss = evaluate(
        model=model,
        dataset=CacheDataset(valid_set),
        batch_size=args.batch_size,
        num_batches=args.val_batches,
        max_seq_length=args.max_seq_length,
    )
    peak_gb = mx.get_peak_memory() / 1e9
    print(f"[train] final val loss {val_loss:.4f} | wall {train_seconds:.1f}s | peak mem {peak_gb:.2f} GB")

    summary = {
        "base_model": args.model,
        "adapter_path": str(Path(opts.out_dir).resolve()),
        "steps": opts.steps,
        "rank": opts.rank,
        "alpha": opts.alpha,
        "scale": opts.alpha / opts.rank,
        "dropout": opts.dropout,
        "quantize": opts.quantize,
        "learning_rate": opts.learning_rate,
        "seed": opts.seed,
        "n_train": len(train_set),
        "n_valid": len(valid_set),
        "final_val_loss": float(val_loss),
        "wall_seconds": round(train_seconds, 1),
        "peak_memory_gb": round(peak_gb, 2),
    }
    summary_path = Path(opts.out_dir) / "train_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"[train] summary -> {summary_path}")
    return 0


def _parse_size(spec: str) -> int:
    """Parse a size like '2g' / '500m' / '1048576' into bytes (mlx-lm style)."""
    spec = spec.strip().lower()
    if spec.endswith("g"):
        return int(float(spec[:-1]) * 1e9)
    if spec.endswith("m"):
        return int(float(spec[:-1]) * 1e6)
    return int(spec)


if __name__ == "__main__":
    raise SystemExit(main())
