"""Optional independent reviewer (proposal Fig. 1, dashed box; stretch goal).

A fresh-context model call with NO tools and NO access to the agent's reasoning
trace: it sees only each finding, its status and the text of the cited spans,
and judges whether the cited spans genuinely support the finding. This is the
semantic check the deterministic completion gate cannot make. It never changes
a status; disagreements become questions for the compliance officer.
"""

from __future__ import annotations

import json
from typing import Any

from .protocol import REVIEW_SCHEMA


def _span(ev) -> dict[str, Any]:
    f = ev.fields
    text = f.get("text") or f.get("statement") or json.dumps(
        {k: v for k, v in f.items() if k not in ("timeline", "rows")}, ensure_ascii=False, default=str)
    return {"evidence_id": ev.evidence_id, "type": ev.evidence_type, "location": ev.location, "text": str(text)[:700]}


def independent_review(wf) -> None:
    st = wf.state
    items = []
    for c in st.claims:
        f = st.findings.get(c.claim_id)
        if not f or f.verdict == "unresolved":
            continue
        items.append({"claim_id": c.claim_id, "claim": c.text, "status": f.verdict, "finding": f.rationale,
                      "conflicts": f.conflicts,
                      "cited_spans": [_span(st.evidence[e]) for e in f.evidence_ids if e in st.evidence]})
    if not items:
        return
    system = (wf.settings.prompts_dir / "reviewer.md").read_text(encoding="utf-8")
    content = "PHASE: review\nFINDINGS_JSON:\n" + json.dumps(items, ensure_ascii=False) + "\nEND_FINDINGS"
    out = wf._model_json(content, REVIEW_SCHEMA, "review", system=system)
    for r in (out or {}).get("reviews", []):
        f = st.findings.get(r["claim_id"])
        if not f:
            continue
        f.review = {"supports": r["supports"], "comment": r.get("comment", "")}
        if not r["supports"]:
            st.review_questions.append({"claim_id": f.claim_id, "source": "independent reviewer",
                                        "question": "Independent reviewer: the cited spans may not support this "
                                                    f"finding. {r.get('comment', '')}".strip()})
    wf.tracer.event("phase", phase="review", reviewed=len(items),
                    disagreements=[r["claim_id"] for r in (out or {}).get("reviews", []) if not r["supports"]])
