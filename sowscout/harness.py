"""Bounded verification loop for one task (Lec 4 "Bounded agent loop" / "Harness loop").

for step in range(MAX_STEPS):
    deadline / cost cap?  -> handoff("budget")
    decide(build_context(state))
    tool_calls            -> validate, execute in parallel, observe, update state
    ask_user              -> officer's answer (or NO_HUMAN_AVAILABLE) becomes an observation
    finish                -> citation / completion checks; one bounded revision; else downgrade
    malformed output      -> one bounded format repair; else stop
return handoff("step budget")

Every new observation can change the next model decision (ReAct).
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from .context import ContextBuilder, observation_message
from .llm import LLMError, call_model
from .protocol import ProtocolError, parse_decision
from .state import Finding, RunState, SourceChunk, VerificationTask
from .tools.text import norm_name, text_score
from .verify import verify_assessments

AskFn = Callable[[str, list[str]], "str | None"]

INSTRUCTION = ("Decide the next action for this task. Return exactly one JSON object: "
               '{"action":"tool_calls",...} | {"action":"finish",...} | {"action":"ask_user",...}.')


def relevant_memory(facts: list[dict[str, Any]], claim) -> list[dict[str, Any]]:
    """Previously verified facts about the same entity (employer / property)."""
    out = []
    for f in facts:
        same_entity = claim.entity and f.get("entity") and (
            norm_name(f["entity"]) == norm_name(claim.entity) or text_score(f["entity"], claim.entity) >= 0.75)
        if same_entity:
            out.append(f)
    return out


class VerificationHarness:
    def __init__(self, *, llm, gateway, ctx: ContextBuilder, skills, state: RunState, memory, tracer,
                 settings, ask_fn: AskFn | None, run_deadline: float, ctrl=None):
        self.llm, self.gw, self.ctx, self.skills = llm, gateway, ctx, skills
        self.state, self.memory, self.tracer, self.settings = state, memory, tracer, settings
        self.L = settings.limits
        self.variant = settings.variant
        self.ask_fn = ask_fn
        self.run_deadline = run_deadline
        self.ctrl = ctrl

    def _now(self) -> float:
        return self.ctrl.now() if self.ctrl else time.monotonic()

    def _human_available(self) -> bool:
        if self.ctrl:
            return self.ctrl.flags["ask_reviewer"] and self.ask_fn is not None
        return bool(self.ask_fn and self.settings.interactive)

    # ------------------------------------------------------------------ brief
    def _task_brief(self, task: VerificationTask, decl_ev: dict[str, str], mem_ev: dict[str, str]) -> str:
        st = self.state
        claims = [st.claim(c) for c in task.claim_ids]
        docs = {}
        for ch in st.chunks:
            if ch.doc_type != "declaration":
                docs.setdefault(ch.doc, {"doc": ch.doc, "doc_type": ch.doc_type, "doc_date": ch.doc_date})
        payload = {
            "task_id": task.task_id, "question": task.question, "skill": task.skill if self.variant["skills"] else "",
            "client": st.client, "client_ref": st.client_ref,
            "claims": [{"claim_id": c.claim_id, "text": c.text, "category": c.category, "entity": c.entity,
                        "amount": c.amount, "currency": c.currency, "date": c.date, "period_end": c.period_end,
                        "event": c.event, "source_chunk_ids": c.source_chunk_ids} for c in claims if c],
            "declaration_evidence_ids": list(decl_ev.values()),
            "memory_evidence_ids": list(mem_ev.values()),
            "name_variants": st.config.get("name_variants", []),
            "packet_documents": list(docs.values()),
            "evidence_round": task.round,
        }
        lines = ["PHASE: verify", "TASK_JSON:", json.dumps(payload, ensure_ascii=False), "END_TASK", ""]
        if self.variant["skills"]:
            lines += [self.skills.activation_text(task.skill), ""]
        lines.append("DECLARATION_EXCERPTS (what the client asserts; cite to show the claim, NEVER as support):")
        for chunk_id, eid in decl_ev.items():
            ch = st.chunk(chunk_id)
            if ch:
                lines.append(f"[{eid}] {ch.doc}, {ch.location}: {ch.text[:600]}")
        if mem_ev:
            lines += ["", "CLIENT_MEMORY (facts verified and confirmed by an officer in an earlier review):"]
            for fid, eid in mem_ev.items():
                f = next((m for m in st.memory_facts if m["fact_id"] == fid), {})
                lines.append(f"[{eid}] verified {f.get('verified_on', '?')}: {f.get('statement', '')}")
        return "\n".join(lines)

    def _tail(self, step: int, used: int, t_end: float, asked: bool, last: bool) -> str:
        ws = {"task_step": step + 1, "max_steps": self.L.max_steps_per_task, "tool_calls_used": used,
              "tool_calls_remaining": max(0, self.L.max_tool_calls_per_task - used),
              "max_calls_per_decision": self.L.max_calls_per_batch,
              "seconds_left": max(0, round(t_end - self._now())), "already_asked_user": asked}
        extra = " This is the LAST step: you must return action 'finish' now." if last else ""
        return f"WORKING_STATE: {json.dumps(ws)}\nINSTRUCTION: {INSTRUCTION}{extra}"

    def prepare(self, task: VerificationTask) -> tuple[str, dict[str, str], dict[str, str]]:
        st = self.state
        chunks: list[SourceChunk] = [ch for cid in task.claim_ids for ch_id in st.claim(cid).source_chunk_ids
                                     if (ch := st.chunk(ch_id))]
        decl_ev = self.gw.register_declaration(chunks)
        facts = {f["fact_id"]: f for cid in task.claim_ids for f in relevant_memory(st.memory_facts, st.claim(cid))}
        mem_ids = self.gw.register_memory(list(facts.values()))
        mem_ev = dict(zip(facts.keys(), mem_ids))
        return self._task_brief(task, decl_ev, mem_ev), decl_ev, mem_ev

    # ------------------------------------------------------------------ run
    def run(self, task: VerificationTask) -> list[Finding]:
        st, L = self.state, self.L
        brief, decl_ev, mem_ev = self.prepare(task)
        observed: set[str] = set(decl_ev.values()) | set(mem_ev.values())
        history: list[dict[str, Any]] = []
        t_end = min(self._now() + L.task_deadline_s, self.run_deadline)
        used = repairs = revisions = asks = 0
        allowed = set(self.gw.specs)

        for step in range(L.max_steps_per_task):
            if self.ctrl:
                if self.ctrl.should_skip(task.task_id):
                    return self._handoff(task, "skipped by reviewer", decl_ev)
                self.ctrl.gate("decision", task_id=task.task_id, step=step + 1, tool_calls_used=used)
                if self.ctrl.should_skip(task.task_id):
                    return self._handoff(task, "skipped by reviewer", decl_ev)
                for note in self.ctrl.take_notes(task.task_id):
                    history.append({"role": "user", "content": f"REVIEWER_NOTE: {note}"})
                    self.tracer.event("control", event="note_delivered", task_id=task.task_id, text=note[:200])
            if self._now() > t_end:
                return self._handoff(task, "time budget exhausted", decl_ev)
            if L.max_cost_usd and st.counters.cost_usd >= L.max_cost_usd:
                return self._handoff(task, f"cost cap reached (${st.counters.cost_usd:.4f})", decl_ev)
            last = step == L.max_steps_per_task - 1
            msgs, info = self.ctx.build(brief, history, self._tail(step, used, t_end, asks > 0, last))
            try:
                res = call_model(self.llm, msgs, state=st, tracer=self.tracer, settings=self.settings,
                                 purpose="verify", task_id=task.task_id, step=step)
            except LLMError as exc:
                return self._handoff(task, f"model call failed: {exc}", decl_ev)
            self.tracer.event("context", task_id=task.task_id, step=step, **info)
            try:
                d = parse_decision(res.text, allowed, L.max_calls_per_batch)
            except ProtocolError as exc:
                if hasattr(self.llm, "note_failure"):
                    self.llm.note_failure("verify", task.task_id)
                if repairs < L.max_format_repairs:
                    repairs += 1
                    st.counters.format_repairs += 1
                    self.tracer.event("format_repair", task_id=task.task_id, step=step, error=str(exc))
                    history += [{"role": "assistant", "content": res.text},
                                {"role": "user", "content": f"FORMAT_ERROR: {exc}. Follow the OUTPUT CONTRACT."}]
                    continue
                return self._handoff(task, f"malformed model output after repair: {exc}", decl_ev)
            history.append({"role": "assistant", "content": res.text})
            self.tracer.event("decision", task_id=task.task_id, step=step, action=d["action"],
                              summary=d.get("thought", "")[:160])

            if d["action"] == "tool_calls":
                remaining = L.max_tool_calls_per_task - used
                if remaining <= 0:
                    history.append({"role": "user", "content": "TOOL_BUDGET_EXHAUSTED: no more tool calls; "
                                                               "finish with the evidence you have."})
                    continue
                calls = d["calls"][:remaining]
                if self.ctrl and self.ctrl.flags["approve_tools"]:
                    calls, note = self._approve(task, step, calls, d.get("thought", ""), allowed)
                    if not calls:
                        history.append({"role": "user", "content": "REVIEWER_REJECTED_TOOL_CALLS: "
                                        + (note or "the reviewer did not approve these calls")
                                        + ". Choose a different action."})
                        continue
                obs = self.gw.run_batch(calls, task_id=task.task_id, step=step)
                used += len(calls)
                for o in obs:
                    observed.update(o.evidence_ids)
                history.append(observation_message([o.for_model(L.max_records_per_observation) for o in obs]))

            elif d["action"] == "ask_user":
                asks += 1
                history.append({"role": "user", "content": self._ask(task, d, asks)})

            else:  # finish
                if not self.variant["gate"]:
                    return self._accept(task, d["assessments"], [], decl_ev)
                problems = verify_assessments(d["assessments"], st, task, observed, self.variant["calculator"])
                self.tracer.event("verify", task_id=task.task_id, step=step, ok=not problems, problems=problems)
                if problems and hasattr(self.llm, "note_failure"):
                    self.llm.note_failure("verify", task.task_id)
                if problems and revisions < L.max_verify_revisions and not last:
                    revisions += 1
                    st.counters.verify_rejections += 1
                    history.append({"role": "user", "content": "VERIFICATION_FAILED:\n- " + "\n- ".join(problems) +
                                                               "\nRevise the assessment (you may call tools first)."})
                    continue
                return self._accept(task, d["assessments"], problems, decl_ev)
        return self._handoff(task, "step budget exhausted", decl_ev)

    # ------------------------------------------------------------------ human in the loop
    def _approve(self, task, step, calls, thought, allowed):
        resp = self.ctrl.request("approve_tools", {"task_id": task.task_id, "step": step + 1,
                                                   "thought": thought, "calls": calls}) or {}
        if resp.get("decision") != "approve":
            self.tracer.event("control", event="tools_rejected", task_id=task.task_id, note=resp.get("note", ""))
            return [], resp.get("note", "")
        edited = []
        for c in resp.get("calls") or calls:
            if isinstance(c, dict) and c.get("tool") in allowed and isinstance(c.get("arguments"), dict):
                edited.append({"tool": c["tool"], "arguments": c["arguments"]})
        edited = edited[: self.L.max_calls_per_batch]
        if edited != calls:
            self.tracer.event("control", event="tools_edited", task_id=task.task_id, calls=edited)
        return edited, ""

    def _ask(self, task: VerificationTask, d: dict[str, Any], asks: int) -> str:
        q = d["question"]
        if asks > 1:
            return "ASK_LIMIT: only one question per task; proceed and record the doubt as an open question."
        answer = self.ask_fn(q, d.get("options", [])) if self._human_available() else None
        if isinstance(answer, str) and not answer.strip():
            answer = None
        rec = {"task_id": task.task_id, "question": q, "answer": answer, "alias_candidate": d.get("alias_candidate")}
        self.tracer.event("ask_user", **rec)
        self.state.human_answers.append(rec)
        if answer is None:
            return ("NO_HUMAN_AVAILABLE: no officer is available. Proceed without confirmation and list the doubt "
                    "in open_questions.")
        alias = d.get("alias_candidate")
        claim = self.state.claim(task.claim_ids[0])
        if alias and claim and answer.strip().lower() in {"y", "yes", "same", "true"}:
            # controlled memory write: only an officer-confirmed name variant is stored
            self.memory.add_name_variant(self.state.client, claim.entity, alias, confirmed_by="officer")
            self.state.config.setdefault("name_variants", []).append({"entity": claim.entity, "variant": alias})
        return f"HUMAN_ANSWER: {answer}"

    # ------------------------------------------------------------------ outcomes
    def _accept(self, task, assessments, problems, decl_ev) -> list[Finding]:
        out = []
        for a in assessments:
            if a["claim_id"] not in task.claim_ids:
                continue
            f = Finding(claim_id=a["claim_id"], verdict=a["verdict"], evidence_ids=a.get("evidence_ids", []),
                        rationale=a["rationale"], conflicts=a.get("conflicts", []),
                        missing_evidence=a.get("missing_evidence", []), open_questions=a.get("open_questions", []),
                        numbers=a.get("numbers", {}) or {}, task_id=task.task_id,
                        verified=not problems and self.variant["gate"])
            mine = [p for p in problems if p.startswith(a["claim_id"] + ":")]
            if mine:   # still failing after bounded revision: do not publish the status
                f.rationale = f"[runtime downgrade from '{f.verdict}': {'; '.join(mine)}] {f.rationale}"
                f.verdict = "unresolved"
                f.gate_notes = mine
                f.evidence_ids = [e for e in f.evidence_ids if e in self.state.evidence]
                f.numbers = {}
                if not (f.missing_evidence or f.open_questions):
                    f.open_questions = ["Verify this claim manually."]
            out.append(f)
        covered = {f.claim_id for f in out}
        out += [self._stopped(c, task, "no assessment returned", decl_ev) for c in task.claim_ids if c not in covered]
        task.status = "done"
        task.stop_reason = "finished" if not problems else "finished with runtime downgrade"
        return out

    def _stopped(self, claim_id, task, reason, decl_ev) -> Finding:
        ch_ids = self.state.claim(claim_id).source_chunk_ids
        return Finding(claim_id=claim_id, verdict="unresolved", evidence_ids=[decl_ev[c] for c in ch_ids if c in decl_ev],
                       rationale=f"Verification stopped: {reason}.", open_questions=[task.question],
                       task_id=task.task_id, verified=True)

    def _handoff(self, task, reason, decl_ev) -> list[Finding]:
        self.tracer.event("stop", task_id=task.task_id, reason=reason)
        task.status, task.stop_reason = "unresolved", reason
        return [self._stopped(c, task, reason, decl_ev) for c in task.claim_ids]
