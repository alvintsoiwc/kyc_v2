"""Render the draft SoW memo (proposal Fig. 1, step 7).

Deterministic rendering from the gated case record: every statement in the
memo maps to a claim, a finding and evidence ids in the evidence log. The memo
supports a human decision; it never recommends approving or rejecting a client.
"""

from __future__ import annotations

from collections import Counter

from .state import THEMES, VERDICTS, RunState

LABEL = {"supported": "Supported", "unresolved": "Unresolved", "potential_red_flag": "Potential red flag"}
ICON = {"supported": "✓", "unresolved": "?", "potential_red_flag": "⚑"}


def _money(amount, currency) -> str:
    return "" if amount is None else f"{currency or 'HKD'} {amount:,.0f}"


def _evidence_line(st: RunState, eid: str) -> str:
    e = st.evidence[eid]
    f = e.fields
    if e.tool == "lookup_company":
        desc = (f"CR {f.get('cr_number')} — {f.get('name_en')} ({f.get('name_zh', '')}), incorporated "
                f"{f.get('incorporated')}, status {f.get('status')}" + (f", dissolved {f['dissolved']}" if f.get("dissolved") else ""))
    elif e.tool == "lookup_property":
        tx = "; ".join(f"{t.get('date')} {t.get('nature')} "
                       + (f"HKD {t['consideration']:,}" if t.get("consideration") else f"HKD {t.get('amount', 0):,}")
                       for t in f.get("transactions", []))
        desc = f"{f.get('property_ref')} — {f.get('address')}; {tx}"
    elif e.tool == "calc_wealth_timeline":
        desc = (f"{f.get('label')}: in HKD {f.get('total_in_hkd', 0):,.0f}, out HKD {f.get('total_out_hkd', 0):,.0f}, "
                f"lowest balance HKD {f.get('lowest_balance_hkd', 0):,.0f}, funding gap HKD {f.get('funding_gap_hkd', 0):,.0f}")
    elif e.tool == "check_consistency":
        desc = "; ".join(f"{c['label']}: {'consistent' if c['consistent'] else 'INCONSISTENT'}"
                         + (f" ({c['relative_difference']:.1%} diff)" if "relative_difference" in c else "")
                         for c in f.get("checks", []))
    elif e.tool == "search_policy":
        desc = f"{f.get('section_id')} — {f.get('title')} (version {f.get('version')})"
    elif e.evidence_type == "memory":
        desc = f"{f.get('statement')} (verified {f.get('verified_on')} by {f.get('confirmed_by')})"
    else:
        desc = e.location
    tag = {"declaration": "client assertion", "calculation": "computed", "policy": "guidance, not evidence",
           "memory": "prior verification"}.get(e.evidence_type, "")
    tags = [tag] if tag else []
    if e.synthetic and e.evidence_type in ("document", "registry"):
        tags.append("SYNTHETIC")
    return f"- [{eid}] {e.source}: {desc}" + (f" _({', '.join(tags)})_" if tags else "")


def render(st: RunState, summary: dict) -> str:
    cfg = st.config
    L: list[str] = []
    L += [f"# Source-of-Wealth Verification Memo (draft): {st.client}", "",
          f"Run `{st.run_id}` · client ref `{st.client_ref or '-'}` · started {st.started_at} · system "
          f"`{cfg.get('system')}` · model `{cfg.get('provider')}/{cfg.get('model')}`"
          + (f" · focus: {', '.join(st.focus)}" if st.focus else ""), "",
          "> **For human compliance review.** This draft lists what the declaration claims, what the evidence "
          "shows and what is missing. A *potential red flag* is a review trigger, not a finding of misconduct. "
          "The agent cannot approve or reject onboarding; the compliance officer decides next steps.",
          "> **SYNTHETIC DATA:** client, documents and registry records are fictional."]
    if cfg.get("provider") == "mock":
        L += ["> **MOCK MODEL:** decisions were produced by the scripted mock policy, not an LLM."]
    if not (cfg.get("variant") or {}).get("gate", True):
        L += ["> **GATE DISABLED** in this system variant: findings were not checked by the citation/completion gate."]
    L.append("")

    counts = Counter(f.verdict for f in st.findings.values() if f.task_id != "out_of_scope")
    L += ["## Summary", "", "| Status | Claims |", "|---|---|"]
    L += [f"| {ICON[v]} {LABEL[v]} | {counts.get(v, 0)} |" for v in VERDICTS]
    L += ["", f"{len(st.claims)} claims extracted from the declaration; {len({c.doc for c in st.chunks})} documents in "
              f"the packet; {len(st.evidence)} evidence items; {st.pii_masked} PII spans masked at intake; "
              f"{len(st.evidence_requests)} documents to request.", ""]

    L += ["## Wealth timeline", "", "| Date | Claim | Event | Amount | Status |", "|---|---|---|---|---|"]
    for t in st.timeline:
        L.append(f"| {t['date']} | {t['claim_id']} | {t['event']} — {t['entity']} | {_money(t['amount'], t['currency'])} "
                 f"| {ICON.get(t['status'], '')} {LABEL.get(t['status'], t['status'])} |")
    L.append("")

    sections = [("1. Income", THEMES["income"]), ("2. Property", THEMES["property"]),
                ("3. Third-party funding and other sources", THEMES["funding"])]
    for heading, cats in sections:
        claims = [c for c in st.claims if c.category in cats and st.findings.get(c.claim_id)
                  and st.findings[c.claim_id].task_id != "out_of_scope"]
        L += [f"## {heading}", ""]
        if not claims:
            L += ["_No claims in this section._", ""]
        for c in claims:
            f = st.findings[c.claim_id]
            srcs = "; ".join(f"{ch.doc}, {ch.location}" for i in c.source_chunk_ids if (ch := st.chunk(i)))
            L += [f"### {c.claim_id} · {c.category} · {ICON[f.verdict]} {LABEL[f.verdict]}", "",
                  f"**Declared:** “{c.text}”  ", f"_Source: {srcs}_  ",
                  f"_Typed: entity `{c.entity or '-'}` · amount `{_money(c.amount, c.currency) or '-'}` · "
                  f"date `{c.date or '-'}`{' – ' + c.period_end if c.period_end else ''} · event `{c.event or '-'}`_", "",
                  f"**Finding:** {f.rationale}", ""]
            if f.numbers:
                L += ["**Computed figures (from the calculator):** " +
                      ", ".join(f"{k} = {v:,.0f}" if isinstance(v, (int, float)) else f"{k} = {v}"
                                for k, v in f.numbers.items()), ""]
            ev = [e for e in f.evidence_ids if e in st.evidence]
            if ev:
                L += ["**Evidence:**", *[_evidence_line(st, e) for e in ev], ""]
            if f.conflicts:
                L += ["**Conflicts:**", *[f"- {x}" for x in f.conflicts], ""]
            if f.missing_evidence:
                L += ["**Missing evidence (request from client):**", *[f"- {x}" for x in f.missing_evidence], ""]
            if f.open_questions:
                L += ["**Open questions:**", *[f"- {q}" for q in f.open_questions], ""]
            if f.gate_notes:
                L += ["**Gate notes:**", *[f"- {g}" for g in f.gate_notes], ""]
            if f.review:
                L += [f"**Independent reviewer:** {'agrees the cited spans support this finding' if f.review.get('supports') else 'DISAGREES'}"
                      + (f" — {f.review['comment']}" if f.review.get("comment") else ""), ""]

    L += ["## 4. Cross-claim consistency", ""]
    if st.cross_claim_conflicts:
        for x in st.cross_claim_conflicts:
            L.append(f"- {', '.join(x['claims'])} ({x['entity']}): {'; '.join(x['differences'])}")
    else:
        L.append("_No conflicting statements detected within the declaration._")
    L.append("")

    L += ["## 5. Outstanding questions and documents to request", ""]
    grouped: dict[str, list[str]] = {}
    for q in st.review_questions:
        grouped.setdefault(q["question"], [])
        if q["claim_id"] not in grouped[q["question"]]:
            grouped[q["question"]].append(q["claim_id"])
    for r in st.evidence_requests:
        key = f"Request: {r['document']}"
        grouped.setdefault(key, [])
        if r["claim_id"] not in grouped[key]:
            grouped[key].append(r["claim_id"])
    for n, (q, refs) in enumerate(grouped.items(), 1):
        L.append(f"{n}. ({', '.join(refs)}) {q}")
    if not grouped:
        L.append("_None._")
    L.append("")

    oos = [c for c in st.claims if st.findings.get(c.claim_id) and st.findings[c.claim_id].task_id == "out_of_scope"]
    if oos:
        L += ["## 6. Out of scope for this request", "", *[f"- {c.claim_id} ({c.category}): {c.text}" for c in oos], ""]

    L += ["## Officer decision (to be completed by a human)", "",
          "- [ ] Evidence sufficient for the assessed risk", "- [ ] Further documents requested (see section 5)",
          "- [ ] Escalate for enhanced review", "", "Officer: ____________ Date: ____________", ""]

    L += ["## Evidence log", "", "| ID | Type | Source | Identifier | Location | Retrieved |", "|---|---|---|---|---|---|"]
    for e in st.evidence.values():
        L.append(f"| {e.evidence_id} | {e.evidence_type} | {e.source} | {e.identifier} | {e.location} | {e.retrieved_at} |")
    c = st.counters
    L += ["", "## Run log", "",
          f"- Model calls: {c.model_calls} · tool calls: {c.tool_calls} (errors: {c.tool_errors}) · format repairs: "
          f"{c.format_repairs} · verification rejections: {c.verify_rejections} · gate downgrades: {c.gate_downgrades}",
          f"- Tokens in/out: {c.tokens_in}/{c.tokens_out}" + (" (estimated)" if cfg.get("provider") == "mock" else "")
          + f" · estimated cost: ${c.cost_usd:.4f} · evidence rounds: {st.evidence_rounds}",
          f"- Model latency p50/p95: {summary.get('model_latency_p50_ms')}/{summary.get('model_latency_p95_ms')} ms · "
          f"tool latency p50/p95: {summary.get('tool_latency_p50_ms')}/{summary.get('tool_latency_p95_ms')} ms · "
          f"wall time: {summary.get('wall_time_s')} s",
          "- Tasks: " + "; ".join(f"{t.task_id} [{t.skill or 'no playbook'}] {t.status} ({t.stop_reason})"
                                  for t in st.tasks), ""]
    return "\n".join(L)
