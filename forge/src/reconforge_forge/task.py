"""Task model — the recon pair (CONTRACTS.md task schema).

A ``Task`` is one ledger-vs-statement pair plus the authoritative
``expected`` verdict written by the generator (which knows the truth it
injected). ``to_dict``/``from_dict`` roundtrip is lossless.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Task:
    task_id: str
    seed: int
    difficulty: float
    ledger: dict[str, Any]
    statement: dict[str, Any] | None
    expected: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "seed": self.seed,
            "difficulty": self.difficulty,
            "ledger": dict(self.ledger),
            "statement": None if self.statement is None else dict(self.statement),
            "expected": dict(self.expected),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        st = d.get("statement")
        return cls(
            task_id=str(d["task_id"]),
            seed=int(d["seed"]),
            difficulty=float(d["difficulty"]),
            ledger=dict(d["ledger"]),
            statement=None if st is None else dict(st),
            expected=dict(d["expected"]),
        )
