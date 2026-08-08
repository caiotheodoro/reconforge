"""Pure decision logic: threshold classification of a model Verdict into a pipeline outcome."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from reconforge_system.contracts import Verdict


class Outcome(str, Enum):
    ESCALATE = "escalate"
    VERDICT = "verdict"
    EXCEPTION = "exception"


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reason: str
    provisional: Verdict


def classify(verdict: Verdict, confidence_threshold: float, escalate_severities: list[str]) -> Decision:
    if verdict.verdict == "ESCALATE":
        return Decision(Outcome.ESCALATE, "model asked for escalation", verdict)
    if verdict.severity in escalate_severities:
        return Decision(Outcome.ESCALATE, f"severity {verdict.severity} always escalates", verdict)
    if verdict.confidence < confidence_threshold:
        return Decision(
            Outcome.ESCALATE,
            f"confidence {verdict.confidence:.3f} below threshold {confidence_threshold}",
            verdict,
        )
    if verdict.verdict == "EXCEPTION":
        return Decision(Outcome.EXCEPTION, "exception recorded", verdict)
    return Decision(Outcome.VERDICT, "match recorded", verdict)
