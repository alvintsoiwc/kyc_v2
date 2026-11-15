"""The case record: typed working state for one source-of-wealth (SoW) verification run.

Working state (this run) is kept separate from reusable memory (previously
verified client facts — see memory.py). Every claim keeps its source locations
in the client declaration, and every evidence item keeps its type, identifier,
source location and retrieval time (proposal §3.1: traceability).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

# Claim source types. The MVP scope is employment income and property purchase / sale
# (rental if feasible); third-party funding is in the benchmark because it is a common
# gap. Anything else (business, inheritance, crypto...) is "other" and stays unresolved.
CATEGORIES = ["employment", "property_purchase", "property_sale", "rental", "third_party", "other"]

# Proposal §2 / §4.1: three finding labels, fixed before annotation.
VERDICTS = [
    "supported",            # a cited span matches the claim and numeric checks agree within ±5%
    "unresolved",           # required evidence is missing or insufficient
    "potential_red_flag",   # cited evidence conflicts with the claim or the numbers fail to reconcile
]

# Evidence types. A declaration is what the client asserts; it is never support for itself.
EVIDENCE_TYPES = ["declaration", "document", "registry", "calculation", "policy", "memory", "internal"]
SUPPORTING_TYPES = {"document", "registry", "memory"}

THEMES = {
    "income": ["employment", "rental"],
    "property": ["property_purchase", "property_sale"],
    "funding": ["third_party", "other"],
}

TOLERANCE = 0.05     # ±5% numeric tolerance (proposal §4.1 status rules)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class SourceChunk:
    chunk_id: str          # e.g. "D2#3"
    doc: str               # file name
    location: str          # human-readable: "section 'Employment', lines 12-18"
    text: str              # PII-masked text
    doc_date: str = ""
    doc_type: str = ""     # declaration | payslip | bank_statement | tax_return | property | mortgage | letter | other


@dataclass
class Claim:
    claim_id: str
    text: str
    category: str
    source_chunk_ids: list[str]
    entity: str = ""            # employer / property address / funding party
    amount: float | None = None
    currency: str = ""
    date: str = ""              # YYYY or YYYY-MM or YYYY-MM-DD (event date or start of period)
    period_end: str = ""
    event: str = ""             # e.g. "monthly salary", "purchase price", "sale proceeds"
    materiality: str = "high"   # high | medium | low


@dataclass
class VerificationTask:
    task_id: str
    claim_ids: list[str]
    question: str
    skill: str
    priority: int = 2
    status: str = "pending"     # pending | done | unresolved
    stop_reason: str = ""
    round: int = 1              # evidence round (2+ after the officer supplied documents)


@dataclass
class Evidence:
    evidence_id: str
    tool: str
    source: str                 # e.g. "Client document", "Mock Companies Registry", "Calculator"
    identifier: str             # "payslip_2025-03.md#2", CR number, memorial number, ...
    location: str               # document + location, or registry key
    retrieved_at: str
    fields: dict[str, Any]
    evidence_type: str          # one of EVIDENCE_TYPES
    synthetic: bool = True
    query: dict[str, Any] = field(default_factory=dict)


@dataclass
class Finding:
    claim_id: str
    verdict: str
    evidence_ids: list[str]
    rationale: str
    conflicts: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)   # documents to request
    open_questions: list[str] = field(default_factory=list)
    numbers: dict[str, Any] = field(default_factory=dict)       # numeric results the finding relies on
    task_id: str = ""
    verified: bool = False      # passed the citation / completion gate
    gate_notes: list[str] = field(default_factory=list)
    review: dict[str, Any] = field(default_factory=dict)        # independent reviewer verdict (optional)


@dataclass
class Counters:
    model_calls: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    format_repairs: int = 0
    verify_rejections: int = 0
    gate_downgrades: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass
class RunState:
    run_id: str
    client: str
    materials_dir: str
    client_ref: str = ""        # internal reference, never the HKID
    focus: list[str] = field(default_factory=list)
    phase: str = "intake"
    started_at: str = field(default_factory=now_iso)
    chunks: list[SourceChunk] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    tasks: list[VerificationTask] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    findings: dict[str, Finding] = field(default_factory=dict)
    memory_facts: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    cross_claim_conflicts: list[dict[str, Any]] = field(default_factory=list)
    evidence_requests: list[dict[str, Any]] = field(default_factory=list)
    review_questions: list[dict[str, Any]] = field(default_factory=list)
    human_answers: list[dict[str, Any]] = field(default_factory=list)
    pii_masked: int = 0
    evidence_rounds: int = 1
    counters: Counters = field(default_factory=Counters)
    stop_reason: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def new(client: str, materials_dir: str, client_ref: str = "", focus: list[str] | None = None) -> "RunState":
        rid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        return RunState(run_id=rid, client=client, materials_dir=materials_dir, client_ref=client_ref,
                        focus=focus or [])

    # ---- lookups -------------------------------------------------------
    def claim(self, claim_id: str) -> Claim | None:
        return next((c for c in self.claims if c.claim_id == claim_id), None)

    def chunk(self, chunk_id: str) -> SourceChunk | None:
        return next((c for c in self.chunks if c.chunk_id == chunk_id), None)

    def next_evidence_id(self) -> str:
        return f"E{len(self.evidence) + 1}"

    # ---- (de)serialisation for checkpoints -----------------------------
    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @staticmethod
    def from_json(text: str) -> "RunState":
        d = json.loads(text)
        st = RunState(run_id=d["run_id"], client=d["client"], materials_dir=d["materials_dir"])
        for k, v in d.items():
            setattr(st, k, v)
        st.chunks = [SourceChunk(**c) for c in d.get("chunks", [])]
        st.claims = [Claim(**c) for c in d.get("claims", [])]
        st.tasks = [VerificationTask(**t) for t in d.get("tasks", [])]
        st.evidence = {k: Evidence(**v) for k, v in d.get("evidence", {}).items()}
        st.findings = {k: Finding(**v) for k, v in d.get("findings", {}).items()}
        st.counters = Counters(**d.get("counters", {}))
        return st
