PHASE: plan
CLIENT: {{CLIENT}}
FOCUS: {{FOCUS}}
EVIDENCE_ROUND: {{ROUND}}
AVAILABLE_PLAYBOOKS: {{SKILLS}}
MAX_TASKS: {{MAX_TASKS}}
CLIENT_MEMORY (facts an officer verified in earlier reviews; may be out of date): {{CLIENT_MEMORY}}

Plan the verification. Create tasks for the claims below, most material first (priority 1 = highest).
A task may group claims that need the same evidence (for example a purchase and the gift that funded it).
Every claim must belong to exactly one task. Pick the playbook that fits each task and write a specific
evidence question (which document, registry record or calculation would settle the claim).
Return ONLY: {"tasks":[{"claim_ids":["C1"],"question":"...","skill":"employment-income","priority":1}]}

CLAIMS_JSON:
{{CLAIMS_JSON}}
END_CLAIMS
