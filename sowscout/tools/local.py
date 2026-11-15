"""Local tools: policy-guidance retrieval, skill references, evidence recall."""

from __future__ import annotations

import re
from typing import Any

from .base import ToolContext, ToolError, envelope, string_arg
from .text import tfidf_rank


def _policy_sections(ctx: ToolContext) -> list[dict[str, str]]:
    if ctx.policy_dir is None or not ctx.policy_dir.exists():
        raise ToolError("unavailable", "no policy corpus configured")
    out = []
    for p in sorted(ctx.policy_dir.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        ver = re.search(r"^version:\s*(.+)$", text, re.M | re.I)
        src = re.search(r"^source:\s*(.+)$", text, re.M | re.I)
        for sec in re.split(r"^## ", text, flags=re.M)[1:]:
            title, _, body = sec.partition("\n")
            out.append({"section_id": f"{p.stem}§{title.split(' ')[0].strip('.')}", "doc": p.name, "title": title.strip(),
                        "version": ver.group(1).strip() if ver else "", "source": src.group(1).strip() if src else "",
                        "text": body.strip()[:900]})
    return out


def search_policy(ctx: ToolContext, query: str, limit: int = 3) -> dict[str, Any]:
    secs = _policy_sections(ctx)
    ranked = tfidf_rank(query, [s["title"] + " " + s["text"] for s in secs])
    recs = [{**secs[i], "score": round(sc, 3)} for i, sc in ranked[:limit] if sc > 0]
    return {"source": "Policy guidance notes", "total": len(recs), "records": recs,
            "note": "Paraphrased guidance notes for this prototype; not legal advice and not the official text."}


SEARCH_POLICY_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {"query": string_arg("Topic, e.g. 'third-party gift source of wealth'"),
                   "limit": {"type": "integer", "minimum": 1, "maximum": 5}},
}
SEARCH_POLICY_OUTPUT = envelope({"type": "object", "required": ["section_id", "title", "text"]})


def read_skill_reference(ctx: ToolContext, skill: str, file: str) -> dict[str, Any]:
    if ctx.skills is None:
        raise ToolError("unavailable", "no skill library")
    text = ctx.skills.read_reference(skill, file)
    return {"source": f"skill:{skill}/{file}", "total": 1, "records": [{"file": file, "text": text[:3000]}]}


READ_REF_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["skill", "file"],
    "properties": {
        "skill": string_arg("Skill name from the skill index"),
        "file": string_arg("Reference file listed by the loaded skill", pattern="^[A-Za-z0-9_./-]+$"),
    },
}


def get_evidence(ctx: ToolContext, evidence_id: str) -> dict[str, Any]:
    ev = ctx.evidence.get(evidence_id)
    if ev is None:
        raise ToolError("permanent", f"unknown evidence id {evidence_id}")
    return {"source": "evidence store", "total": 1,
            "records": [{"evidence_id": ev.evidence_id, "source": ev.source, "identifier": ev.identifier,
                         "location": ev.location, "evidence_type": ev.evidence_type, "fields": ev.fields}]}


GET_EVIDENCE_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["evidence_id"],
    "properties": {"evidence_id": string_arg("Evidence id such as E3", pattern="^E[0-9]+$")},
}
GENERIC_OUTPUT = envelope({"type": "object"})
