---
name: rental-income
description: Verify rental income against the tenancy agreement, Land Registry ownership and bank rent credits.
---
# Procedure
1. lookup_property(address) — the client must be a registered owner during the rental period.
2. search_documents(<address>, doc_type=tenancy) — compare the monthly rent with the claim (check_consistency).
3. search_documents("rent", doc_type=bank_statement) — look for recurring rent credits of that amount.
4. supported: ownership, tenancy and rent credits agree (±5%). potential_red_flag: tenancy rent or ownership
   conflicts with the claim. unresolved: tenancy agreement or rent credits missing.
