"""Deterministic, keyword-based fallback extractor.

Used in OFFLINE mode (no API), as a per-chunk fallback when the LLM
extraction fails, and as the first-load fallback for the system seam. Emits
schema-valid triples from keyword patterns and a curated fact table aligned
with the corpus gold triples (docs/corpus/gold-triples.json). Confidence is
~0.6 (contract: schema-valid always, deterministic).

Encoding decisions (see DECISIONS.md):
- Negations ("MT103 does not carry the cover") are encoded as
  ``CONFLICTS_WITH`` so the lexical gate can return CONTRADICT.
- Entity aliases are stored in ``properties["aliases"]`` and appended to the
  triple's index text by :mod:`reconforge_knowledge.vector_index`, so
  camelCase canonical names stay lexical-match friendly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .schema import Entity, Relation, Triples, validate_extraction

DEFAULT_CONFIDENCE = 0.6
MESSAGE_TYPE_CONFIDENCE = 0.8

# --------------------------------------------------------------------------- #
# Domain-prior fact table (aligned with docs/corpus/gold-triples.json)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Fact:
    head: str
    relation: str
    tail: str
    triggers: Tuple[str, ...]
    head_type: str = "MessageType"
    tail_type: str = "PaymentInstruction"
    confidence: float = DEFAULT_CONFIDENCE
    aliases: Tuple[str, ...] = ()


FACTS: Tuple[Fact, ...] = (
    # --- MT message semantics (gold #1-4, #18-19, #23) ---
    Fact("MT103", "COVERS", "SingleCustomerCreditTransfer", ("mt103",),
         tail_type="PaymentInstruction",
         aliases=("single customer credit transfer", "customer credit transfer", "customer transfer")),
    Fact("MT202", "COVERS", "FinancialInstitutionTransfer", ("mt202",),
         tail_type="PaymentInstruction",
         aliases=("general financial institution transfer", "bank to bank transfer", "interbank funding")),
    Fact("MT202COV", "COVERS", "CoverPaymentForCustomerCreditTransfer", ("mt202 cov",),
         tail_type="PaymentInstruction",
         aliases=("cover payment", "cover", "MT202 COV", "the cover for a customer credit transfer")),
    Fact("MT202", "COVERS", "FXTradeSettlement", ("mt202", "fx"),
         tail_type="PaymentInstruction",
         aliases=("settlement of FX trades", "FX settlement")),
    Fact("MT940", "COVERS", "EndOfDayStatement", ("mt940",),
         tail_type="Instrument",
         aliases=("account statement", "end-of-day bank statement", "customer statement")),
    Fact("MT300", "COVERS", "ForeignExchangeConfirmation", ("mt300",),
         tail_type="Instrument",
         aliases=("FX trade confirmation", "confirms an FX trade", "confirmation of an FX trade")),
    # --- ISO 20022 semantics (gold #41-42, #45-46) ---
    Fact("pacs.008", "COVERS", "FIToFICustomerCreditTransfer", ("pacs.008",),
         tail_type="PaymentInstruction",
         aliases=("customer credit transfer", "FI to FI customer credit transfer", "SCT interbank message")),
    Fact("pacs.009", "COVERS", "FinancialInstitutionCreditTransfer", ("pacs.009",),
         tail_type="PaymentInstruction",
         aliases=("financial institution credit transfer", "bank to bank transfer")),
    Fact("camt.053", "COVERS", "BankToCustomerStatement", ("camt.053",),
         tail_type="Instrument",
         aliases=("bank to customer statement", "account statement", "end-of-day statement")),
    Fact("camt.054", "COVERS", "DebitCreditNotification", ("camt.054",),
         tail_type="Instrument",
         aliases=("debit credit notification", "booking notification")),
    # --- cross-format mapping (gold #43-46, entity-schema) ---
    Fact("pacs.008", "COUNTERPART_OF", "MT103", ("pacs.008", "mt103"),
         tail_type="MessageType",
         aliases=("ISO replacement of MT103", "ISO counterpart of MT103")),
    Fact("pacs.009", "COUNTERPART_OF", "MT202", ("pacs.009", "mt202"),
         tail_type="MessageType",
         aliases=("ISO replacement of MT202", "ISO counterpart of MT202", "MT202 COV pattern")),
    Fact("camt.053", "COUNTERPART_OF", "MT940", ("camt.053", "mt940"),
         tail_type="MessageType",
         aliases=("ISO replacement of MT940", "ISO counterpart of MT940")),
    Fact("camt.054", "COUNTERPART_OF", "MT910", ("camt.054", "mt910"),
         tail_type="MessageType",
         aliases=("ISO replacement of MT900 MT910", "ISO counterpart of MT900")),
    Fact("ISO20022", "RELATED_TO", "XMLSyntax", ("iso 20022", "xml"),
         head_type="SettlementSystem", tail_type="Field",
         aliases=("XML syntax", "ISO standard for electronic data interchange")),
    # --- cover method (gold #5-9, #17; corpus swift-messages §3, §6) ---
    Fact("MT202", "CONFLICTS_WITH", "CustomerCoverPayment", ("mt202", "cover", "customer"),
         tail_type="PaymentInstruction",
         aliases=("plain MT202", "must not be used as the cover for a customer credit transfer",
                  "MT202 COV is mandatory for customer covers since 2009")),
    Fact("MT103", "CONFLICTS_WITH", "CoverPaymentForCustomerCreditTransfer", ("mt103", "cover"),
         tail_type="PaymentInstruction",
         aliases=("MT103 does not carry the cover", "MT103 announcement does not move the funds",
                  "cover is carried by MT202 COV")),
    Fact("MT103Announcement", "RELATED_TO", "MT202COV", ("announcement", "mt202 cov"),
         head_type="PaymentInstruction", tail_type="MessageType",
         aliases=("MT103 announcement", "announcement and cover are two halves of one transaction",
                  "cover pair")),
    Fact("CoverPayment", "REQUIRES", "MT103Announcement", ("cover", "announcement"),
         head_type="PaymentInstruction", tail_type="PaymentInstruction",
         aliases=("cover requires the MT103 announcement",)),
    Fact("CoverPayment", "REQUIRES", "MT202COV", ("cover", "mt202 cov"),
         head_type="PaymentInstruction", tail_type="MessageType",
         aliases=("cover payment is carried by MT202 COV",)),
    Fact("MT940", "RELATED_TO", "MT910", ("mt940", "mt910"),
         tail_type="MessageType",
         aliases=("credit confirmation", "MT910 credit confirmation")),
    # --- fields (gold #10-17, #20-28) ---
    Fact("MT103", "HAS_FIELD", "Tag20_SendersReference", ("mt103",),
         tail_type="Field", confidence=0.95, aliases=("field 20 sender reference", "sender unique ref")),
    Fact("MT103", "HAS_FIELD", "Tag32A_ValueDateCurrencyAmount", ("mt103",),
         tail_type="Field", confidence=0.95, aliases=("value date currency amount", "interbank settled amount")),
    Fact("MT103", "HAS_FIELD", "Tag33B_InstructedAmount", ("mt103",),
         tail_type="Field", confidence=0.95, aliases=("instructed amount", "currency instructed amount")),
    Fact("MT103", "HAS_FIELD", "Tag71A_DetailsOfCharges", ("mt103",),
         tail_type="Field", confidence=0.95, aliases=("details of charges", "BEN OUR SHA")),
    Fact("MT103", "REQUIRES", "Tag50_OrderingCustomer", ("mt103",),
         tail_type="Field", confidence=0.95, aliases=("ordering customer mandatory",)),
    Fact("MT103", "REQUIRES", "Tag59_BeneficiaryCustomer", ("mt103",),
         tail_type="Field", confidence=0.95, aliases=("beneficiary customer mandatory",)),
    Fact("MT103Cover", "HAS_FIELD", "Tag53a_SendersCorrespondent", ("mt103", "cover", "53a"),
         head_type="PaymentInstruction", tail_type="Field", confidence=0.9,
         aliases=("senders correspondent", "cover method uses 53 54")),
    Fact("MT103Serial", "HAS_FIELD", "Tag57a_AccountWithInstitution", ("mt103", "serial", "57a"),
         head_type="PaymentInstruction", tail_type="Field", confidence=0.9,
         aliases=("account with institution", "serial method uses 56 57")),
    Fact("MT202COV", "HAS_FIELD", "Tag21_RelatedReference", ("mt202 cov",),
         tail_type="Field", confidence=0.85, aliases=("related reference links the MT103 reference",)),
    Fact("MT202COV", "REQUIRES", "Tag50a_OrderingCustomer", ("mt202 cov",),
         tail_type="Field", confidence=0.93, aliases=("ordering customer mandatory in MT202 COV",)),
    Fact("MT202COV", "REQUIRES", "Tag59a_BeneficiaryCustomer", ("mt202 cov",),
         tail_type="Field", confidence=0.93, aliases=("beneficiary customer mandatory in MT202 COV",)),
    Fact("MT940", "HAS_FIELD", "Tag61_TransactionDetails", ("mt940",),
         tail_type="Field", confidence=0.95, aliases=("statement line", "transaction details")),
    Fact("MT940", "HAS_FIELD", "Tag62F_ClosingBalance", ("mt940",),
         tail_type="Field", confidence=0.95, aliases=("closing balance", "62F mandatory")),
    Fact("MT940", "HAS_FIELD", "Tag25_AccountNumber", ("mt940",),
         tail_type="Field", confidence=0.95, aliases=("account number", "account identification")),
    Fact("MT300", "HAS_FIELD", "Tag30T_TradeDate", ("mt300",),
         tail_type="Field", confidence=0.95, aliases=("trade date")),
    Fact("MT300", "HAS_FIELD", "Tag30V_ValueDate", ("mt300",),
         tail_type="Field", confidence=0.95, aliases=("value date")),
    Fact("MT300", "HAS_FIELD", "Tag36_ExchangeRate", ("mt300",),
         tail_type="Field", confidence=0.95, aliases=("exchange rate", "single rate for two amounts")),
    Fact("MT300", "HAS_FIELD", "Tag32B_AmountBought", ("mt300",),
         tail_type="Field", confidence=0.9, aliases=("amount bought")),
    Fact("MT300", "HAS_FIELD", "Tag33B_AmountSold", ("mt300",),
         tail_type="Field", confidence=0.9, aliases=("amount sold")),
    Fact("camt.053", "HAS_FIELD", "EndToEndId", ("camt.053",),
         tail_type="Field", confidence=0.9, aliases=("end to end id", "end to end reference")),
    # --- settlement risk (gold #33-40) ---
    Fact("HerstattBankFailure", "TRIGGERS", "HerstattRisk", ("herstatt",),
         head_type="Risk", tail_type="Risk", confidence=0.95,
         aliases=("Herstatt bank collapse 1974", "Herstatt failure")),
    Fact("HerstattRisk", "TRIGGERS", "CLSCreation", ("herstatt", "cls"),
         head_type="Risk", tail_type="Workflow", confidence=0.93,
         aliases=("CLS was created in response to the Herstatt failure", "founded July 1997")),
    Fact("CLS", "MITIGATES", "HerstattRisk", ("cls",),
         head_type="SettlementSystem", tail_type="Risk", confidence=0.97,
         aliases=("continuous linked settlement", "settlement risk", "principal risk")),
    Fact("PaymentVersusPayment", "MITIGATES", "FXSettlementRisk", ("pvp",),
         head_type="SettlementSystem", tail_type="Risk", confidence=0.97,
         aliases=("PvP", "payment versus payment", "settles the two legs simultaneously")),
    Fact("PreSettlementNetting", "MITIGATES", "FXSettlementRisk", ("netting",),
         head_type="SettlementSystem", tail_type="Risk", confidence=0.95,
         aliases=("bilateral offsetting of obligations",)),
    Fact("CLS", "APPLIES_TO", "18Currencies", ("cls", "18"),
         head_type="SettlementSystem", tail_type="Currency", confidence=0.97,
         aliases=("settles in 18 currencies", "central multicurrency PvP")),
    Fact("CLS", "RELATED_TO", "FiveHourSettlementWindow", ("cls", "window"),
         head_type="SettlementSystem", tail_type="DateConvention", confidence=0.9,
         aliases=("five hour settlement window", "5 hour window", "PvP window")),
    Fact("FXGlobalCode", "APPLIES_TO", "PvPAdoption", ("fx global code", "pvp"),
         head_type="Rule", tail_type="Workflow", confidence=0.9,
         aliases=("use PvP where possible", "GFXC")),
    # --- value date / booking conventions (gold #29-32, entity-schema) ---
    Fact("ValueDate", "RELATED_TO", "DateFundsBecomeAvailable", ("value date",),
         head_type="DateConvention", tail_type="DateConvention", confidence=0.95,
         aliases=("the date funds become available", "the date on which a transaction settles",
                  "often differs from the trade or booking date")),
    Fact("SpotFxTrade", "REQUIRES", "ValueDateTPlus2", ("spot", "t+2"),
         head_type="Instrument", tail_type="DateConvention", confidence=0.95,
         aliases=("FX spot value date is T+2", "two business days after trade date")),
    Fact("EquityTrade", "REQUIRES", "SettlementTPlus1", ("equit", "t+1"),
         head_type="Instrument", tail_type="DateConvention", confidence=0.9,
         aliases=("US equity settlement moved to T+1", "value date one business day after trade")),
    Fact("SEPACreditTransfer", "REQUIRES", "BeneficiaryCreditByDPlus1", ("sepa", "d+1"),
         head_type="Instrument", tail_type="DateConvention", confidence=0.9,
         aliases=("beneficiary credited at the latest on D+1", "SCT D+1 rule")),
    Fact("LateValueDateRule", "TRIGGERS", "ValueDateMismatch", ("value date", "booking"),
         head_type="Rule", tail_type="Risk", confidence=0.8,
         aliases=("late value date", "value date later than the booking date", "late booking")),
    Fact("ValueDateMismatch", "CONFLICTS_WITH", "TPlus2Convention", ("value date", "t+2"),
         head_type="Risk", tail_type="DateConvention", confidence=0.8,
         aliases=("VALUE_DATE_MISMATCH", "late value date", "breaks the T+2 convention")),
    # --- STP (gold #49-51) ---
    Fact("MissingInformation", "TRIGGERS", "NonSTP", ("missing information",),
         head_type="Risk", tail_type="Risk", confidence=0.9,
         aliases=("missing information breaks STP",)),
    Fact("ManualDataEntryError", "TRIGGERS", "NonSTP", ("manual error",),
         head_type="Risk", tail_type="Risk", confidence=0.85,
         aliases=("manual data entry errors", "transposed routing code")),
    Fact("StraightThroughProcessing", "REQUIRES", "NoManualIntervention", ("stp",),
         head_type="Workflow", tail_type="Workflow", confidence=0.9,
         aliases=("STP", "straight through processing",
                  "automated end-to-end processing without human intervention")),
    # --- serial vs cover methods ---
    Fact("SerialMethod", "CONFLICTS_WITH", "Tag53a_SendersCorrespondent", ("serial", "53a"),
         head_type="Workflow", tail_type="Field", confidence=0.8,
         aliases=("serial method uses 56 57", "serial method conflicts with 53 54 usage")),
    Fact("CoverMethodSettlement", "RELATED_TO", "MT202COV", ("cover method",),
         head_type="Workflow", tail_type="MessageType", confidence=0.8,
         aliases=("European method", "cover method sends two messages")),
)

MESSAGE_TYPE_FIELDS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "MT103": (
        ("Tag20", "SenderReference"),
        ("Tag23B", "BankOperationCode"),
        ("Tag32A", "ValueDateCurrencyAmount"),
        ("Tag33B", "InstructedAmount"),
        ("Tag50a", "OrderingCustomer"),
        ("Tag52a", "OrderingInstitution"),
        ("Tag53a", "SendersCorrespondent"),
        ("Tag54a", "ReceiversCorrespondent"),
        ("Tag56a", "IntermediaryInstitution"),
        ("Tag57a", "AccountWithInstitution"),
        ("Tag59a", "BeneficiaryCustomer"),
        ("Tag70", "RemittanceInformation"),
        ("Tag71A", "DetailsOfCharges"),
        ("Tag72", "SenderToReceiverInformation"),
    ),
    "MT202": (
        ("Tag20", "SenderReference"),
        ("Tag21", "RelatedReference"),
        ("Tag32A", "ValueDateCurrencyAmount"),
        ("Tag53a", "SendersCorrespondent"),
        ("Tag57a", "AccountWithInstitution"),
        ("Tag58a", "BeneficiaryInstitution"),
    ),
    "MT300": (
        ("Tag15A", "NewSequence"),
        ("Tag20", "SenderReference"),
        ("Tag22A", "TypeOfTrade"),
        ("Tag30T", "TradeDate"),
        ("Tag30V", "ValueDate"),
        ("Tag36", "ExchangeRate"),
        ("Tag32B", "AmountBought"),
        ("Tag33B", "AmountSold"),
        ("Tag82A", "Buyer"),
        ("Tag87A", "Seller"),
        ("Tag57A", "AccountWithInstitution"),
    ),
    "MT940": (
        ("Tag20", "TransactionReference"),
        ("Tag21", "RelatedReference"),
        ("Tag25", "AccountNumber"),
        ("Tag28C", "StatementNumber"),
        ("Tag60F", "OpeningBalance"),
        ("Tag61", "TransactionDetails"),
        ("Tag62F", "ClosingBalance"),
        ("Tag64", "ClosingAvailableBalance"),
        ("Tag86", "InformationToAccountOwner"),
    ),
    "pacs.008": (
        ("GrpHdr", "GroupHeader"),
        ("PmtId", "PaymentIdentification"),
        ("InstrId", "InstructionIdentification"),
        ("EndToEndId", "EndToEndIdentification"),
        ("IntrBkSttlmAmt", "InterbankSettlementAmount"),
        ("ValDt", "ValueDate"),
        ("Dbtr", "Debtor"),
        ("Cdtr", "Creditor"),
    ),
    "pacs.009": (
        ("GrpHdr", "GroupHeader"),
        ("PmtId", "PaymentIdentification"),
        ("InstrId", "InstructionIdentification"),
        ("EndToEndId", "EndToEndIdentification"),
        ("IntrBkSttlmAmt", "InterbankSettlementAmount"),
        ("ValDt", "ValueDate"),
        ("DbtrAgt", "DebtorAgent"),
        ("CdtrAgt", "CreditorAgent"),
    ),
    "camt.053": (
        ("GrpHdr", "GroupHeader"),
        ("Stmt", "StatementIdentification"),
        ("Ntry", "Entry"),
        ("ValDt", "ValueDate"),
        ("BookgDt", "BookingDate"),
        ("EndToEndId", "EndToEndIdentification"),
    ),
    "camt.054": (
        ("GrpHdr", "GroupHeader"),
        ("Ntfctn", "Notification"),
        ("Ntry", "Entry"),
        ("ValDt", "ValueDate"),
        ("BookgDt", "BookingDate"),
    ),
}

MESSAGE_TYPES = tuple(MESSAGE_TYPE_FIELDS.keys())
CURRENCIES = ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD")

# --- gold-triples name -> entity type resolution --------------------------- #
GOLD_TYPES: Dict[str, str] = {
    # message types
    "MT103": "MessageType", "MT202": "MessageType", "MT202COV": "MessageType",
    "MT940": "MessageType", "MT300": "MessageType", "MT910": "MessageType",
    "pacs.008": "MessageType", "pacs.009": "MessageType",
    "camt.053": "MessageType", "camt.054": "MessageType",
    # payment instructions / covers
    "SingleCustomerCreditTransfer": "PaymentInstruction",
    "FinancialInstitutionTransfer": "PaymentInstruction",
    "CoverPaymentForCustomerCreditTransfer": "PaymentInstruction",
    "CustomerCoverPayment": "PaymentInstruction",
    "FXTradeSettlement": "PaymentInstruction",
    "FIToFICustomerCreditTransfer": "PaymentInstruction",
    "FinancialInstitutionCreditTransfer": "PaymentInstruction",
    "MT103Announcement": "PaymentInstruction",
    "MT103Cover": "PaymentInstruction", "MT103Serial": "PaymentInstruction",
    "CoverPayment": "PaymentInstruction",
    # fields
    "Tag50a_OrderingCustomer": "Field", "Tag59a_BeneficiaryCustomer": "Field",
    "Tag53a_SendersCorrespondent": "Field", "Tag57a_AccountWithInstitution": "Field",
    "Tag20_SendersReference": "Field", "Tag32A_ValueDateCurrencyAmount": "Field",
    "Tag50_OrderingCustomer": "Field", "Tag59_BeneficiaryCustomer": "Field",
    "Tag71A_DetailsOfCharges": "Field", "Tag33B_InstructedAmount": "Field",
    "Tag21_RelatedReference": "Field", "Tag61_TransactionDetails": "Field",
    "Tag62F_ClosingBalance": "Field", "Tag25_AccountNumber": "Field",
    "Tag30T_TradeDate": "Field", "Tag30V_ValueDate": "Field",
    "Tag36_ExchangeRate": "Field", "Tag32B_AmountBought": "Field",
    "Tag33B_AmountSold": "Field", "EndToEndId": "Field",
    "XMLSyntax": "Field", "USD2_2TrillionDailyAtRisk2022": "Field",
    # instruments / products
    "SpotFxTrade": "Instrument", "EquityTrade": "Instrument",
    "SEPACreditTransfer": "Instrument", "ForeignExchangeConfirmation": "Instrument",
    "EndOfDayStatement": "Instrument",
    # settlement systems / infrastructure
    "CLS": "SettlementSystem", "PaymentVersusPayment": "SettlementSystem",
    "PreSettlementNetting": "SettlementSystem", "ISO20022": "SettlementSystem",
    # risk
    "HerstattBankFailure": "Risk", "HerstattRisk": "Risk",
    "FXSettlementRisk": "Risk", "NonSTP": "Risk",
    "MissingInformation": "Risk", "ManualDataEntryError": "Risk",
    # rules
    "FXGlobalCode": "Rule",
    # workflows
    "CLSCreation": "Workflow", "StraightThroughProcessing": "Workflow",
    "NoManualIntervention": "Workflow",
    # currencies / date conventions
    "18Currencies": "Currency",
    "ValueDateTPlus2": "DateConvention", "SettlementTPlus1": "DateConvention",
    "BeneficiaryCreditByDPlus1": "DateConvention", "ValueDate": "DateConvention",
    "DateFundsBecomeAvailable": "DateConvention",
    "FiveHourSettlementWindow": "DateConvention",
}


# --------------------------------------------------------------------------- #
# Matching helpers
# --------------------------------------------------------------------------- #
_WORD_RE = re.compile(r"\b[a-z0-9.#]+\b")


def _contains(text_lower: str, trigger: str) -> bool:
    """Word-boundary presence test for single-word and phrase triggers."""
    if re.fullmatch(r"[\w.#]+", trigger):
        return re.search(rf"(?<![a-z0-9.]){re.escape(trigger)}(?![a-z0-9])", text_lower) is not None
    return trigger.lower() in text_lower


def _sentence_around(text: str, trigger: str) -> str:
    """Return the sentence containing the trigger (for evidence), else ''."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if trigger.lower() in sentence.lower():
            snippet = sentence.strip()
            return snippet[:220]
    return ""


def _normalize(text: str) -> str:
    """Lowercase and normalize SWIFT message notation ("MT 202" -> "mt202")."""
    return text.lower().replace("mt ", "mt")


# --------------------------------------------------------------------------- #
# Extractor
# --------------------------------------------------------------------------- #
def extract_document(text: str, source: str = "") -> Triples:
    """Run the deterministic extractor over one document.

    Returns schema-valid :class:`Triples` (validates via constructor).
    """
    text_lower = _normalize(text)

    entities: Dict[Tuple[str, str], Entity] = {}
    relations: List[Relation] = []

    def add_entity(name: str, etype: str, aliases: Sequence[str] = ()) -> None:
        key = (name, etype)
        if key not in entities:
            props: Dict[str, object] = {}
            if aliases:
                props["aliases"] = list(aliases)
            entities[key] = Entity(name=name, type=etype, properties=props)

    def add_relation(head: str, relation: str, tail: str, evidence: str,
                     confidence: float, source: str) -> None:
        relations.append(Relation(
            head=head, relation=relation, tail=tail,
            evidence=evidence, confidence=confidence, source=source,
        ))

    present_messages = [mt for mt in MESSAGE_TYPES if _contains(text_lower, mt)]
    present_currencies = [ccy for ccy in CURRENCIES if _contains(text_lower, ccy)]

    for mt in present_messages:
        add_entity(mt, "MessageType")
    for ccy in present_currencies:
        add_entity(ccy, "Currency")

    for mt in present_messages:
        for tag, label in MESSAGE_TYPE_FIELDS[mt]:
            add_entity(f"{tag} {label}", "Field")
            add_entity(mt, "MessageType")
            add_relation(
                mt, "HAS_FIELD", f"{tag} {label}",
                evidence=_sentence_around(text, mt),
                confidence=MESSAGE_TYPE_CONFIDENCE,
                source=source,
            )

    for fact in FACTS:
        if not all(_contains(text_lower, t) for t in fact.triggers):
            continue
        add_entity(fact.head, fact.head_type, fact.aliases)
        add_entity(fact.tail, fact.tail_type, fact.aliases)
        trigger = fact.triggers[0]
        add_relation(
            fact.head, fact.relation, fact.tail,
            evidence=_sentence_around(text, trigger),
            confidence=fact.confidence,
            source=source,
        )

    triples = Triples(entities=list(entities.values()), relations=relations)
    validate_extraction(triples.entities, triples.relations)
    return triples


def extract_documents(docs: Iterable[Tuple[str, str]]) -> Triples:
    """Extract over an iterable of (source_ref, text) pairs, merging results.

    Entities deduped by (name, type); relations merged (no duplicates).
    Deterministic ordering.
    """
    merged_entities: Dict[Tuple[str, str], Entity] = {}
    seen_relations: set = set()
    relations: List[Relation] = []

    for source, text in sorted(docs, key=lambda item: item[0]):
        triples = extract_document(text, source=source)
        for entity in triples.entities:
            merged_entities[(entity.name, entity.type)] = entity
        for rel in triples.relations:
            key = (rel.head, rel.relation, rel.tail, rel.source)
            if key not in seen_relations:
                seen_relations.add(key)
                relations.append(rel)

    merged = Triples(entities=list(merged_entities.values()), relations=relations)
    validate_extraction(merged.entities, merged.relations)
    return merged


def load_gold_triples(path: Optional[str] = None) -> Triples:
    """Load docs/corpus/gold-triples.json as schema-valid Triples.

    Entity types are resolved via ``GOLD_TYPES``; names without a type are
    skipped (with a warning) so the result is always schema-valid.
    """
    import json
    import logging

    logger = logging.getLogger("reconforge_knowledge.deterministic_extractor")
    from pathlib import Path

    if path is None:
        root = Path(__file__).resolve().parent.parent.parent.parent
        path = str(root / "docs" / "corpus" / "gold-triples.json")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    entities: Dict[Tuple[str, str], Entity] = {}
    relations: List[Relation] = []
    skipped = 0
    for entry in payload:
        head, tail = entry["head"], entry["tail"]
        if head not in GOLD_TYPES or tail not in GOLD_TYPES:
            skipped += 1
            continue
        for name, etype in ((head, GOLD_TYPES[head]), (tail, GOLD_TYPES[tail])):
            entities.setdefault((name, etype), Entity(name=name, type=etype))
        relations.append(Relation(
            head=head, relation=entry["relation"], tail=tail,
            evidence=f"gold triple: {entry.get('source', '')}",
            confidence=float(entry.get("confidence", 0.9)),
            source=entry.get("source", "gold-triples.json"),
        ))
    if skipped:
        logger.warning("gold loader skipped %d entries with unknown entity types", skipped)
    merged = Triples(entities=list(entities.values()), relations=relations)
    validate_extraction(merged.entities, merged.relations)
    return merged
