"""Multi-hop probe questions: the eval set for retrieval quality (D2 study).

Each probe carries the question, a human expected answer, the expected gate
verdict over the reference corpus (used for offline sanity checks), and the
target entities the retrieval should surface. Probes 1-3 are ordered to be
answerable by the deterministic (offline) pipeline end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True, slots=True)
class Probe:
    id: str
    question: str
    expected_answer: str
    target_verdict: str
    target_entities: tuple[str, ...]


PROBES: List[Probe] = [
    Probe(
        id="P01",
        question="Does MT103 require cover for a customer credit transfer?",
        expected_answer=(
            "No — cover is provided via MT202; MT103 is the customer transfer "
            "itself (MT103 CONFLICTS_WITH CoverPayment, MT202 COVERS CoverPayment)."
        ),
        target_verdict="CONTRADICT",
        target_entities=("MT103", "MT202", "CoverPayment", "CustomerCreditTransfer"),
    ),
    Probe(
        id="P02",
        question="Which system mitigates Herstatt risk?",
        expected_answer="CLS (continuous linked settlement), via PvP settlement.",
        target_verdict="SUPPORT",
        target_entities=("CLS", "HerstattRisk", "PaymentVersusPayment"),
    ),
    Probe(
        id="P03",
        question="Which message type confirms an FX trade?",
        expected_answer="MT300 (FX trade confirmation).",
        target_verdict="SUPPORT",
        target_entities=("MT300", "FXTradeConfirmation", "ForeignExchangeTrade"),
    ),
    Probe(
        id="P04",
        question="Which message type reports a customer credit transfer?",
        expected_answer="MT103 (SWIFT) or pacs.008 (ISO equivalent).",
        target_verdict="SUPPORT",
        target_entities=("MT103", "pacs.008", "CustomerCreditTransfer"),
    ),
    Probe(
        id="P05",
        question="What relation connects MT103 and MT202 in a cover payment flow?",
        expected_answer="MT103 RELATED_TO MT202; the cover leg is MT202 COVERS CoverPayment.",
        target_verdict="SUPPORT",
        target_entities=("MT103", "MT202", "CoverPayment"),
    ),
    Probe(
        id="P06",
        question="Which statement message type is the ISO counterpart of MT940?",
        expected_answer="camt.053 (bank-to-customer statement).",
        target_verdict="SUPPORT",
        target_entities=("MT940", "camt.053", "AccountStatement"),
    ),
    Probe(
        id="P07",
        question="What happens when the value date is later than the booking date?",
        expected_answer=(
            "Late booking: VALUE_DATE_MISMATCH (MEDIUM severity) with settlement "
            "timing and interest implications."
        ),
        target_verdict="SUPPORT",
        target_entities=("ValueDate", "LateValueDateRule", "ValueDateMismatchRisk"),
    ),
    Probe(
        id="P08",
        question="What is the difference between a nostro account and a vostro account?",
        expected_answer=(
            "Perspective-dependent naming: one bank's nostro is the counterparty's "
            "vostro (NostroAccount COUNTERPART_OF VostroAccount)."
        ),
        target_verdict="SILENT",
        target_entities=("NostroAccount", "VostroAccount"),
    ),
    Probe(
        id="P09",
        question="Which risk does CLS mitigate?",
        expected_answer="Herstatt risk (principal/settlement risk).",
        target_verdict="SUPPORT",
        target_entities=("CLS", "HerstattRisk"),
    ),
    Probe(
        id="P10",
        question="What is straight through processing (STP)?",
        expected_answer="Automated end-to-end processing with no manual intervention.",
        target_verdict="SUPPORT",
        target_entities=("StraightThroughProcessing", "NoManualIntervention"),
    ),
    Probe(
        id="P11",
        question="What is the value date convention for FX spot trades?",
        expected_answer="T+2 (two business days after the trade date).",
        target_verdict="SUPPORT",
        target_entities=("SpotFxTrade", "ValueDateTPlus2", "TPlus2Convention"),
    ),
    Probe(
        id="P12",
        question="What triggers a VALUE_DATE_MISMATCH?",
        expected_answer=(
            "A value date later than the booking date beyond the allowed window "
            "(late booking)."
        ),
        target_verdict="SUPPORT",
        target_entities=("LateValueDateRule", "ValueDateMismatch", "ValueDate"),
    ),
]


def get_probes(ids: List[str]) -> List[Probe]:
    by_id = {p.id: p for p in PROBES}
    return [by_id[i] for i in ids if i in by_id]


def all_probes() -> List[Probe]:
    return list(PROBES)
