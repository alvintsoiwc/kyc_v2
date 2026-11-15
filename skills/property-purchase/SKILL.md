---
name: property-purchase
description: Verify a property purchase and reconcile how it was funded (Land Registry, S&P / assignment, mortgage, bank statements).
---
# Procedure
1. lookup_property(address=<address>). Find the Assignment to the client: compare consideration and date with
   the claim (check_consistency amount and date) and check the client is the registered owner (kind=name).
   Find the Mortgage memorial and compare its amount with any declared mortgage.
2. search_documents for the S&P / assignment (doc_type=property), the mortgage offer (doc_type=mortgage) and
   bank statements covering the payment period (doc_type=bank_statement, within 3 months before completion).
3. Funding reconciliation with calc_wealth_timeline (never by hand):
   - in: opening balance ("Balance brought forward") of the statement before the payments;
   - in: credits explained by a declared source (payroll from the declared employer, rent, sale proceeds,
         a gift backed by a gift letter);
   - in: the mortgage loan at completion;
   - out: the full purchase price at completion ONLY (do NOT also add the deposit or completion balance debit
          rows from the bank statement as 'out' items when the mortgage loan and full purchase price are included,
          as that would double-count the cash down payment).
   Do NOT count unexplained credits (e.g. a large "TT IN" from an unrelated company); list them as conflicts.
   In assessments, report the resulting funding gap in `numbers` under the key `"funding_gap_hkd"`.
4. Each declared funding source must be evidenced: savings -> a bank balance; mortgage -> registry / offer;
   sale proceeds -> a bank credit of proceeds; gift -> a bank credit matching a gift letter.
5. Status:
   - supported: registry matches (±5%), every declared source evidenced, funding gap within 5% of the price.
   - potential_red_flag: registry conflicts with the claim, or the funding gap exceeds 5% (cite the timeline
     result and give the gap in "numbers"), or the payments rely on unexplained credits.
   - unresolved: no bank statement for the payment period, or a declared source is not evidenced
     (missing_evidence: the statement / proceeds record / transfer record to request).
