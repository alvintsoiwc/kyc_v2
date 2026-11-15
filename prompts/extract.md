PHASE: extract_claims
CLIENT: {{CLIENT}}

{{SKILL}}

Extract the checkable source-of-wealth claims from the declaration chunks below.
Return ONLY: {"claims":[{"text":"...","category":"employment|property_purchase|property_sale|rental|third_party|other",
"source_chunk_ids":["D1#2"],"entity":"<employer, property address or funding party>","amount":85000,
"currency":"HKD","date":"2018-03","period_end":"","event":"monthly salary","materiality":"high|medium|low"}]}
Use only chunk ids that appear below. Quote or closely paraphrase the claim; do not add facts.
Use null for an amount that is not stated. Dates as YYYY, YYYY-MM or YYYY-MM-DD.

CHUNKS_JSON:
{{CHUNKS_JSON}}
END_CHUNKS
