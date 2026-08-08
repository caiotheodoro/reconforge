# Back-Office Reconciliation Operations

Status: RESEARCH-ONLY corpus. Inline source URLs; uncertain claims marked
**UNVERIFIED**. Where the corpus cannot verify an industry figure, it says so —
we do not invent numbers.

## 1. Straight-through processing (STP)

- **Definition**: automated end-to-end processing of payment transactions
  without human intervention; reduces operational risk, cost and cycle time.
  Sources: https://en.wikipedia.org/wiki/Straight-through_processing ;
  https://www.paiementor.com/sepa-payments-schemes-instruments/
- **Why payments fail STP (VERIFIED causes)**:
  - missing information;
  - data not machine-understandable (name-and-address instead of a BIC/IBAN/code);
  - human-readable free-text instructions (e.g. "credit urgently");
  - transactions outside the bank's automatic-processing rules (large value,
    exotic currencies);
  - manual errors: transposed routing-code digits/letters, data-format errors,
    data in wrong fields, invalid data.
  Sources: https://en.wikipedia.org/wiki/Straight-through_processing ;
  https://www.theglobaltreasurer.com/2007/11/22/payment-stp-through-high-quality-data/
- **STP rates in industry**: precise, citable cross-border STP-rate figures
  were **NOT reliably verified** in this research round (search engines
  blocked; SWIFT reports login-gated). Qualitative, verifiable statements only:
  - Banks levy charges for non-STP payments/manual repairs, or price
    correspondent fees by counterparty STP quality — implying STP is well
    below 100% in practice and is a monitored metric.
    Source: https://en.wikipedia.org/wiki/Straight-through_processing
  - ISO 20022/CBPR+ and SEPA are explicitly justified as STP enablers
    (structured data, mandatory payer/payee fields, EndToEndId).
    Sources: https://www.paiementor.com/cbpr-plus-iso-20022-migration/ ;
    https://de.wikipedia.org/wiki/Camt-Format
  - Specific percentages (e.g. "X% of cross-border payments settle STP") →
    **UNVERIFIED**, do not generate as facts.

## 2. The reconciliation workflow (matching ledger vs statement)

The canonical back-office loop for nostro/counterparty reconciliation:

1. **Capture** — ingest both sides:
   - *Ledger/booking side*: our own payment instructions/booking records
     (MT103/MT202/MT300-paired records, internal ledger).
   - *Statement side*: counterparty statements and confirmations
     (MT940 end-of-day, MT950 for account owners, MT910 credit confirmations,
     camt.053/camt.054 in ISO 20022).
     Sources: https://en.wikipedia.org/wiki/MT940 ;
     https://de.wikipedia.org/wiki/Camt-Format
2. **Normalize** — align fields: amounts (decimal, 2dp), currency (ISO 4217
   uppercase), dates (ISO YYYY-MM-DD), refs trimmed; map MT fields to a common
   model (sender ref `:20`, value date/amount `:32A`, ordering/beneficiary
   `:50a`/`:59a`, statement line `:61`).
   Source (field semantics): https://www.paiementor.com/mt103-swift-message-with-optional-fields-52a-and-57a/
3. **Match** — pair ledger records with statement lines on (counterparty
   account, amount±tolerance, currency, value date, beneficiary). In cover
   method, the beneficiary bank reconciles the MT103 announcement against the
   MT910/MT950 credit that follows the MT202 COV — the announcement and the
   cover are two halves of one transaction.
   Source: https://www.paiementor.com/swift-serial-and-cover-payments/
4. **Classify exceptions** — anything unmatched or inconsistent becomes an
   exception ticket (§3).
5. **Resolve / escalate** — auto-adjust, rebook, reject, or escalate (§4).
6. **Evidence & audit** — keep the message trail for regulated reporting (§5).

## 3. Exception categories seen in production ops (map to CONTRACTS taxonomy)

| Production symptom | ReconForge exception_type | Notes / sources |
|---|---|---|
| Amount differs between sides | AMOUNT_MISMATCH | Charge deduction (`:71A` BEN/OUR/SHA) and fee/deduction lines legitimately change the credited amount. Source: https://www.paiementor.com/mt103-swift-message-with-optional-fields-52a-and-57a/ |
| One leg foreign currency, implied rate off | FX_CONVERSION_ERROR | MT300 confirms one rate for two amounts (`:36`); any booking/statement rate deviation is an FX error. Source: https://tkbesx.github.io/convert/MT300%20Example.txt |
| Ordering/beneficiary differs | BENEFICIARY_MISMATCH | `:50a`/`:59a` are mandatory in MT103 and in MT202 COV Sequence B — reliable cross-check points. Sources: paiementor MT103 article; https://en.wikipedia.org/wiki/MT202_COV |
| Account/counterparty differs | COUNTERPARTY_MISMATCH | Account identity: `:25` (MT940), `:57a`/`:58a`; BIC (ISO 9362) identifies institutions. Sources: https://de.wikipedia.org/wiki/MT940 ; https://en.wikipedia.org/wiki/ISO_9362 |
| Value date differs | VALUE_DATE_MISMATCH | Statement lines carry value dates (`:61` in MT940); value-date conventions: FX spot T+2, SCT D+1. Sources: https://de.wikipedia.org/wiki/MT940 ; https://www.investopedia.com/terms/v/valuedate.asp ; https://www.paiementor.com/sepa-payments-schemes-instruments/ |
| Announcement received, cover/credit never arrives | MISSING_MESSAGE | Cover method: MT103 announcement ≠ funds; credit arrives via MT202 COV → MT910/950. A missing cover is a real ops break. Source: https://www.paiementor.com/swift-serial-and-cover-payments/ |
| Same transaction booked twice | DUPLICATE | Duplicate `:20` refs or double presentation of announcement+cover as two bookings. Source: MT202 COV linkage via `:21`→`:20` (paiementor cover article) |
| Line matches some fields but not all (e.g. amount ok, date off) | PARTIAL_MATCH | Ambiguous by design; needs human judgment (CONTRACTS: weight 0.5). Source: corpus classification |
| Field corrupted / unusable data | FIELD_CORRUPTION | Non-STP drivers: format errors, wrong-field data, invalid codes. Source: https://www.theglobaltreasurer.com/2007/11/22/payment-stp-through-high-quality-data/ |

## 4. Severity, escalation, and disposition

- **Severity logic (corpus position, aligned with CONTRACTS weights)**:
  principal-at-risk issues (amount, FX, beneficiary, counterparty) are HIGH;
  timing/data-quality issues (value date, missing message, partial, duplicate,
  corruption) are MEDIUM/LOW.
  Source: CONTRACTS.md (fixed taxonomy — A3).
- **Escalation triggers observed in practice**:
  - high-value or anomalous payments routed out of automatic processing
    (STP rule-bases); Source: https://en.wikipedia.org/wiki/Straight-through_processing
  - cover-method receipts where the credit (MT910/950) is missing or the
    announcement/cover pair disagrees; Source: https://www.paiementor.com/swift-serial-and-cover-payments/
  - cancellation/return workflows via camt.056/camt.029 (ISO 20022) and
    MT192/MT195/MT292/MT295 (FIN). Sources: https://de.wikipedia.org/wiki/Camt-Format ;
    https://www.paiementor.com/sepa-payments-schemes-instruments/
- **Dispositions**:
  - *Auto-adjust*: tolerances met (rounding, charges, FX within window).
  - *Reject/return*: wrongful credit or unmatchable instruction — return flow
    (e.g. SEPA pacs.004 Payment Return; camt.056 cancellation).
  - *Rebook*: value-date or booking corrections (camt.087 Request to Modify
    Payment / value-date correction in SEPA).
    Source: https://www.paiementor.com/sepa-payments-schemes-instruments/
  - *Flag-review*: PARTIAL_MATCH / FIELD_CORRUPTION where human judgment is
    mandatory.

## 5. Audit and evidence requirements in regulated operations

- The SWIFT message trail is the evidentiary record: message headers have been
  held by English courts to constitute a valid electronic signature; messages
  are retained and reconstructible (sender/receiver, refs, timestamps).
  Source: https://en.wikipedia.org/wiki/SWIFT_message_types
- Regulated ops must be able to demonstrate:
  - who instructed, who booked, who confirmed (sender/receiver BIC per block);
    Source: https://en.wikipedia.org/wiki/ISO_9362
  - end-to-end traceability of funds origin and destination — the very reason
    MT202 COV (with mandatory `:50a`/`:59a`) replaced plain MT202 for covers;
    Source: https://en.wikipedia.org/wiki/MT202_COV
  - AML/sanctions screening decisions (structured ISO 20022 data improves
    compliance/false-positive rates); Source: https://www.paiementor.com/cbpr-plus-iso-20022-migration/
  - settlement risk management posture (PvP usage, netting, limits) per the FX
    Global Code / BCBS-CPMI guidance; Source: https://www.bis.org/publ/qtrpdf/r_qt2212i.htm
- Evidence records for recon: pair (ledger record + statement line/message
  copy), match keys, exception classification, disposition and timestamps —
  retained for audit.

## 6. UNVERIFIED items

- Numeric industry STP rates (see §1).
- Specific SLAs/cut-off times per currency/corridor for cover vs serial.
- The operational share of each exception category in production (no citable
  distribution found; do not generate frequency priors).
