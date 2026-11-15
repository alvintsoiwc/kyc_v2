"""SoWScout workflow graph (proposal Fig. 1).

    intake -> extract_claims -> plan -> verify -> sufficiency -> reconcile -> gate -> review -> memo -> done
                                 ^                     |
                                 +---- new documents --+   (bounded: max_evidence_rounds)

  1 intake        parse the packet, assign document types and source locations, mask PII, read client memory
  2 extract       typed SoW claims from the declaration (source type, entity, time, currency, amount, event)
  3 plan          verification planner: one task per claim group, a playbook (skill) per task
  3-4 verify      one bounded ReAct loop per task over the tools; per-task citation checks
  4 sufficiency   "sufficient evidence or stop limit?" — request missing documents or keep the gaps
  5 reconcile     cross-claim checks (conflicting narratives), wealth timeline, questions for the officer
  6 gate          deterministic citation and completion gate over every finding
  - review        optional independent reviewer (fresh context, no tools)
  7 memo          draft SoW memo
  8 (human)       the compliance officer decides; the agent cannot approve or reject onboarding

The state is checkpointed after every node and every task, so a run can be
resumed with `python run.py resume <run_id>`.

Which decisions need the model, and which belong in Python:
  model : claim extraction, verification planning, tool selection/arguments, when to stop / ask,
          the status label and its rationale, (optional) the independent review
  python: chunking, PII masking, source locations, schema/allowlist validation, budgets, retries,
          evidence ids, ALL arithmetic (calculator), the completion gate, cross-claim checks,
          coverage of every claim, memo rendering, memory writes (officer-confirmed only)
"""

from __future__ import annotations

import json
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from . import memo as memo_mod
from .context import ContextBuilder
from .harness import VerificationHarness
from .intake import load_materials
from .llm import LLMError, call_model, make_llm, messages_tokens
from .memory import Memory
from .protocol import EXTRACT_SCHEMA, PLAN_SCHEMA, ProtocolError, parse
from .reviewer import independent_review
from .skills import SkillLibrary
from .state import CATEGORIES, THEMES, VERDICTS, Claim, Finding, RunState, VerificationTask  # noqa: F401
from .tools import ToolContext, ToolGateway, build_specs, catalog_text
from .tools.text import norm_name, parse_amount, parse_currency, parse_date, text_score, words
from .verify import completion_gate

DEFAULT_SKILL = {"employment": "employment-income", "property_purchase": "property-purchase",
                 "property_sale": "property-sale", "rental": "rental-income", "third_party": "third-party-funding",
                 "other": "out-of-scope"}
GENERIC_QUESTION = "Which documents and registry records support or contradict this claim?"
NEXT = {"intake": "extract_claims", "extract_claims": "plan", "plan": "verify", "verify": "sufficiency",
        "sufficiency": "reconcile", "reconcile": "gate", "gate": "review", "review": "memo", "memo": "done"}

EvidenceFn = Callable[[list[dict[str, Any]]], "list[Path] | None"]


def render(template: str, **values: str) -> str:
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", v)
    return template


class Workflow:
    def __init__(self, settings, state: RunState, *, case_dir: Path | None = None,
                 ask_fn: Callable[[str, list[str]], str | None] | None = None, echo: bool = True,
                 ctrl=None, faults: str | None = None, evidence_fn: EvidenceFn | None = None):
        self.settings, self.state = settings, state
        self.ctrl = ctrl
        self.L = settings.limits
        self.variant = settings.variant
        self.run_dir = settings.runs_dir / state.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.memory = Memory(settings.db_path)
        from .trace import Tracer
        self.tracer = Tracer(self.run_dir / "trace.jsonl", state.run_id, echo)
        self.skills = SkillLibrary(settings.skills_dir)
        self.specs = build_specs(calculator=self.variant["calculator"], database=settings.use_database)
        registry = state.config.get("registry_dir") or (
            str(case_dir / "registry") if case_dir and (case_dir / "registry").exists() else "")
        state.config.update(provider=settings.provider, model=settings.default_model(), system=settings.system,
                            variant=self.variant, reviewer=settings.reviewer, tool_transport=settings.tool_transport,
                            registry_dir=registry, limits=vars(self.L))
        self.tool_ctx = ToolContext(registry_dir=Path(registry) if registry else None, policy_dir=settings.policy_dir,
                                    chunks=state.chunks, evidence=state.evidence, skills=self.skills,
                                    timeout_s=self.L.tool_timeout_s)
        mcp_args = (["--registry", registry] if registry else []) + ["--policy", str(settings.policy_dir)]
        self.gateway = ToolGateway(self.specs, self.tool_ctx, state, self.L, self.tracer,
                                   transport=settings.tool_transport, mcp_server_args=mcp_args, faults=faults)
        from . import user_settings
        if settings.use_database:
            self.tool_ctx.database = user_settings.open_database(settings.runs_dir)
            self.tool_ctx.database_notes = user_settings.load(settings.runs_dir)["database_notes"]
        private = bool(state.config.get("private", case_dir is None) or settings.use_database)
        state.config.update(private=private, allow_cloud=settings.allow_cloud, use_database=settings.use_database)
        self.llm = make_llm(settings, private=private)
        if hasattr(self.llm, "preflight"):
            self.llm.preflight()
        system = render((settings.prompts_dir / "system.md").read_text(encoding="utf-8"),
                        TOOL_CATALOG=catalog_text(self.specs),
                        SKILL_INDEX=self.skills.index_text() if self.variant["skills"] else "(no playbooks in this system variant)",
                        VERDICTS=", ".join(VERDICTS))
        self.ctx = ContextBuilder(system, self.L)
        self.ask_fn = ask_fn
        self.evidence_fn = evidence_fn
        self.deadline = self._now() + self.L.run_deadline_s

    def _now(self) -> float:
        return self.ctrl.now() if self.ctrl else time.monotonic()

    # ------------------------------------------------------------------ edges
    def run(self) -> RunState:
        from .control import StopRequested
        st = self.state
        st.stop_reason = ""
        self.tracer.event("phase", phase=st.phase, run_id=st.run_id, provider=self.settings.provider,
                          system=self.settings.system, transport=self.settings.tool_transport)
        try:
            while st.phase != "done":
                if self.ctrl:
                    self.ctrl.gate("node", phase=st.phase)
                nxt = getattr(self, st.phase)()
                st.phase = nxt or NEXT[st.phase]
                self.checkpoint()
                if st.phase != "done":
                    self.tracer.event("phase", phase=st.phase)
        except StopRequested:
            st.stop_reason = "stopped by reviewer"
            self.checkpoint()
            self.tracer.event("stop", reason=st.stop_reason, phase=st.phase)
        except KeyboardInterrupt:
            self.checkpoint()
            print(f"\n[sowscout] interrupted; resume with: python run.py resume {st.run_id}")
            raise
        finally:
            self.gateway.close()
            self.memory.close()
            if self.tool_ctx.database:
                self.tool_ctx.database.close()
        return st

    def checkpoint(self) -> None:
        js = self.state.to_json()
        self.memory.save_checkpoint(self.state.run_id, self.state.phase, js)
        (self.run_dir / "state.json").write_text(js)

    def _model_json(self, content: str, schema: dict[str, Any], purpose: str,
                    system: str | None = None) -> dict[str, Any] | None:
        """One-shot model call with a single bounded format repair."""
        msgs = self.ctx.one_shot(content) if system is None else [{"role": "system", "content": system},
                                                                  {"role": "user", "content": content}]
        for _ in range(1 + self.L.max_format_repairs):
            try:
                res = call_model(self.llm, msgs, state=self.state, tracer=self.tracer, settings=self.settings,
                                 purpose=purpose, schema=schema)
            except LLMError as exc:
                self.tracer.event("warning", phase=purpose, message=f"model call failed: {exc}")
                return None
            try:
                return parse(res.text, schema)
            except ProtocolError as exc:
                if hasattr(self.llm, "note_failure"):
                    self.llm.note_failure(purpose)
                self.state.counters.format_repairs += 1
                self.tracer.event("format_repair", phase=purpose, error=str(exc))
                msgs = msgs + [{"role": "assistant", "content": res.text},
                               {"role": "user", "content": f"FORMAT_ERROR: {exc}. Return only the JSON object."}]
        return None

    # ------------------------------------------------------------------ 1. intake
    def intake(self) -> None:
        st = self.state
        packet = self.run_dir / "packet"            # immutable snapshot of what was reviewed (audit)
        if not packet.exists():
            shutil.copytree(Path(st.materials_dir), packet)
        chunks, skipped, masked = load_materials(packet)
        st.chunks[:] = chunks
        st.pii_masked = masked
        st.memory_facts = self.memory.client_facts(st.client)                      # semantic memory read
        st.config["name_variants"] = self.memory.name_variants(st.client)
        st.config["past_cases"] = self.memory.past_cases(st.client)                # episodic memory read
        if not any(c.doc_type == "declaration" for c in chunks):
            self.tracer.event("warning", phase="intake", message="no declaration found; claims are extracted "
                                                                 "from all documents")
        self.tracer.event("phase", phase="intake", documents=len({c.doc for c in chunks}), chunks=len(chunks),
                          doc_types=dict(Counter(c.doc_type for c in {c.doc: c for c in chunks}.values())),
                          skipped=skipped, pii_masked=masked, memory_facts=len(st.memory_facts))

    # ------------------------------------------------------------------ 2. extract
    def extract_claims(self) -> None:
        st = self.state
        template = (self.settings.prompts_dir / "extract.md").read_text(encoding="utf-8")
        skill = self.skills.activation_text("claim-extraction")
        source = [c for c in st.chunks if c.doc_type == "declaration"] or st.chunks
        raw: list[dict[str, Any]] = []
        for batch in self._chunk_batches(source, template, skill):
            ids = {c.chunk_id for c in batch}
            payload = [{"chunk_id": c.chunk_id, "doc": c.doc, "location": c.location, "text": c.text} for c in batch]
            content = render(template, CLIENT=st.client, SKILL=skill, CHUNKS_JSON=json.dumps(payload, ensure_ascii=False))
            out = self._model_json(content, EXTRACT_SCHEMA, "extract_claims")
            for c in (out or {}).get("claims", []):
                valid = [i for i in c["source_chunk_ids"] if i in ids]
                if not valid:      # traceability rule: no source location, no claim
                    self.tracer.event("warning", phase="extract_claims", message="dropped claim without valid source",
                                      claim=c["text"][:120])
                    continue
                raw.append({**c, "source_chunk_ids": valid})
        merged: list[dict[str, Any]] = []
        for c in raw:               # near-duplicate merge
            w = set(words(c["text"]))
            dup = next((m for m in merged if len(w & set(words(m["text"]))) / max(1, len(w | set(words(m["text"])))) >= 0.85), None)
            if dup:
                dup["source_chunk_ids"] = sorted(set(dup["source_chunk_ids"]) | set(c["source_chunk_ids"]))
            else:
                merged.append(dict(c))
        st.claims = [self._normalise(i, c) for i, c in enumerate(merged, 1)]
        self.tracer.event("phase", phase="extract_claims", claims=len(st.claims),
                          by_category=dict(Counter(c.category for c in st.claims)))
        if self.ctrl and self.ctrl.flags["review_claims"]:
            self._review_claims()

    @staticmethod
    def _normalise(i: int, c: dict[str, Any]) -> Claim:
        """Python normalises the typed fields the model extracted (currency, dates, amounts)."""
        amount = c.get("amount")
        if isinstance(amount, str):
            amount = parse_amount(amount)
        return Claim(claim_id=f"C{i}", text=c["text"], category=c["category"], source_chunk_ids=c["source_chunk_ids"],
                     entity=(c.get("entity") or "").strip(), amount=amount,
                     currency=(parse_currency(c.get("currency", "")) or c.get("currency", "") or
                               ("HKD" if amount is not None else "")).upper(),
                     date=parse_date(c.get("date", "")) or c.get("date", ""),
                     period_end=parse_date(c.get("period_end", "")) or c.get("period_end", ""),
                     event=c.get("event", ""), materiality=c.get("materiality", "high"))

    def _review_claims(self) -> None:
        st = self.state
        resp = self.ctrl.request("review_claims", {"claims": [
            {"claim_id": c.claim_id, "text": c.text, "category": c.category, "materiality": c.materiality,
             "entity": c.entity, "amount": c.amount, "currency": c.currency, "date": c.date,
             "sources": [f"{ch.doc}, {ch.location}" for i in c.source_chunk_ids if (ch := st.chunk(i))]}
            for c in st.claims], "categories": CATEGORIES}) or {}
        edits = {e.get("claim_id"): e for e in resp.get("claims", []) if isinstance(e, dict)}
        kept, dropped = [], []
        for c in st.claims:
            e = edits.get(c.claim_id)
            if e is None:
                kept.append(c)
                continue
            if not e.get("keep", True):
                dropped.append(c.claim_id)
                continue
            if isinstance(e.get("text"), str) and len(e["text"].strip()) >= 8:
                c.text = e["text"].strip()
            if e.get("category") in CATEGORIES:
                c.category = e["category"]
            if e.get("materiality") in ("high", "medium", "low"):
                c.materiality = e["materiality"]
            if isinstance(e.get("entity"), str):
                c.entity = e["entity"].strip()
            if e.get("amount") not in (None, ""):
                c.amount = parse_amount(e["amount"])
            kept.append(c)
        st.claims = kept
        self.tracer.event("control", event="claims_reviewed", kept=len(kept), dropped=dropped)

    def _chunk_batches(self, chunks, template: str, skill: str):
        """Fit chunks into the input budget (Lec 4 'Context budget'): one or more calls per document."""
        overhead = messages_tokens(self.ctx.one_shot(render(template, CLIENT="", SKILL=skill, CHUNKS_JSON="")))
        room = max(500, self.ctx.input_budget - overhead - 200)
        by_doc: dict[str, list] = {}
        for c in chunks:
            by_doc.setdefault(c.doc, []).append(c)
        for group in by_doc.values():
            batch, size = [], 0
            for c in group:
                t = len(c.text) // 4 + 40
                if batch and size + t > room:
                    yield batch
                    batch, size = [], 0
                batch.append(c)
                size += t
            if batch:
                yield batch

    def _in_focus(self, claim: Claim) -> bool:
        f = self.state.focus
        if not f:
            return True
        cats = set()
        for x in f:
            cats |= set(THEMES.get(x, [x]))
        return claim.category in cats

    # ------------------------------------------------------------------ 3. plan
    def plan(self, claim_ids: list[str] | None = None, round_no: int = 1) -> None:
        st = self.state
        pool = [c for c in st.claims if claim_ids is None or c.claim_id in claim_ids]
        in_scope = [c for c in pool if self._in_focus(c)]
        for c in pool:
            if not self._in_focus(c):
                st.findings[c.claim_id] = Finding(c.claim_id, "unresolved", [], "Out of scope for this request "
                                                  f"(focus: {', '.join(st.focus)}).", task_id="out_of_scope",
                                                  open_questions=["Out of scope for this request."], verified=True)
        out: dict[str, Any] | None
        if not self.variant["skills"]:          # System B: no planner, one generic task per claim
            out = {"tasks": [{"claim_ids": [c.claim_id], "question": GENERIC_QUESTION, "skill": "", "priority": 2}
                             for c in in_scope]}
        elif in_scope:
            claims_json = [{"claim_id": c.claim_id, "text": c.text, "category": c.category, "entity": c.entity,
                            "amount": c.amount, "date": c.date, "materiality": c.materiality} for c in in_scope]
            memory = [{"category": m["category"], "statement": m["statement"], "verified_on": m["verified_on"]}
                      for m in st.memory_facts]
            content = render((self.settings.prompts_dir / "plan.md").read_text(encoding="utf-8"),
                             CLIENT=st.client, FOCUS=", ".join(st.focus) or "all sources of wealth",
                             SKILLS=", ".join(n for n in self.skills.names() if n != "claim-extraction"),
                             MAX_TASKS=str(self.L.max_tasks), CLAIMS_JSON=json.dumps(claims_json, ensure_ascii=False),
                             CLIENT_MEMORY=json.dumps(memory, ensure_ascii=False), ROUND=str(round_no))
            out = self._model_json(content, PLAN_SCHEMA, "plan")
        else:
            out = {"tasks": []}
        valid_ids = {c.claim_id for c in in_scope}
        covered: set[str] = set()
        tasks: list[VerificationTask] = []
        for t in (out or {}).get("tasks", []):
            ids = [i for i in t["claim_ids"] if i in valid_ids and i not in covered]
            if not ids:
                continue
            skill = t["skill"] if self.skills.get(t["skill"]) else DEFAULT_SKILL.get(st.claim(ids[0]).category,
                                                                                    "out-of-scope")
            covered |= set(ids)
            tasks.append(VerificationTask("", ids, t["question"], skill, t["priority"], round=round_no))
        missing = [c for c in in_scope if c.claim_id not in covered]
        if missing:   # coverage check: every claim gets a task
            self.tracer.event("plan", message="planner missed claims; added fallback tasks",
                              claims=[c.claim_id for c in missing])
            tasks += [VerificationTask("", [c.claim_id], f"Verify against documents and registries: {c.text[:160]}",
                                       DEFAULT_SKILL.get(c.category, "out-of-scope"), 2, round=round_no)
                      for c in missing]
        tasks.sort(key=lambda t: t.priority)
        start = len(st.tasks)
        for i, t in enumerate(tasks, start + 1):
            t.task_id = f"T{i}"
        budget = max(0, self.L.max_tasks - start)
        st.tasks += tasks[:budget]
        for t in tasks[budget:]:
            for cid in t.claim_ids:
                st.findings[cid] = Finding(cid, "unresolved", [], "Not verified: run task budget reached.",
                                           open_questions=[t.question], task_id=t.task_id, verified=True)
        self.tracer.event("plan", round=round_no, tasks=[{"task_id": t.task_id, "claims": t.claim_ids,
                                                          "skill": t.skill, "priority": t.priority} for t in tasks])
        if self.ctrl and self.ctrl.flags["review_plan"]:
            self._review_plan()

    def _review_plan(self) -> None:
        st = self.state
        skills = [n for n in self.skills.names() if n != "claim-extraction"]
        pending = [t for t in st.tasks if t.status == "pending"]
        resp = self.ctrl.request("review_plan", {
            "tasks": [{"task_id": t.task_id, "claim_ids": t.claim_ids, "question": t.question, "skill": t.skill,
                       "priority": t.priority,
                       "claims": [{"claim_id": c, "text": st.claim(c).text, "category": st.claim(c).category}
                                  for c in t.claim_ids if st.claim(c)]} for t in pending],
            "skills": skills}) or {}
        by_id = {t.task_id: t for t in pending}
        done = [t for t in st.tasks if t.status != "pending"]
        new: list[VerificationTask] = []
        removed: list[str] = []
        for e in resp.get("tasks", [t.__dict__ for t in pending]):
            t = by_id.pop(e.get("task_id"), None) if isinstance(e, dict) else None
            if t is None:
                continue
            if not e.get("keep", True):
                removed.append(t.task_id)
                for cid in t.claim_ids:
                    st.findings[cid] = Finding(cid, "unresolved", [], "Not verified: removed from the plan by the "
                                               "reviewer.", open_questions=["Removed from the plan by the reviewer."],
                                               task_id="removed", verified=True)
                continue
            if isinstance(e.get("question"), str) and len(e["question"].strip()) >= 8:
                t.question = e["question"].strip()
            if e.get("skill") in skills:
                t.skill = e["skill"]
            if e.get("priority") in (1, 2, 3, "1", "2", "3"):
                t.priority = int(e["priority"])
            new.append(t)
        new += list(by_id.values())
        for i, t in enumerate(new, len(done) + 1):
            t.task_id = f"T{i}"
        st.tasks = done + new
        self.tracer.event("control", event="plan_reviewed", removed=removed,
                          tasks=[{"task_id": t.task_id, "claims": t.claim_ids, "skill": t.skill} for t in new])

    # ------------------------------------------------------------------ 3-4. verify
    def verify(self) -> None:
        st = self.state
        h = VerificationHarness(llm=self.llm, gateway=self.gateway, ctx=self.ctx, skills=self.skills, state=st,
                                memory=self.memory, tracer=self.tracer, settings=self.settings, ask_fn=self.ask_fn,
                                run_deadline=self.deadline, ctrl=self.ctrl)
        for task in st.tasks:
            if task.status != "pending":
                continue
            if self.ctrl:
                self.ctrl.gate("task", task_id=task.task_id)
            if self._now() > self.deadline:
                task.status, task.stop_reason = "unresolved", "run time budget exhausted"
                for cid in task.claim_ids:
                    st.findings[cid] = Finding(cid, "unresolved", [], "Not verified: run time budget exhausted.",
                                               open_questions=[task.question], task_id=task.task_id, verified=True)
                continue
            claim = st.claim(task.claim_ids[0])
            self.tracer.event("phase", phase="verify", task_id=task.task_id, skill=task.skill,
                              claim=claim.text[:100] if claim else "")
            for f in h.run(task):
                st.findings[f.claim_id] = f
            self.checkpoint()

    # ------------------------------------------------------------------ 4. sufficient evidence or stop limit?
    def sufficiency(self) -> str | None:
        st = self.state
        gaps = [{"claim_id": f.claim_id, "claim": st.claim(f.claim_id).text if st.claim(f.claim_id) else "",
                 "missing_evidence": f.missing_evidence}
                for f in st.findings.values() if f.verdict == "unresolved" and f.missing_evidence]
        if not gaps:
            return None
        if st.evidence_rounds >= self.L.max_evidence_rounds:
            self.tracer.event("phase", phase="sufficiency", decision="stop limit reached; keep gaps", gaps=len(gaps))
            return None
        files = self._request_evidence(gaps)
        if not files:
            self.tracer.event("phase", phase="sufficiency", decision="no new documents; keep gaps", gaps=len(gaps))
            return None
        packet = self.run_dir / "packet"
        added = []
        for p in files:
            dest = packet / p.name
            if p.is_file() and not dest.exists():
                shutil.copy2(p, dest)
                added.append(dest)
        if not added:
            return None
        start = len({c.doc for c in st.chunks})
        new_chunks, _, masked = load_materials(packet, only=[p.name for p in added], start_index=start + 1)
        st.chunks.extend(new_chunks)
        st.pii_masked += masked
        st.evidence_rounds += 1
        claim_ids = [g["claim_id"] for g in gaps]
        for cid in claim_ids:
            st.findings.pop(cid, None)
        self.tracer.event("phase", phase="sufficiency", decision="new documents received; re-planning",
                          documents=[p.name for p in added], claims=claim_ids, round=st.evidence_rounds)
        self.plan(claim_ids, round_no=st.evidence_rounds)
        return "verify"

    def _request_evidence(self, gaps: list[dict[str, Any]]) -> list[Path]:
        if self.ctrl and self.ctrl.flags.get("request_evidence"):
            resp = self.ctrl.request("request_evidence", {"gaps": gaps}) or {}
            return [Path(p) for p in resp.get("files", []) if isinstance(p, str)]
        if self.evidence_fn:
            return list(self.evidence_fn(gaps) or [])
        return []

    # ------------------------------------------------------------------ 5. reconcile
    def reconcile(self) -> None:
        st = self.state
        st.cross_claim_conflicts.clear()
        st.review_questions.clear()
        st.evidence_requests.clear()
        # (a) conflicting narratives: the same event declared twice with different amounts or dates
        for i, a in enumerate(st.claims):
            for b in st.claims[i + 1:]:
                if a.category != b.category or not a.entity or not b.entity:
                    continue
                if not (norm_name(a.entity) == norm_name(b.entity) or text_score(a.entity, b.entity) >= 0.75):
                    continue
                diffs = []
                if a.amount and b.amount and abs(a.amount - b.amount) / max(a.amount, b.amount) > 0.05:
                    diffs.append(f"amount {a.currency} {a.amount:,.0f} vs {b.currency} {b.amount:,.0f}")
                if a.date and b.date and a.date[:4] != b.date[:4]:
                    diffs.append(f"date {a.date} vs {b.date}")
                if a.category in ("property_purchase", "property_sale") and diffs:
                    st.cross_claim_conflicts.append({"claims": [a.claim_id, b.claim_id], "entity": a.entity,
                                                     "differences": diffs})
                    q = (f"The declaration describes the same {a.category.replace('_', ' ')} ({a.entity}) twice with "
                         f"different details ({'; '.join(diffs)}). Ask the client which is correct.")
                    st.review_questions.append({"claim_id": f"{a.claim_id}, {b.claim_id}", "question": q,
                                                "source": "cross-claim check"})
        # (b) wealth timeline (deterministic, from typed claims and their final status)
        st.timeline = sorted(
            [{"date": c.date or "?", "claim_id": c.claim_id, "category": c.category, "event": c.event or c.category,
              "entity": c.entity, "amount": c.amount, "currency": c.currency,
              "status": st.findings[c.claim_id].verdict if c.claim_id in st.findings else "unresolved"}
             for c in st.claims], key=lambda x: x["date"])
        # (c) evidence requests and questions for the officer
        for f in st.findings.values():
            if f.task_id == "out_of_scope":
                continue
            for m in f.missing_evidence:
                st.evidence_requests.append({"claim_id": f.claim_id, "document": m})
            for q in f.open_questions:
                st.review_questions.append({"claim_id": f.claim_id, "question": q, "source": "finding"})
        self.tracer.event("phase", phase="reconcile", cross_claim_conflicts=len(st.cross_claim_conflicts),
                          evidence_requests=len(st.evidence_requests), review_questions=len(st.review_questions))

    # ------------------------------------------------------------------ 6. citation and completion gate
    def gate(self) -> None:
        st = self.state
        if not self.variant["gate"]:
            for f in st.findings.values():
                f.verified = False
            self.tracer.event("phase", phase="gate", enabled=False)
            return
        report = completion_gate(st, calculator=self.variant["calculator"])
        if any(not r["ok"] for r in report):          # downgrades change the timeline and questions
            self.reconcile()
        self.tracer.event("phase", phase="gate", enabled=True, checked=len(report),
                          downgraded=[r["claim_id"] for r in report if not r["ok"]])

    # ------------------------------------------------------------------ optional independent reviewer
    def review(self) -> None:
        if not self.settings.reviewer:
            return
        independent_review(self)

    # ------------------------------------------------------------------ 7. memo
    def memo(self) -> None:
        st = self.state
        summary = self.tracer.summary()
        md = memo_mod.render(st, summary)
        (self.run_dir / "memo.md").write_text(md)
        (self.run_dir / "record.json").write_text(st.to_json())
        (self.run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        self.memory.record_case(st.run_id, st.client, {
            "statuses": dict(Counter(f.verdict for f in st.findings.values())),
            "open_questions": [q["question"] for q in st.review_questions][:5]})
        self.tracer.event("phase", phase="memo", path=str(self.run_dir / "memo.md"))


def load_for_resume(settings, run_id: str) -> RunState:
    mem = Memory(settings.db_path)
    ck = mem.load_checkpoint(run_id)
    mem.close()
    if ck is None:
        raise SystemExit(f"no checkpoint for run {run_id}")
    st = RunState.from_json(ck[1])
    settings.allow_cloud = st.config.get("allow_cloud", settings.allow_cloud)
    settings.use_database = st.config.get("use_database", settings.use_database)
    settings.provider = st.config.get("provider", settings.provider)
    settings.model = st.config.get("model", settings.model)
    settings.system = st.config.get("system", settings.system)
    settings.reviewer = st.config.get("reviewer", settings.reviewer)
    settings.tool_transport = st.config.get("tool_transport", settings.tool_transport)
    for k, v in (st.config.get("limits") or {}).items():
        if hasattr(settings.limits, k):
            setattr(settings.limits, k, v)
    return st


def resume(settings, run_id: str, ask_fn=None, echo=True) -> RunState:
    st = load_for_resume(settings, run_id)
    if st.phase == "done":
        print(f"[sowscout] run {run_id} already finished")
        return st
    wf = Workflow(settings, st, ask_fn=ask_fn, echo=echo)
    return wf.run()


def remember_findings(settings, run_id: str, confirmed_by: str, claim_ids: list[str] | None = None) -> list[str]:
    """Step 8 (human): after the officer reviews the memo, write the supported, gate-verified findings
    they confirm into client memory. The agent never calls this on its own."""
    if not confirmed_by.strip():
        raise ValueError("an officer identifier is required to write client memory")
    st = load_for_resume(settings, run_id)
    if st.phase != "done":
        raise ValueError(f"run {run_id} is not finished (phase {st.phase})")
    mem = Memory(settings.db_path)
    written = []
    for c in st.claims:
        f = st.findings.get(c.claim_id)
        if not f or f.verdict != "supported" or not f.verified or (claim_ids and c.claim_id not in claim_ids):
            continue
        ev = [f"{st.evidence[e].source}: {st.evidence[e].identifier}" for e in f.evidence_ids if e in st.evidence
              and st.evidence[e].evidence_type in ("document", "registry", "calculation")]
        written.append(mem.add_client_fact(st.client, {
            "fact_id": f"{run_id}-{c.claim_id}", "category": c.category, "statement": c.text, "entity": c.entity,
            "amount": c.amount, "currency": c.currency, "date": c.date, "evidence": ev},
            source_run=run_id, confirmed_by=confirmed_by))
    mem.close()
    return written
