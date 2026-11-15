---
name: third-party-funding
description: Verify a gift or loan from a third party (gift letter, transfer record, donor's own source of wealth).
---
# Procedure
1. search_documents("gift", doc_type=letter): donor, recipient, amount, date, gift vs loan.
2. search_documents(<donor name> / "transfer", doc_type=bank_statement): a credit from the donor of that amount.
3. search_policy("third-party gift funding") for what is normally expected.
4. check_consistency: claimed amount vs letter amount (and vs the bank credit, if found).
5. supported: letter and transfer agree (±5%); still add an open question on the donor's own source of wealth.
   potential_red_flag: the letter or transfer conflicts with the claim (amount, donor, loan vs gift).
   unresolved: letter only, no transfer record (missing_evidence: bank record of the transfer; evidence of
   the donor's source of wealth).
