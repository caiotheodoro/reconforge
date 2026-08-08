# ReconForge Knowledge Graph — Entity & Relation Schema

Follows the fixed schema in CONTRACTS.md. Definitions are grounded in the
researched corpus (docs/corpus/swift-messages.md, iso20022.md,
settlement-risk.md, reconciliation-ops.md); examples are concrete instances
that exist in the corpus.

## Entity types

| Entity type | Definition | Instances (from corpus) |
|---|---|---|
| **MessageType** | A standardized financial message format exchanged between institutions (MT or ISO 20022). | MT103, MT202, MT202 COV, MT300, MT940, pacs.008, pacs.009, camt.053, camt.054 |
| **Field** | A specific data element of a message type, identified by tag (MT) or XML element name (ISO 20022), with optionality and format. | :20 Sender's Reference, :32A Value Date/CCY/Amount, :50a Ordering Customer, :59a Beneficiary Customer, :61 statement line, :36 Exchange Rate, EndToEndId, InstrId, ValDt, Amt |
| **PaymentInstruction** | A concrete instruction to move funds (a business object, independent of the message that carries it). | SingleCustomerCreditTransfer, FinancialInstitutionTransfer, CoverPayment (MT103+MT202COV pair), FXSpotDeal (USD/GBP, T+2) |
| **SettlementSystem** | Infrastructure that achieves finality of payment/transfer of value. | CLS (Continuous Linked Settlement), RTGS (Fedwire/T2/CHAPS), T2 (Eurosystem RTGS) |
| **Risk** | A class of adverse settlement or operational outcome the controls are designed against. | HerstattRisk (FX settlement risk), PrincipalRisk, ValueDateMismatch, SettlementRisk |
| **Rule** | A normative requirement (standard, regulation, market practice) that constrains messages or workflows. | MT202COV-mandate (2009), Serial/Cover-method rule (53/54 vs 56/57), SCT-D+1 rule, MT940 :62F mandatory, FX Global Code PvP principle |
| **Instrument** | A financial product/contract whose settlement the messages support. | FX Spot, FX Forward, SEPA Credit Transfer (SCT), Securities Trade (T+1) |
| **Workflow** | A documented operational process in the back office. | NostroReconciliation, CoverMethodSettlement, SerialMethodSettlement, ExceptionInvestigation (camt.056/camt.029) |
| **Currency** | A settlement currency per ISO 4217. | USD, EUR, GBP, JPY |
| **DateConvention** | A value-date/settlement-timing convention. | T+1, T+2 (FX spot), D+1 (SCT), CLS 5-hour settlement window |

## Relation types

| Relation type | Definition | Instances (from corpus) |
|---|---|---|
| **COVERS** | X (message/instrument) semantically implements or is the carrier of Y. | (MT103) -COVERS-> (SingleCustomerCreditTransfer); (MT202) -COVERS-> (FinancialInstitutionTransfer); (pacs.008) -COVERS-> (FIToFICustomerCreditTransfer); (camt.053) -COVERS-> (BankToCustomerStatement) |
| **REQUIRES** | X structurally or normatively requires Y to exist/be populated. | (MT202 COV) -REQUIRES-> (:50a Ordering Customer); (MT202 COV) -REQUIRES-> (:59a Beneficiary Customer); (MT103) -REQUIRES-> (:32A); (CoverPayment) -REQUIRES-> (MT103 Announcement) + (MT202 COV) |
| **HAS_FIELD** | Message type X contains field Y. | (MT103) -HAS_FIELD-> (:20 Sender's Reference); (MT940) -HAS_FIELD-> (:62F Closing Balance); (MT300) -HAS_FIELD-> (:36 Exchange Rate); (camt.053) -HAS_FIELD-> (EndToEndId) |
| **CONFLICTS_WITH** | X is incompatible with Y (using X where Y is mandated is a violation). | (MT202 plain) -CONFLICTS_WITH-> (CustomerCoverPayment) [MT202 COV is mandated]; (SerialMethod) -CONFLICTS_WITH-> (:53a/:54a usage) [serial uses :56a/:57a]; (ValueDateMismatch) -CONFLICTS_WITH-> (T+2 convention) |
| **TRIGGERS** | X causes Y (event/risk → control or workflow). | (HerstattBankFailure 1974) -TRIGGERS-> (HerstattRisk); (HerstattRisk) -TRIGGERS-> (CLS creation); (AnnouncementWithoutCover) -TRIGGERS-> (MISSING_MESSAGE exception); (MissingData) -TRIGGERS-> (NonSTP/repair) |
| **APPLIES_TO** | X (system/rule/risk) governs Y. | (CLS) -APPLIES_TO-> (18 currencies); (FXGlobalCode) -APPLIES_TO-> (PvP adoption); (SCT rule) -APPLIES_TO-> (D+1 credit); (MT940) -APPLIES_TO-> (EndOfDayStatement) |
| **MITIGATES** | X reduces Y. | (CLS) -MITIGATES-> (HerstattRisk); (PvP) -MITIGATES-> (FXSettlementRisk); (PreSettlementNetting) -MITIGATES-> (FXSettlementRisk); (MT202 COV traceability) -MITIGATES-> (AML opacity in covers) |
| **RELATED_TO** | X is associated with Y without the stronger semantics above. | (MT103) -RELATED_TO-> (MT202 COV) [cover pair]; (MT940) -RELATED_TO-> (MT910) [credit confirmation]; (MT103 :21) -RELATED_TO-> (MT202 COV :20 ref linkage); (camt.056) -RELATED_TO-> (exception investigation workflow) |
| **COUNTERPART_OF** | X is the ISO 20022 counterpart/implementation of MT Y. | (pacs.008) -COUNTERPART_OF-> (MT103); (pacs.009) -COUNTERPART_OF-> (MT202/MT202 COV); (camt.053) -COUNTERPART_OF-> (MT940); (camt.054) -COUNTERPART_OF-> (MT900/MT910) |

## Graph-construction guidance

- Materialize message instances (e.g. a specific MT940 with ref OUR-REF-001)
  only at runtime; the schema nodes above are the type layer.
- Fields are nodes so that extraction can attach format/optionality
  (e.g. `:32A` "M, 6!n3!a15d = YYMMDD+CCY+amount").
- Relation direction follows the arrow above (head -> relation -> tail), which
  mirrors gold-triples.json.
- Every node/relation should be traceable to one of the corpus markdown files
  for the grounded gate.
