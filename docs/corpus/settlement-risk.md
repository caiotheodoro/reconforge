# Settlement Risk in FX and Payments

Status: RESEARCH-ONLY corpus. Inline source URLs; uncertain claims marked
**UNVERIFIED**.

## 1. Definitions

- **Settlement risk** (also delivery risk / counterparty risk): the risk that a
  counterparty (or intermediary) fails to deliver the security or its cash
  value after the first party has delivered its side of the deal.
  Source: https://en.wikipedia.org/wiki/Settlement_risk
- **FX settlement risk**: "the risk that one party to a trade of currencies
  fails to deliver the currency owed"; it combines credit risk and liquidity
  risk. In deliverable FX (spot, outright forwards, FX swaps, currency swaps),
  the failure mode is **principal risk** — losing the full value of a leg.
  Sources: https://www.bis.org/publ/qtrpdf/r_qt2212i.htm ;
  https://en.wikipedia.org/wiki/Settlement_risk

## 2. Herstatt risk — definition and the 1974 collapse

- **Herstatt risk** = foreign-exchange settlement risk / cross-currency
  settlement risk, named after Bankhaus Herstatt, Cologne.
  Source: https://en.wikipedia.org/wiki/Settlement_risk
- **What happened (26 June 1974)**: German regulators withdrew Herstatt's
  license at the end of the German banking day (16:30 local time) for lack of
  capital. During that day, counterparties had paid Deutsche Marks to Herstatt
  in Germany, expecting to receive US dollars later that day in New York.
  After ~15:30 Germany / 10:30 New York, Herstatt stopped all dollar payments,
  and counterparties could not collect. Banks had paid away one currency leg
  without receiving the other — the textbook loss-of-principal scenario.
  Source: https://en.wikipedia.org/wiki/Settlement_risk
- **Why it matters**: over the three days after the failure, gross funds
  transferred in the multilateral netting system declined ~60%; it froze
  interbank trust and money-market lending, and became the canonical case for
  why settlement risk is a systemic issue, not just a bilateral credit issue.
  Sources: https://en.wikipedia.org/wiki/CLS_Group ;
  https://www.bis.org/publ/qtrpdf/r_qt2212i.htm
- **Modern instances**: KfW lost ~€300m when Lehman collapsed in 2008; Barclays
  lost ~$130m to a small currency exchange in March 2020.
  Source: https://www.bis.org/publ/qtrpdf/r_qt2212i.htm

## 3. Mitigation: netting, PvP, CLS

### Payment versus payment (PvP)
- **PvP**: a settlement mechanism in which the final payment of one currency
  occurs if, and only if, the final payment of the other currency takes place —
  the two legs of an FX trade settle simultaneously. This removes principal
  risk for the covered legs.
  Sources: https://www.bis.org/publ/qtrpdf/r_qt2212i.htm ;
  https://en.wikipedia.org/wiki/CLS_Group
- Without PvP, one party may deliver its currency and not receive the other.
  Source: https://en.wikipedia.org/wiki/CLS_Group

### CLS (Continuous Linked Settlement)
- CLS Group is a financial market infrastructure whose main entity is
  New-York-based CLS Bank (started operations 9 September 2002), created in
  response to the Herstatt failure (founded July 1997 by the "group of 20"
  banks; BIS CPSS committees — Angell 1989, Lamfalussy 1990, Noël 1993,
  Allsopp 1996 — paved the way).
  Sources: https://en.wikipedia.org/wiki/CLS_Group ;
  https://en.wikipedia.org/wiki/Settlement_risk
- CLS runs a central multicurrency PvP settlement service connected to the
  RTGS systems of participating jurisdictions; it settles in 18 currencies;
  by March 2017 it settled just over 50% of global FX transactions.
  Sources: https://en.wikipedia.org/wiki/CLS_Group ;
  https://www.bis.org/publ/qtrpdf/r_qt2212i.htm
- **How it works (VERIFIED)**: settlement members submit instructions which are
  authenticated and matched; settlement/funding occurs in a ~5-hour window when
  all relevant RTGS systems are open; each member holds a single multi-currency
  account that starts and ends the day at zero; multilateral netting reduces
  funding requirements (netting efficiency ~96% on average); the in/out swap
  compresses payment obligations by ~75%, so funding required in CLS is <1% of
  total gross settlement value. Settlement is final and irrevocable.
  Source: https://en.wikipedia.org/wiki/CLS_Group
- CLS reduces but does not eliminate FX settlement risk (only for eligible
  currencies/pairs).
  Source: https://en.wikipedia.org/wiki/CLS_Group

### Other mitigations
- Pre-settlement netting (bilateral offsetting of obligations) — reduced risk
  on ~$1.3 trillion/day of deliverable turnover in April 2022.
  Source: https://www.bis.org/publ/qtrpdf/r_qt2212i.htm
- On-us settlement (both legs across one institution) with simultaneous
  settlement or loss protection; DvP for securities is the analogous concept.
  Sources: https://www.bis.org/publ/qtrpdf/r_qt2212i.htm ;
  https://en.wikipedia.org/wiki/Delivery_versus_payment
- The FX Global Code (GFXC) calls on participants to use PvP where possible,
  else netting/other risk reduction; BCBS-CPMI supervisory guidance reinforces
  this.
  Source: https://www.bis.org/publ/qtrpdf/r_qt2212i.htm

## 4. How much risk remains (VERIFIED numbers)

- April 2022 BIS Triennial Survey: **$2.2 trillion of daily deliverable FX
  turnover was subject to settlement risk** (31% of deliverable turnover;
  up from ~$1.9tn in April 2019). $2.5tn was settled via CLS; ~$1tn via other
  PvP / on-us-with-loss-protection; ~$1.3tn netted pre-settlement.
  Source: https://www.bis.org/publ/qtrpdf/r_qt2212i.htm
- Why risk remains: PvP unavailable or unsuitable for some currencies/pairs,
  access costs too high for smaller participants, time-zone/liquidity windows.
  Source: https://www.bis.org/publ/qtrpdf/r_qt2212i.htm

## 5. Value dates, cut-offs, T+1/T+2 conventions

- **Value date**: the date on which a transaction settles — funds/assets become
  effective; the date funds are available for use (banking) / the delivery date
  of both FX legs (trading). It often differs from the trade/booking date.
  Source: https://www.investopedia.com/terms/v/valuedate.asp
- **FX spot**: value date is usually **T+2** (two business days after trade
  date) — "the value date for spot trades in foreign currencies is usually set
  for two days after the transaction date."
  Source: https://www.investopedia.com/terms/v/valuedate.asp
  - Independent confirmation from a real MT300: trade date 20020122, value
    date 20020124 (= T+2). Source: https://tkbesx.github.io/convert/MT300%20Example.txt
- **Equities**: US equity settlement moved to **T+1** (value date = one business
  day after trade); bond settlement similar. General T+2 cycles also common
  elsewhere.
  Sources: https://www.investopedia.com/terms/v/valuedate.asp ;
  https://en.wikipedia.org/wiki/Straight-through_processing
- **SEPA credit transfer**: originator debited on acceptance date D, beneficiary
  credited at the latest on D+1.
  Source: https://www.paiementor.com/sepa-payments-schemes-instruments/
- **In messages**: MT103 `:32A` = YYMMDD value date; MT300 `:30T`/`:30V` trade
  and value dates; MT940 `:61` line carries value date, `:60F`/`:62F` opening/
  closing balances carry dates. Sources: paiementor MT103 article;
  https://tkbesx.github.io/convert/MT300%20Example.txt ;
  https://de.wikipedia.org/wiki/MT940
- **Cut-offs / CLS window**: CLS settles during a ~5-hour window when all RTGS
  systems in its currencies are open; central banks can extend RTGS hours to
  widen PvP windows (CPMI discussion).
  Sources: https://en.wikipedia.org/wiki/CLS_Group ;
  https://www.bis.org/publ/qtrpdf/r_qt2212i.htm

## 6. ESTA — verification result

The task brief asked to verify what "ESTA" stands for in an FX-settlement
context. **We could NOT verify any FX-settlement acronym "ESTA"** (no source
found for "Extended Settlement Time Arrangement" or similar; the only ESTA the
sources surface is the US Electronic System for Travel Authorization).
=> **UNVERIFIED.** Treat "ESTA" as a probe/distractor term until a citable
source is added; do not generate ESTA-based facts.

## 7. Relevance to ReconForge reconciliation

- VALUE_DATE_MISMATCH exceptions map directly onto value-date semantics above
  (FX spot T+2, SCT D+1, MT940 line value dates).
- FX_CONVERSION_ERROR in a recon pair is the operational echo of principal-risk
  controls: one leg booked in one currency, cover/statement in another; implied
  rate must be consistent (see CONTRACTS tolerance semantics).
- Settlement-risk facts (Herstatt, CLS, PvP) are the "why" behind the workflow
  controls: cut-offs, finality, cover-before-credit rules.

## 8. UNVERIFIED items

- ESTA in FX context (see §6).
- Currency-pair-specific value-date calendars (weekends/holidays per pair).
- Exact CLS member/fee economics and current share of turnover beyond the
  sources above.
