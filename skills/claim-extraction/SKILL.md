---
name: claim-extraction
description: Turn a free-text SoW declaration into typed, checkable claims that keep their source locations.
---
# Procedure
1. A claim is one checkable statement about how wealth was accumulated: an employment and its pay, a bonus,
   a property purchase (price, date, how it was funded), a property sale (price, date, proceeds), rental income,
   a gift or loan from a third party, or another source (business, inheritance, investments).
2. One claim per event. Split "I worked at A, then at B" into two claims. Keep a purchase and its funding
   sources in one claim, but extract a separately described gift as its own third_party claim.
3. Fill the typed fields: entity (employer / full property address / funding party), amount (the main figure:
   salary, price, sale price, rent, gift), currency, date (start of employment or event date), period_end,
   event ("monthly salary", "annual bonus", "purchase price", "sale price", "monthly rent", "gift").
4. Keep the wording close to the source. Do not resolve contradictions: if the declaration describes the same
   event twice with different details, extract BOTH claims; the inconsistency is a finding.
5. Skip unverifiable generalities ("my savings were built up over the years") unless they give an amount or event.
6. Categories: employment | property_purchase | property_sale | rental | third_party | other.
   Business ownership, inheritance, investments and crypto are "other" (outside the MVP scope).
7. Every claim must list the chunk ids it came from. No source location, no claim.
