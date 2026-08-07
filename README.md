# ReconForge

Benchmark-grade evaluation for financial back-office reconciliation agents.

A cadence-driven system where a locally fine-tuned Qwen3-1.7B (MLX-LoRA) is
measured head-to-head against frontier models on a synthetic reconciliation
benchmark built with a reproduced ARC-style benchmark methodology.

**Status: under construction — see `CONTRACTS.md` for the coordination
contracts, `docs/DECISIONS.md` for the decision log, and the workstream
directories (`forge/`, `knowledge/`, `model/`, `system/`) for the build.**

## Workstreams

- `forge/` — seeded task generator, verifier-as-oracle, benchmark, contamination monitor
- `knowledge/` — domain corpus, GraphRAG extraction, Neo4j graph, grounded gate
- `model/` — dataset builder, MLX-LoRA fine-tuning, calibration, eval
- `system/` — microservices, Kafka, Temporal Cloud workflows, cadence jobs
- `docs/corpus/` — researched domain corpus (SWIFT, ISO 20022, settlement risk, ops)

## Quickstart

```sh
cp .env.example .env   # fill in secrets
make forge-test
```
