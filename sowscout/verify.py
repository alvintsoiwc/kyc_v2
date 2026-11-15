"""Citation and completion gate (proposal Fig. 1, step 6) — deterministic, no model.

The model proposes a finding; Python checks it before it enters the memo:

  citations   every cited evidence id exists, was retrieved in this task, and has a source location
  status      the label is one of the three permitted labels and its preconditions hold:
                supported           >=1 document / registry / memory evidence; no stated conflicts;
                                    a claim with an amount needs a cited calculation that agrees (±5%)
                potential_red_flag  the conflict is stated and backed by non-declaration evidence
                unresolved          the missing evidence or open question is stated
  numbers     every figure in `numbers` appears in the cited evidence (no free-form arithmetic)
  safe status no approve / reject / misconduct language: the agent cannot decide onboarding

Inside a task, failures are returned to the model once for bounded revision
(Lec 4 "bounded revision"); in the final gate they downgrade the finding to
`unresolved` with the reason recorded. The gate only checks that ids, locations,
numbers and labels exist and are valid; whether a span genuinely supports a
finding is the optional independent reviewer's job (reviewer.py).
"""

from __future__ import annotations

import re
from typing import Any

from .state import SUPPORTING_TYPES, VERDICTS, RunState, VerificationTask

UNSAFE = re.compile(
    r"\b(approve[sd]?|reject(?:s|ed)?|decline[sd]?|accept(?:s|ed)?)\b[^.]{0,40}\b(client|onboarding|account|application|relationship)\b"
    r"|\b(recommend|should)\b[^.]{0,30}\b(approv|reject|declin|onboard)"
    r"|\bmoney laundering (?:is|was|has been) (?:confirmed|established|proven)|\b(?:is|was) fraudulent\b|\bcommitted fraud\b",
    re.I)
NUM_TOL = 0.005


def _numbers_in(obj: Any) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        for m in re.findall(r"-?\d[\d,]*(?:\.\d+)?", obj):
            try:
                out.append(float(m.replace(",", "")))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            out += _numbers_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _numbers_in(v)
    return out


def _calc_status(fields: dict[str, Any]) -> bool | None:
    if "all_consistent" in fields:
        return bool(fields["all_consistent"])
    if "reconciles" in fields:
        return bool(fields["reconciles"])
    return None


def check_finding(a: dict[str, Any], state: RunState, *, calculator: bool = True,
                  observed: set[str] | None = None) -> list[str]:
    """Problems with one assessment / finding (dict with verdict, evidence_ids, rationale, ...)."""
    cid = a["claim_id"]
    claim = state.claim(cid)
    p: list[str] = []
    v = a["verdict"]
    if v not in VERDICTS:
        return [f"{cid}: verdict '{v}' is not a permitted status label {VERDICTS}"]
    cited = list(a.get("evidence_ids", []))
    unknown = [e for e in cited if e not in state.evidence]
    if unknown:
        p.append(f"{cid}: cites unknown evidence ids {unknown}; cite only ids shown in observations")
    if observed is not None:
        unseen = [e for e in cited if e in state.evidence and e not in observed]
        if unseen:
            p.append(f"{cid}: cites {unseen} which were not retrieved in this task")
    ev = [state.evidence[e] for e in cited if e in state.evidence]
    no_loc = [e.evidence_id for e in ev if not e.location]
    if no_loc:
        p.append(f"{cid}: evidence {no_loc} has no source location")
    supporting = [e for e in ev if e.evidence_type in SUPPORTING_TYPES]
    calcs = [e for e in ev if e.evidence_type == "calculation"]
    calc_ok = [_calc_status(e.fields) for e in calcs]
    if v == "supported":
        if not supporting:
            p.append(f"{cid}: 'supported' needs at least one document, registry or memory evidence id "
                     "(the declaration is not support for itself)")
        if a.get("conflicts"):
            p.append(f"{cid}: 'supported' cannot list conflicts; use potential_red_flag or remove them")
        if calculator and claim and claim.amount is not None and not any(e.evidence_type == "memory" for e in ev):
            if not calcs:
                p.append(f"{cid}: the claim states an amount; cite a check_consistency or calc_wealth_timeline "
                         "result showing it agrees with the documents")
            elif False in calc_ok:
                p.append(f"{cid}: a cited calculation does not reconcile / is inconsistent, so the claim "
                         "cannot be 'supported'")
    if v == "potential_red_flag":
        if not a.get("conflicts"):
            p.append(f"{cid}: 'potential_red_flag' must state the conflict in 'conflicts'")
        if not [e for e in ev if e.evidence_type in SUPPORTING_TYPES | {"calculation"}]:
            p.append(f"{cid}: 'potential_red_flag' must cite the document, registry or calculation that conflicts")
    if v == "unresolved" and not (a.get("missing_evidence") or a.get("open_questions")):
        p.append(f"{cid}: 'unresolved' must list the missing evidence or an open question")
    nums = a.get("numbers") or {}
    if nums:
        have = _numbers_in([e.fields for e in ev]) + ([claim.amount] if claim and claim.amount is not None else [])
        for k, x in nums.items():
            if isinstance(x, bool) or not isinstance(x, (int, float)):
                continue
            if not any(abs(x - h) <= NUM_TOL * max(abs(h), 1.0) for h in have):
                p.append(f"{cid}: number {k}={x} does not appear in the cited evidence; compute it with a tool "
                         "and cite the result")
    text = " ".join([a.get("rationale", "")] + list(a.get("conflicts", [])))
    if UNSAFE.search(text):
        p.append(f"{cid}: findings must not approve, reject or allege misconduct; describe the evidence only "
                 "(the compliance officer decides)")
    return p


def verify_assessments(assessments: list[dict[str, Any]], state: RunState, task: VerificationTask,
                       observed_ids: set[str], calculator: bool = True) -> list[str]:
    problems: list[str] = []
    seen = set()
    for a in assessments:
        cid = a["claim_id"]
        seen.add(cid)
        if cid not in task.claim_ids:
            problems.append(f"{cid}: not a claim of this task (expected {task.claim_ids})")
            continue
        problems += check_finding(a, state, calculator=calculator, observed=observed_ids)
    missing = [c for c in task.claim_ids if c not in seen]
    if missing:
        problems.append(f"missing assessments for {missing}")
    return problems


def completion_gate(state: RunState, calculator: bool = True) -> list[dict[str, Any]]:
    """Final deterministic gate over every finding. Failing findings are downgraded to `unresolved`."""
    report = []
    for f in state.findings.values():
        if f.task_id in ("out_of_scope", "removed"):
            continue
        problems = check_finding(vars(f), state, calculator=calculator)
        if problems:
            state.counters.gate_downgrades += 1
            old = f.verdict
            f.gate_notes = problems
            if old != "unresolved":
                f.rationale = f"[completion gate downgrade from '{old}': {'; '.join(problems)}] {f.rationale}"
            f.verdict = "unresolved"
            f.evidence_ids = [e for e in f.evidence_ids if e in state.evidence]
            f.numbers = {}
            if not (f.missing_evidence or f.open_questions):
                f.open_questions = ["Verify this claim manually: the automated finding did not pass the gate."]
            f.verified = False
        else:
            f.verified = True
        report.append({"claim_id": f.claim_id, "ok": not problems, "problems": problems})
    return report
