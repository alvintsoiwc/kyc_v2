"""System A (proposal Table 1): single-prompt LLM, no tools.

Identical information access: System A receives the same declaration, the same
document text and the same mock registry records as plain text, so A–B
differences reflect tool use and code-based calculation rather than extra
information. Same model and settings, same status labels, one format repair.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .intake import load_materials
from .llm import LLMError, call_model, make_llm
from .protocol import ProtocolError, parse
from .state import CATEGORIES, VERDICTS, RunState
from .trace import Tracer
from .workflow import render

BASELINE_SCHEMA = {
    "type": "object", "required": ["findings"],
    "properties": {"findings": {"type": "array", "items": {
        "type": "object", "required": ["claim_text", "verdict"],
        "properties": {"claim_text": {"type": "string"}, "category": {"enum": CATEGORIES},
                       "verdict": {"enum": VERDICTS}, "evidence_ids": {"type": "array", "items": {"type": "string"}},
                       "rationale": {"type": "string"}, "conflicts": {"type": "array", "items": {"type": "string"}},
                       "missing_evidence": {"type": "array", "items": {"type": "string"}},
                       "numbers": {"type": "object"}}}}},
}


def run_direct(settings, client: str, materials: Path, case_dir: Path | None, run_dir: Path) -> dict[str, Any]:
    st = RunState.new(client, str(materials))
    run_dir.mkdir(parents=True, exist_ok=True)
    tracer = Tracer(run_dir / f"systemA-{st.run_id}.jsonl", st.run_id)
    chunks, _, _ = load_materials(materials)
    decl = [{"chunk_id": c.chunk_id, "doc": c.doc, "location": c.location, "text": c.text}
            for c in chunks if c.doc_type == "declaration"]
    packet: list[dict[str, Any]] = []
    evidence: dict[str, dict[str, Any]] = {}
    for c in chunks:
        if c.doc_type == "declaration":
            continue
        eid = f"E{len(packet) + 1}"
        ident = f"{c.doc}#{c.chunk_id.split('#', 1)[1]}"
        packet.append({"evidence_id": eid, "kind": c.doc_type, "location": f"{c.doc}, {c.location}", "text": c.text})
        evidence[eid] = {"identifier": ident, "evidence_type": "document"}
    reg = case_dir / "registry" if case_dir else None
    for name, key in (("companies", "cr_number"), ("land_registry", "property_ref")):
        path = reg / f"{name}.json" if reg else None
        if path and path.exists():
            for r in json.loads(path.read_text(encoding="utf-8")).get("records", []):
                eid = f"E{len(packet) + 1}"
                packet.append({"evidence_id": eid, "kind": f"registry:{name}", "location": f"{name}: {r[key]}",
                               "text": json.dumps(r, ensure_ascii=False)})
                evidence[eid] = {"identifier": r[key], "evidence_type": "registry"}
    content = render((settings.prompts_dir / "baseline.md").read_text(encoding="utf-8"), CLIENT=client,
                     DECLARATION_JSON=json.dumps(decl, ensure_ascii=False),
                     PACKET_JSON=json.dumps(packet, ensure_ascii=False))
    msgs = [{"role": "system", "content": (settings.prompts_dir / "baseline_system.md").read_text(encoding="utf-8")},
            {"role": "user", "content": content}]
    llm = make_llm(settings, private=case_dir is None)
    findings: list[dict[str, Any]] = []
    for _ in range(2):
        try:
            res = call_model(llm, msgs, state=st, tracer=tracer, settings=settings, purpose="system_A",
                             schema=BASELINE_SCHEMA)
        except LLMError:
            break
        try:
            findings = parse(res.text, BASELINE_SCHEMA)["findings"]
            break
        except ProtocolError as exc:
            st.counters.format_repairs += 1
            msgs = msgs + [{"role": "assistant", "content": res.text},
                           {"role": "user", "content": f"FORMAT_ERROR: {exc}. Return only the JSON object."}]
    for f in findings:
        for k, d in (("evidence_ids", []), ("conflicts", []), ("missing_evidence", []), ("numbers", {}),
                     ("category", "other"), ("rationale", "")):
            f.setdefault(k, d)
        f["open_questions"] = []
    return {"system": "A", "findings": findings, "evidence": evidence, "claims": [],
            "counters": vars(st.counters), "summary": tracer.summary()}
