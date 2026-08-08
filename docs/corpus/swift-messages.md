# SWIFT MT Messages for Reconciliation

Status: RESEARCH-ONLY corpus. Every factual claim carries an inline source URL.
Anything not verifiable is marked **UNVERIFIED**. This document feeds the
ReconForge knowledge graph; treat it as ground truth for generator/verifier logic.

## 0. How MT numbers work

MT (Message Type) numbers encode category / group / type. MT103 = category 1
(customer payments and cheques), group 0 (financial institution transfer),
type 3. MT202 = category 2 (financial institution transfers). MT300 = category 3
(treasury markets — FX, money markets, derivatives). MT940 = category 9
(cash management and customer status).
Source: https://en.wikipedia.org/wiki/SWIFT_message_types

## 1. MT103 — Single Customer Credit Transfer

- **Purpose**: "Instructs a funds transfer" — the standard message for a customer
  (non-bank) credit transfer between financial institutions.
  Source: https://www.paiementor.com/list-of-all-swift-messages-types/
- **Usage**: sent bank-to-bank on behalf of a customer. Can travel in two ways
  (see §6 serial vs cover):
  - *Serial MT103*: the single message that moves funds hop-by-hop down the
    correspondent chain to the beneficiary's bank.
  - *Cover-method MT103 (announcement)*: an "announcement" to the beneficiary's
    bank that funds are coming; it does NOT move the funds itself — the
    accompanying MT202 COV does.
  Source: https://www.paiementor.com/swift-serial-and-cover-payments/

- **Key fields (tag : tag name — mandatory/optional)**:
  | Tag | Name | Req | Notes |
  |---|---|---|---|
  | `:20` | Sender's Reference | M | format 16x; sender-unique ref |
  | `:23B` | Bank Operation Code | M | e.g. CRED |
  | `:23E` | Instruction Code | O | e.g. PHOB (phone beneficiary) |
  | `:32A` | Value Date / Currency / Interbank Settled Amount | M | format `6!n3!a15d` = YYMMDD + 3-letter CCY + up to 15 digits (comma decimal separator) |
  | `:33B` | Currency / Instructed Amount | O (C) | mandatory under rule C2 for many cross-border corridors (e.g. FR→ES); shows the amount instructed before charges/FX |
  | `:50a` | Ordering Customer | M | options A/F/K; F most common |
  | `:52a` | Ordering Institution | O | present only when the sender is not the ordering customer's bank |
  | `:53a` | Sender's Correspondent | O | cover-method messages use 53/54 |
  | `:54a` | Receiver's Correspondent | O | cover-method messages use 53/54 |
  | `:56a` | Intermediary Institution | O | serial messages use 56/57 |
  | `:57a` | Account With Institution | O | serial messages use 56/57; absent ⇒ receiver holds the beneficiary account |
  | `:59a` | Beneficiary Customer | M | options / A / F |
  | `:70` | Remittance Information | O | up to 4x35 |
  | `:71A` | Details of Charges | M | BEN / OUR / SHA |
  | `:72` | Sender to Receiver Information | O | free-text instructions to the receiver (e.g. /REC/ refs); usage rules in SWIFT User Handbook |
  Source (field table): https://www.paiementor.com/mt103-swift-message-with-optional-fields-52a-and-57a/ ;
  Source (cover/serial field usage): https://www.paiementor.com/swift-mt103-202-cover-payment-analysis-part-1/
  Source (:72 existence in MT103): https://www2.swift.com/knowledgecentre/ (User Handbook, login-gated; treated as **UNVERIFIED** here — listed from operator practice).

- **Currency/amount convention**: `:32A` and `:33B` carry (ISO 4217 code)(amount)
  with comma decimal separator, e.g. `USD144750,00`. YYMMDD value date.
  Source: https://www.paiementor.com/mt103-swift-message-with-optional-fields-52a-and-57a/
  Zero-decimal conventions per currency (e.g. JPY) **UNVERIFIED** in our sources.

## 2. MT202 — General Financial Institution Transfer

- **Purpose**: "Requests the movement of funds between financial institutions
  EXCEPT if the transfer is related to an underlying customer credit transfer
  that was sent with the cover method, in which case the MT 202 COV must be
  used."
  Source: https://www.paiementor.com/list-of-all-swift-messages-types/
- **Usage**: bank-to-bank-only payments: interbank funding, nostro rebalancing,
  interest payments, settlement of FX trades.
  Source: https://en.wikipedia.org/wiki/MT202_COV
- **Key fields**: same family as MT103 — `:20` Sender's Reference (M), `:21`
  Related Reference (O), `:32A` Value Date/CCY/Amount (M), `:33B` (O),
  `:53a` Sender's Correspondent (O), `:54a` Receiver's Correspondent (O),
  `:57a` Account With Institution (O), `:58a` Beneficiary Institution (O),
  `:72` (O). Detailed format per SWIFT User Handbook (login-gated): see
  https://www2.swift.com/knowledgecentre/ — field-level detail beyond the
  above is **UNVERIFIED** here.

## 3. MT202 COV — the cover message (CRITICAL)

- **Definition**: MT202 COV is the bank-to-bank cover instruction used for a
  customer credit transfer sent with the cover method. It moves the funds
  between correspondent (nostro) accounts across the correspondent banking
  network, in step with the MT103 announcement sent to the beneficiary's bank.
  Source: https://en.wikipedia.org/wiki/MT202_COV
- **History**: introduced/mandated in 2009, in response to AML/FATF and Wolfsberg
  Group requirements, to give intermediate banks visibility of the origin and
  destination of funds (ordering and beneficiary customer) for risk/AML checks.
  Source: https://en.wikipedia.org/wiki/MT202_COV
- **Mandatory vs optional**: in the MT202 COV Sequence B, `:50a` (ordering
  customer) and `:59a` (beneficiary customer) are MANDATORY — this is the
  structural fix that plain MT202 lacks.
  Source: https://en.wikipedia.org/wiki/MT202_COV
- **Linking ref**: field `:21` (Related Reference) of the MT202 COV carries the
  `:20` (Sender's Reference) of the related MT103.
  Source: SWIFT User Handbook usage rules, quoted by paiementor moderator:
  https://www.paiementor.com/swift-mt103-202-cover-payment-analysis-part-1/
  (comment thread, August 2019 — moderate confidence, treated as VERIFIED by
  two independent operators in the thread).

## 4. MT300 — Foreign Exchange Confirmation (benchmark probe: field-level VERIFIED)

- **Purpose**: "Confirms information agreed to in the buying/selling of two
  currencies" — the confirmation of an FX spot/forward trade between two banks.
  Source: https://www.paiementor.com/list-of-all-swift-messages-types/
- **Verifiable example** (real message, `:22A:NEWT`, `:82A` buyer, `:87A`
  seller, USD/GBP):
  ```
  :15A:
  :20:REF1B
  :22A:NEWT
  :22C:BEBEBB4475CRESZZ
  :82A:BEBEDEBB
  :87A:CRESCHZZ
  :15B:
  :30T:20020122      (trade date YYMMDD)
  :30V:20020124      (value date YYMMDD — T+2 here)
  :36:1,4475         (exchange rate)
  :32B:USD144750,00  (currency + amount bought)
  :57A:CHASU33       (account with institution, bought leg)
  :33B:GBP100000,00  (currency + amount sold)
  :57A:MIDLGB22      (account with institution, sold leg)
  :15C:
  :24D:PHON
  ```
  Source: https://tkbesx.github.io/convert/MT300%20Example.txt
- **Reconciliation relevance**: the MT300 confirms the deal; settlement then
  happens via MT202/MT202 COV or RTGS payments in the two currencies. MT300's
  two amounts and single rate (`:36`) make FX amounts cross-checkable
  (amount_bought x rate ≈ amount_sold).
- Fields `:20`, `:22A`, `:30T`, `:30V`, `:36`, `:32B`, `:33B`, `:82a`, `:87a`,
  `:57a`, `:24D` are all VERIFIED from the example above. Other optional fields
  (e.g. `:77H` ordering customer, `:77D` details) exist in the standard but are
  **UNVERIFIED** in our fetched sources.

## 5. MT940 — Customer Statement Message (end-of-day)

- **Purpose**: "Provides balance and transaction details of an account to a
  financial institution on behalf of the account owner" — the end-of-day
  bank statement; the workhorse for nostro reconciliation.
  Source: https://en.wikipedia.org/wiki/MT940 ;
  https://www.paiementor.com/list-of-all-swift-messages-types/
- **Structure (VERIFIED)**: `:20` transaction reference (M), `:21` related
  reference (O), `:25` account number (M), `:28`/`:28C` statement number (M),
  `:60F`/`:60M` opening/interim balance (M; sub-fields: D/C mark, date, CCY,
  amount), `:61` transaction details (O per the German Wikipedia table: value
  date, booking date, D/C mark, CCY, amount, transaction-type key, reference,
  bank reference, additional info), `:86` free description (O), `:62F`/`:62M`
  closing/interim balance (M).
  Example closing balance line: `:62F:C170403EUR17,00` = credit balance,
  date 17-04-03, EUR 17.00.
  Source: https://de.wikipedia.org/wiki/MT940
- **Long-term replacement**: MT940 → camt.053 (ISO 20022). No fixed cut-off for
  reporting messages as of the migration; MT940 remains usable over FIN during
  transition.
  Source: https://de.wikipedia.org/wiki/Camt-Format

## 6. Serial vs Cover — the decision that matters for reconciliation

- **Cover method ("European method")**: the instructing bank sends TWO messages:
  (1) the **MT103 announcement** to the beneficiary's bank (does not carry
  funds — it announces that funds are coming, for which beneficiary, and via
  which correspondent), and (2) the **MT202 COV** to its own correspondent,
  which actually moves the funds between correspondent accounts. The
  beneficiary's bank usually learns of the credit via MT910/MT950 from its
  correspondent, and reconciles the announcement with that credit.
- **Serial method ("American method")**: ONE message (serial MT103) travels
  hop-by-hop and moves the funds itself.
- Cover-method MT103 uses fields `:53a`/`:54a`; serial MT103 uses `:56a`/`:57a`.
  There is no explicit flag marking a message as serial or cover — the receiver
  infers it from content.
- Sources: https://www.paiementor.com/swift-serial-and-cover-payments/ ;
  https://www.paiementor.com/swift-mt103-202-cover-payment-analysis-part-1/

### Benchmark probe answer (get this right in generated tasks)

> **Which message carries the cover for a customer credit transfer, and which
> bank receives it?**

- The **MT202 COV** carries the cover (the actual interbank funds movement /
  reimbursement) for a customer credit transfer executed with the cover method.
  It is sent by the **instructing bank to the reimbursing bank** (the sender's
  correspondent that holds its nostro account, i.e. field `:53a`'s institution).
- The **MT103** is the announcement/instruction sent **by the instructing bank
  to the beneficiary's bank**; in the serial method the MT103 itself moves the
  funds.
- Plain **MT202** is for pure bank-to-bank transfers and must NOT be used as the
  cover for a customer credit transfer (MT202 COV is mandatory for that since
  2009).
- Sources: https://en.wikipedia.org/wiki/MT202_COV ;
  https://www.paiementor.com/swift-serial-and-cover-payments/ ;
  https://www.paiementor.com/list-of-all-swift-messages-types/

## 7. Reconciliation-relevant behavioral notes

- A received announcement does NOT mean funds arrived; banks may credit early
  only at their own discretion (trust, amount thresholds, customer tier).
  A missing MT202 COV after an MT103 announcement is a classic
  MISSING_MESSAGE/PARTIAL_MATCH exception in ops.
  Source: https://www.paiementor.com/swift-serial-and-cover-payments/
- Charge codes: `:71A` BEN (beneficiary pays all), OUR (sender pays all),
  SHA (shared). Charge deduction can make statement amounts differ from the
  instructed amount — a real-world cause of AMOUNT_MISMATCH.
  Source: https://www.paiementor.com/mt103-swift-message-with-optional-fields-52a-and-57a/
- MT940 statement lines carry a D/C mark and their own value date per line
  (`:61`), which is why value-date mismatches between ledger and statement are
  detectable and material.
  Source: https://de.wikipedia.org/wiki/MT940
- Sender/receiver identity lives in the message header blocks (Blocks 1-3), not
  in the text block; BICs (ISO 9362) identify institutions (tags 50a/52a/56a/
  57a/59a etc.).
  Source: https://en.wikipedia.org/wiki/ISO_9362

## 8. UNVERIFIED items

- MT300 optional fields beyond the fetched example (`:77H`, `:77D`, `:22B`, etc.).
- Full MT202 field-by-field mandatory/optional matrix (User Handbook is
  login-gated).
- `:72` exact format rules for MT103/MT202.
- Per-currency zero-decimal conventions (JPY etc.) from our sources.
