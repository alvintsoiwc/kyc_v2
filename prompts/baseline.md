PHASE: baseline_direct
CLIENT: {{CLIENT}}

System A (single prompt, no tools). The client's declaration, every supporting document and the mock registry
records are given below as plain text. Extract each checkable source-of-wealth claim from the declaration and
assess it. Cite evidence by the ids in brackets.
Return ONLY: {"findings":[{"claim_text":"...","category":"employment|property_purchase|property_sale|rental|third_party|other",
"verdict":"supported|unresolved|potential_red_flag","evidence_ids":["E3"],"rationale":"...","conflicts":["..."],
"missing_evidence":["..."],"numbers":{"funding_gap_hkd":0}}]}

DECLARATION_JSON:
{{DECLARATION_JSON}}
END_DECLARATION

PACKET_JSON:
{{PACKET_JSON}}
END_PACKET
