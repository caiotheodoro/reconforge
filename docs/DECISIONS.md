# ReconForge — Decision Log

Every architectural decision is recorded here with its rationale. Agents append
entries as they make decisions (format below). The A1 base-model decision and
severity weights are the fixed defaults from the plan; revise only with
measured evidence.

## Format

```
## YYYY-MM-DD — <study id> — <title>
- Decision: ...
- Rationale: ...
- Evidence: (file/metrics)
- Alternatives rejected: ...
```

---

## 2026-08-07 — A1 (default) — Base model: Qwen/Qwen3-1.7B
- Decision: Qwen3-1.7B (Apache-2.0, 32k context), non-thinking worker mode,
  MLX-LoRA fine-tune.
- Rationale: 16GB M5 budget (no CUDA → vLLM impossible, MLX native); narrow
  structured task → 1.7B sufficient; license-safe for public portfolio;
  Qwen3 agent/tool-calling support (SOTA small model, Qwen3 report 2505.09388).
- Evidence: pending A1 pilot (200-task zero-shot).
- Alternatives rejected: Qwen2.5-1.5B (older), Qwen3-0.6B (weaker structured
  output), 7-8B class (does not fit training budget).

## 2026-08-07 — A3 — Exception taxonomy + severity weights
- Decision: 9 exception classes with weights 1.0/0.9/0.6/0.2 as in
  CONTRACTS.md; primary metric = severity-weighted recall.
- Rationale: financial-risk ordering (principal at risk > misdirection >
  timing/STP > data quality); optimizing raw accuracy would reward models
  that only fix low-severity cases.
- Evidence: domain analysis (FX/back-office ops).
