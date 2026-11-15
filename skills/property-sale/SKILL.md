---
name: property-sale
description: Verify a property sale (price, date, ownership) against the Land Registry and trace the receipt of proceeds.
---
# Procedure
1. lookup_property(address=<address>). Find the Assignment FROM the client: compare consideration and date
   with the claim (check_consistency kind=amount and kind=date) and check the client was the owner before it.
2. search_documents("sale proceeds", doc_type=bank_statement) for a credit of proceeds around the completion
   date (proceeds are often net of mortgage redemption, so the credit can be lower than the price).
3. Status:
   - supported: registry sale matches price (±5%) and date, and a bank credit of proceeds is found.
   - potential_red_flag: registry price or date conflicts with the claim, or no sale by the client is
     registered for the address.
   - unresolved: registry consistent but no record of receiving the proceeds (missing_evidence: bank
     statement for the completion month), or the property is not in the registry.
