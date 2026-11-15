---
name: employment-income
description: Verify an employment / salary / bonus claim against the Companies Registry, payslips, employment letters and tax notices.
---
# Procedure
1. lookup_company(name=<employer>). Check the employer existed during the claimed period:
   incorporation date not after the claimed start (check_consistency kind=date_order), not dissolved before
   the end of the period. Not found -> unresolved with an open question (may be an overseas employer).
2. search_documents(<employer>, doc_type=payslip) and (doc_type=employment_letter). The payslip employer may
   use a short form or a Chinese name — compare with kind=name; ask the officer only if it decides the status.
3. Amounts with check_consistency (never by hand):
   - monthly salary vs payslip basic salary (or gross pay if no basic salary line);
   - bonus vs the payslip bonus line;
   - if a salaries-tax notice exists for a year the claimed salary applies to: claimed monthly x 12
     (multiplier 12) vs total income from employment.
   - employment start date vs the employment letter start date (kind=date).
4. Status:
   - supported: employer existed in the period, a payslip or letter matches entity and amount within 5%,
     and every check is consistent. Cite the registry record, the document spans and the check result.
   - potential_red_flag: employer incorporated after the claimed start / dissolved before the claimed end,
     or any amount / date check inconsistent. State each conflict with the figures from the check.
   - unresolved: no payslip / letter / tax notice for the employer -> missing_evidence names what to request.
For the document checklist: read_skill_reference("employment-income", "references/hk-documents.md").
