# Source-of-Wealth Verification Memo (draft): Wong Ka Yan

Run `20261114-131210-980a6c` · client ref `SYN-CL-002` · started 2026-11-14T13:12:10Z · system `C` · model `mock/mock-scripted-policy`

> **For human compliance review.** This draft lists what the declaration claims, what the evidence shows and what is missing. A *potential red flag* is a review trigger, not a finding of misconduct. The agent cannot approve or reject onboarding; the compliance officer decides next steps.
> **SYNTHETIC DATA:** client, documents and registry records are fictional.
> **MOCK MODEL:** decisions were produced by the scripted mock policy, not an LLM.

## Summary

| Status | Claims |
|---|---|
| ✓ Supported | 2 |
| ? Unresolved | 0 |
| ⚑ Potential red flag | 1 |

3 claims extracted from the declaration; 6 documents in the packet; 14 evidence items; 2 PII spans masked at intake; 0 documents to request.

## Wealth timeline

| Date | Claim | Event | Amount | Status |
|---|---|---|---|---|
| 2019-01 | C1 | monthly salary — Silverline Digital Limited | HKD 62,000 | ✓ Supported |
| 2023-03 | C2 | annual bonus — Silverline Digital Limited | HKD 120,000 | ✓ Supported |
| 2023-10 | C3 | purchase price — Flat 8C, Harbour Crest, 22 Ocean Road, Tseung Kwan O | HKD 9,800,000 | ⚑ Potential red flag |

## 1. Income

### C1 · employment · ✓ Supported

**Declared:** “I have worked at Silverline Digital Limited as Senior Software Engineer since January 2019, earning HKD 62,000 per month.”  
_Source: 01_declaration.md, section 'Sources of wealth', line 10_  
_Typed: entity `Silverline Digital Limited` · amount `HKD 62,000` · date `2019-01` · event `monthly salary`_

**Finding:** Silverline Digital Limited (CR 2581144, incorporated 2016-07-11, Live) existed in the claimed period, and the documents agree with the claim within tolerance.

**Computed figures (from the calculator):** claimed_hkd = 62,000, documented_hkd = 62,000

**Evidence:**
- [E1] Client declaration: 01_declaration.md, section 'Sources of wealth', line 10 _(client assertion)_
- [E3] Mock Companies Registry: CR 2581144 — Silverline Digital Limited (銀線數碼有限公司), incorporated 2016-07-11, status Live _(SYNTHETIC)_
- [E2] Client document: 02_payslip_2023-03.md, section 'Payslip', lines 2-20 _(SYNTHETIC)_
- [E4] Client document: 03_tax_assessment_2023-24.md, section 'Notice of salaries tax assessment', lines 2-9 _(SYNTHETIC)_
- [E5] Consistency checker: employment start not before the employer's incorporation: consistent; monthly salary vs payslip: consistent (0.0% diff); monthly salary x 12 vs salaries tax 2023/24: consistent (0.0% diff) _(computed)_

**Independent reviewer:** agrees the cited spans support this finding — cited spans mention the claimed entity and figures

### C2 · employment · ✓ Supported

**Declared:** “I received an annual bonus of HKD 120,000 in March 2023 from Silverline Digital Limited.”  
_Source: 01_declaration.md, section 'Sources of wealth', line 11_  
_Typed: entity `Silverline Digital Limited` · amount `HKD 120,000` · date `2023-03` · event `annual bonus`_

**Finding:** Silverline Digital Limited (CR 2581144, incorporated 2016-07-11, Live) existed in the claimed period, and the documents agree with the claim within tolerance.

**Computed figures (from the calculator):** claimed_hkd = 120,000, documented_hkd = 120,000

**Evidence:**
- [E6] Client declaration: 01_declaration.md, section 'Sources of wealth', line 11 _(client assertion)_
- [E3] Mock Companies Registry: CR 2581144 — Silverline Digital Limited (銀線數碼有限公司), incorporated 2016-07-11, status Live _(SYNTHETIC)_
- [E2] Client document: 02_payslip_2023-03.md, section 'Payslip', lines 2-20 _(SYNTHETIC)_
- [E7] Consistency checker: employment start not before the employer's incorporation: consistent; bonus vs payslip: consistent (0.0% diff); bonus month vs payslip period: consistent _(computed)_

**Independent reviewer:** agrees the cited spans support this finding — cited spans mention the claimed entity and figures

## 2. Property

### C3 · property_purchase · ⚑ Potential red flag

**Declared:** “In October 2023 I purchased Flat 8C, Harbour Crest, 22 Ocean Road, Tseung Kwan O for HKD 9,800,000, funded by a mortgage of HKD 6,860,000 and my savings.”  
_Source: 01_declaration.md, section 'Sources of wealth', line 12_  
_Typed: entity `Flat 8C, Harbour Crest, 22 Ocean Road, Tseung Kwan O` · amount `HKD 9,800,000` · date `2023-10` · event `purchase price`_

**Finding:** The declared funding (mortgage and savings) does not reconcile with the purchase price; the calculator shows a funding gap beyond tolerance.

**Computed figures (from the calculator):** funding_gap_hkd = 1,669,000

**Evidence:**
- [E8] Client declaration: 01_declaration.md, section 'Sources of wealth', line 12 _(client assertion)_
- [E11] Mock Land Registry: PR-TKO-HC-8C — Flat 8C, Harbour Crest, 22 Ocean Road, Tseung Kwan O, New Territories; 2023-10-20 Assignment HKD 9,800,000; 2023-10-20 Mortgage HKD 6,860,000 _(SYNTHETIC)_
- [E10] Client document: 05_provisional_sale_and_purchase.md, section 'Provisional agreement for sale and purchase', lines 2-10 _(SYNTHETIC)_
- [E9] Client document: 06_mortgage_offer.md, section 'Mortgage offer letter', lines 2-10 _(SYNTHETIC)_
- [E12] Client document: 04_bank_statement_2023-09.md, section 'Bank statement', lines 2-18 _(SYNTHETIC)_
- [E13] Consistency checker: purchase price vs Land Registry consideration: consistent (0.0% diff); purchase date vs Land Registry assignment: consistent; declared mortgage vs registered mortgage: consistent (0.0% diff) _(computed)_
- [E14] Calculator: Funding of Flat 8C, Harbour Crest, 22 Ocean Road, Tseung Kwan O: in HKD 8,131,000, out HKD 9,800,000, lowest balance HKD -1,669,000, funding gap HKD 1,669,000 _(computed)_

**Conflicts:**
- Documented savings, explained credits and the mortgage leave a funding gap of HKD 1,669,000 against the price of HKD 9,800,000.
- Payments rely on credits not explained by any declared source: 2023-09-15 TT IN KAIWING HOLDINGS LTD HKD 1,800,000

**Open questions:**
- Ask the client to explain and evidence the unexplained credits / funding gap.

**Independent reviewer:** agrees the cited spans support this finding — the cited records show the stated conflict

## 3. Third-party funding and other sources

_No claims in this section._

## 4. Cross-claim consistency

_No conflicting statements detected within the declaration._

## 5. Outstanding questions and documents to request

1. (C3) Ask the client to explain and evidence the unexplained credits / funding gap.

## Officer decision (to be completed by a human)

- [ ] Evidence sufficient for the assessed risk
- [ ] Further documents requested (see section 5)
- [ ] Escalate for enhanced review

Officer: ____________ Date: ____________

## Evidence log

| ID | Type | Source | Identifier | Location | Retrieved |
|---|---|---|---|---|---|
| E1 | declaration | Client declaration | 01_declaration.md#3 | 01_declaration.md, section 'Sources of wealth', line 10 | 2026-11-14T13:12:10Z |
| E2 | document | Client document | 02_payslip_2023-03.md#1 | 02_payslip_2023-03.md, section 'Payslip', lines 2-20 | 2026-11-14T13:12:10Z |
| E3 | registry | Mock Companies Registry | 2581144 | Mock Companies Registry: 2581144 | 2026-11-14T13:12:10Z |
| E4 | document | Client document | 03_tax_assessment_2023-24.md#1 | 03_tax_assessment_2023-24.md, section 'Notice of salaries tax assessment', lines 2-9 | 2026-11-14T13:12:10Z |
| E5 | calculation | Consistency checker | consistency:dfff556784 | Consistency checker: consistency:dfff556784 | 2026-11-14T13:12:10Z |
| E6 | declaration | Client declaration | 01_declaration.md#4 | 01_declaration.md, section 'Sources of wealth', line 11 | 2026-11-14T13:12:10Z |
| E7 | calculation | Consistency checker | consistency:0d0994e6dd | Consistency checker: consistency:0d0994e6dd | 2026-11-14T13:12:10Z |
| E8 | declaration | Client declaration | 01_declaration.md#5 | 01_declaration.md, section 'Sources of wealth', line 12 | 2026-11-14T13:12:10Z |
| E9 | document | Client document | 06_mortgage_offer.md#1 | 06_mortgage_offer.md, section 'Mortgage offer letter', lines 2-10 | 2026-11-14T13:12:10Z |
| E10 | document | Client document | 05_provisional_sale_and_purchase.md#1 | 05_provisional_sale_and_purchase.md, section 'Provisional agreement for sale and purchase', lines 2-10 | 2026-11-14T13:12:10Z |
| E11 | registry | Mock Land Registry | PR-TKO-HC-8C | Mock Land Registry: PR-TKO-HC-8C | 2026-11-14T13:12:10Z |
| E12 | document | Client document | 04_bank_statement_2023-09.md#1 | 04_bank_statement_2023-09.md, section 'Bank statement', lines 2-18 | 2026-11-14T13:12:10Z |
| E13 | calculation | Consistency checker | consistency:0974405d6c | Consistency checker: consistency:0974405d6c | 2026-11-14T13:12:10Z |
| E14 | calculation | Calculator | timeline:6a78e2f7d3 | Calculator: timeline:6a78e2f7d3 | 2026-11-14T13:12:10Z |

## Run log

- Model calls: 15 · tool calls: 15 (errors: 0) · format repairs: 0 · verification rejections: 0 · gate downgrades: 0
- Tokens in/out: 49522/2042 (estimated) · estimated cost: $0.0000 · evidence rounds: 1
- Model latency p50/p95: 0.2/0.4 ms · tool latency p50/p95: 4.4/10.5 ms · wall time: 0.17 s
- Tasks: T1 [employment-income] done (finished); T2 [employment-income] done (finished); T3 [property-purchase] done (finished)
