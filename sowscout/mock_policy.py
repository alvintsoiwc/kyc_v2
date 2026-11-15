"""MOCK model: a deterministic, rule-based stand-in for the LLM (provider=mock).

Purpose: run the full agent loop offline (tests, CI, demo without API keys).
It only reads the assembled messages — the same context a real model sees —
and emits the same JSON protocol. Its "reasoning" is a set of keyword and
field rules written alongside the synthetic cases, so results produced with it
say nothing about model quality. Label any mock-based result as such.

It never does arithmetic itself when the calculator tools are offered: it sends
the numbers to check_consistency / calc_wealth_timeline and reads the results.
(In the C-no-calc ablation it falls back to the same comparisons "in its head",
like a model without tools would, and cites no calculation.)

Fault injection for reliability tests: SOWSCOUT_MOCK_FAULTS="malformed:1,ungrounded:1"
  malformed  – the next verification decision is invalid JSON (exercises format repair)
  ungrounded – the next finish cites a non-existent evidence id (exercises the gate)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .tools import calc as calc_tools
from .tools.text import norm_name, parse_amount, parse_date, text_score

_FAULTS: dict[str, int] = {}
_FAULTS_LOADED_FROM: str | None = None


def _take_fault(kind: str) -> bool:
    global _FAULTS_LOADED_FROM
    spec = os.environ.get("SOWSCOUT_MOCK_FAULTS", "")
    if spec != _FAULTS_LOADED_FROM:
        _FAULTS.clear()
        for part in filter(None, spec.split(",")):
            k, _, n = part.partition(":")
            _FAULTS[k.strip()] = int(n or 1)
        _FAULTS_LOADED_FROM = spec
    if _FAULTS.get(kind, 0) > 0:
        _FAULTS[kind] -= 1
        return True
    return False


# ----------------------------------------------------------------- text helpers
def _block(text: str, start: str, end: str) -> str:
    i = text.find(start)
    j = text.find(end, i)
    return "" if i == -1 or j == -1 else text[i + len(start): j].strip()


def _field(text: str, name: str) -> str:
    m = re.search(rf"^{name}:\s*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def _sentences(text: str) -> list[str]:
    lines = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or ln.startswith("|") or re.match(
                r"^(document type|date|client|hkid|mobile|tel|phone|email)\b", ln, re.I):
            continue
        lines.append(re.sub(r"^[-*•]\s+|^\d+\.\s+|\*\*", "", ln))
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", " ".join(lines))
    return [s.strip() for s in parts if len(s.strip()) >= 30]


CATEGORY_RULES = [
    ("rental", re.compile(r"\brent(?:ed)? out\b|\brental income\b", re.I)),
    ("property_sale", re.compile(r"\bsold\b", re.I)),
    ("property_purchase", re.compile(r"\b(?:purchased|bought)\b", re.I)),
    ("third_party", re.compile(r"\bgave me\b|\bgift(?:ed)?\b|\bloan from\b", re.I)),
    ("other", re.compile(r"\bconsult\w*|\bbusiness\b|\binherit\w*|\bcrypto\w*|\bdividend|\bown company\b", re.I)),
    ("employment", re.compile(r"\bemployed\b|\bwork(?:ed|ing)? (?:at|for)\b|\bsalary\b|\bbonus\b|\bearning\b", re.I)),
]
_MONEY = re.compile(r"(?:HKD|HK\$|USD|US\$|RMB)\s?[\d,]+(?:\.\d+)?(?:\s*(?:million|m)\b)?", re.I)
_DATE_TXT = re.compile(r"\b(?:(?:January|February|March|April|May|June|July|August|September|October|November|"
                       r"December)\s+)?(?:19|20)\d\d\b")
_COMPANY = re.compile(r"(?:by|at|for|from|company,?|through)\s+((?:[A-Z][\w&'.-]*\s+)+(?:Company\s+)?(?:Limited|Ltd\.?))")
_ADDRESS = re.compile(r"((?:Flat|Unit|House)\s+[\w-]+,.*?)(?=\s+(?:for|in|and|using|with|was|were)\s|\.|$)")
_PARTY = re.compile(r"\b[Mm]y\s+(parents|father|mother|brother|sister|uncle|aunt|grandparents)\b")


def _typed(sentence: str, cat: str) -> dict[str, Any]:
    money = _MONEY.findall(sentence)
    amount = parse_amount(money[0]) if money else None
    currency = "HKD" if money and re.match(r"HK", money[0], re.I) else ("USD" if money else "")
    dates = _DATE_TXT.findall(sentence)
    date = parse_date(dates[0]) if dates else ""
    end = parse_date(dates[1]) if len(dates) > 1 and re.search(r"\bto\b|\buntil\b", sentence) else ""
    if cat in ("employment", "other"):
        m = _COMPANY.search(sentence)
        entity = m.group(1).strip() if m else ""
    elif cat == "third_party":
        m = _PARTY.search(sentence)
        entity = m.group(1) if m else ""
    else:
        m = _ADDRESS.search(sentence)
        entity = m.group(1).strip(" ,") if m else ""
    event = {"property_purchase": "purchase price", "property_sale": "sale price", "rental": "monthly rent",
             "third_party": "gift", "other": "other income"}.get(cat, "")
    if cat == "employment":
        event = "annual bonus" if re.search(r"bonus", sentence, re.I) else (
            "monthly salary" if re.search(r"per month|monthly", sentence, re.I) else "employment")
    return {"entity": entity, "amount": amount, "currency": currency, "date": date, "period_end": end, "event": event}


def _claims_from_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for ch in chunks:
        for s in _sentences(ch["text"]):
            cat = next((c for c, rx in CATEGORY_RULES if rx.search(s)), "")
            if not cat:
                continue
            t = _typed(s, cat)
            if not t["entity"] and cat != "other":
                continue           # not checkable: no employer / address / funding party
            out.append({"text": s, "category": cat, "source_chunk_ids": [ch["chunk_id"]], **t,
                        "materiality": "medium" if cat == "other" else "high"})
    return out[:25]


# ----------------------------------------------------------------- phases
def respond(messages: list[dict[str, str]]) -> str:
    first_user = messages[1]["content"] if len(messages) > 1 else ""
    phase = _field(first_user, "PHASE")
    if phase == "extract_claims":
        chunks = json.loads(_block(first_user, "CHUNKS_JSON:", "END_CHUNKS") or "[]")
        return json.dumps({"claims": _claims_from_chunks(chunks)})
    if phase == "plan":
        return _plan(first_user)
    if phase == "verify":
        return _verify(messages)
    if phase == "review":
        return _review(first_user)
    if phase == "baseline_direct":
        return _baseline(first_user)
    return json.dumps({"error": f"mock policy has no rule for phase {phase!r}"})


SKILL_FOR = {"employment": "employment-income", "property_purchase": "property-purchase",
             "property_sale": "property-sale", "rental": "rental-income", "third_party": "third-party-funding",
             "other": "out-of-scope"}
QUESTION_FOR = {
    "employment": "Did the employer exist during the claimed period, and do payslips / letters / tax notices match the claimed pay?",
    "property_purchase": "Does the Land Registry match the purchase, and do documented savings, mortgage and other declared sources reconcile with the price?",
    "property_sale": "Does the Land Registry show this sale at the claimed price and date, and were the proceeds received?",
    "rental": "Is the client the registered owner, and do the tenancy and bank credits match the claimed rent?",
    "third_party": "Is the third-party gift evidenced by a signed letter and a matching transfer?",
    "other": "This source is outside the automated scope: what documents should the officer request?",
}
PRIORITY = {"employment": 1, "property_purchase": 1, "property_sale": 1, "rental": 2, "third_party": 2, "other": 3}


def _plan(text: str) -> str:
    claims = json.loads(_block(text, "CLAIMS_JSON:", "END_CLAIMS") or "[]")
    return json.dumps({"tasks": [{"claim_ids": [c["claim_id"]], "question": QUESTION_FOR.get(c["category"], QUESTION_FOR["other"]),
                                  "skill": SKILL_FOR.get(c["category"], "out-of-scope"),
                                  "priority": PRIORITY.get(c["category"], 2)} for c in claims]})


# ----------------------------------------------------------------- verification loop
class _View:
    """What the mock can see of the task: brief + observations + officer replies."""

    def __init__(self, messages: list[dict[str, str]]):
        brief = messages[1]["content"]
        self.calculator = "calc_wealth_timeline(" in messages[0]["content"]
        self.task = json.loads(_block(brief, "TASK_JSON:", "END_TASK") or "{}")
        self.memory = re.findall(r"^\[(E\d+)\] verified ([\d-]+): (.+)$", brief.split("CLIENT_MEMORY", 1)[-1], re.M) \
            if "CLIENT_MEMORY" in brief else []
        self.obs: list[dict[str, Any]] = []
        self.asked = False
        self.human: str | None = None
        for m in messages[2:]:
            if m["role"] == "assistant" and '"ask_user"' in m["content"]:
                self.asked = True
            if m["role"] == "user":
                for blk in re.findall(r"<application_observation>[^\n]*\n(.*?)\n</application_observation>",
                                      m["content"], re.S):
                    try:
                        self.obs.extend(json.loads(blk))
                    except json.JSONDecodeError:
                        pass
                if "HUMAN_ANSWER:" in m["content"]:
                    self.human = m["content"].split("HUMAN_ANSWER:", 1)[1].split("\n", 1)[0].strip()
                elif "NO_HUMAN_AVAILABLE" in m["content"]:
                    self.human = ""
        self.last = messages[-1]["content"]
        self.client = self.task.get("client", "")
        self.claim = (self.task.get("claims") or [{}])[0]
        self.cid = self.claim.get("claim_id", "C?")
        self.decl = self.task.get("declaration_evidence_ids", [])

    # observation access ------------------------------------------------
    def done(self, tool: str, args: dict[str, Any]) -> bool:
        return any(o["tool"] == tool and o.get("arguments") == args for o in self.obs)

    def records(self, tool: str) -> list[dict[str, Any]]:
        out, seen = [], set()
        for o in self.obs:
            if o["tool"] == tool and o.get("ok"):
                for r in o.get("records", []):
                    if r.get("evidence_id") not in seen:
                        seen.add(r.get("evidence_id"))
                        out.append(r)
        return out

    def docs(self, doc_type: str) -> list[dict[str, Any]]:
        out, seen = [], set()
        for t in ("search_documents", "parse_document"):
            for r in self.records(t):
                if r.get("doc_type") == doc_type and r["evidence_id"] not in seen:
                    seen.add(r["evidence_id"])
                    out.append(r)
        return out

    def failed(self, tool: str) -> bool:
        return any(o["tool"] == tool and not o.get("ok") for o in self.obs)

    def calls(self, wanted: list[tuple[str, dict[str, Any]]], thought: str) -> dict[str, Any] | None:
        todo = [{"tool": t, "arguments": a} for t, a in wanted if not self.done(t, a)][:3]
        return {"action": "tool_calls", "thought": thought, "calls": todo} if todo else None

    def check(self, checks: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """(decision to run the checks, result record). Without the calculator the mock compares in its head."""
        if not checks:
            return None, {"checks": [], "all_consistent": True, "inconsistent": []}
        if not self.calculator:
            return None, calc_tools.check_consistency(None, checks)["records"][0]
        d = self.calls([("check_consistency", {"checks": checks})], "compare claimed and documented values")
        if d:
            return d, None
        rec = next((r for o in self.obs if o["tool"] == "check_consistency" and o.get("arguments") == {"checks": checks}
                    and o.get("ok") for r in o.get("records", [])), None)
        return None, rec

    def timeline(self, items: list[dict[str, Any]], label: str):
        if not self.calculator:
            return None, calc_tools.calc_wealth_timeline(None, items, label=label)["records"][0]
        args = {"items": items, "label": label}
        d = self.calls([("calc_wealth_timeline", args)], "reconcile the funding with the calculator")
        if d:
            return d, None
        rec = next((r for o in self.obs if o["tool"] == "calc_wealth_timeline" and o.get("arguments") == args
                    and o.get("ok") for r in o.get("records", [])), None)
        return None, rec

    def finish(self, verdict: str, ev: list[str], rationale: str, conflicts=None, missing=None, questions=None,
               numbers=None, thought="") -> dict[str, Any]:
        a = {"claim_id": self.cid, "verdict": verdict, "evidence_ids": list(dict.fromkeys(e for e in ev if e)),
             "rationale": rationale, "conflicts": conflicts or [], "missing_evidence": missing or [],
             "open_questions": questions or []}
        if numbers:
            a["numbers"] = numbers
        return {"action": "finish", "thought": thought or "evidence gathered; assessing", "assessments": [a]}


def _same(a: str, b: str) -> bool:
    return bool(a and b) and (norm_name(a) == norm_name(b) or text_score(a, b) >= 0.75 or text_score(b, a) >= 0.75)


def _get(fields: dict[str, Any], *keys: str) -> str:
    for k in keys:
        if fields.get(k):
            return str(fields[k])
    return ""


def _conflict_text(r: dict[str, Any]) -> str:
    if r["kind"] == "amount":
        return (f"{r['label']}: claimed HKD {r['claimed_hkd']:,.0f} vs documented HKD {r['documented_hkd']:,.0f} "
                f"({r['relative_difference']:.1%} difference, tolerance {r['tolerance']:.0%})")
    return f"{r['label']}: claimed {r.get('claimed_norm', r['claimed'])} vs documented {r.get('documented_norm', r['documented'])}"


def _calc_ids(v: _View) -> list[str]:
    return [r["evidence_id"] for t in ("check_consistency", "calc_wealth_timeline") for r in v.records(t)]


def _verify(messages: list[dict[str, str]]) -> str:
    v = _View(messages)
    if not v.obs and not v.asked and "FORMAT_ERROR" not in v.last and _take_fault("malformed"):
        return 'Sure! Let me check the registry first: {"action": "tool_calls", "calls": [{"tool": "lookup_company"'
    mem = _memory_match(v)
    if mem:
        d = mem
    else:
        handler = {"employment": _employment, "property_purchase": _purchase, "property_sale": _sale,
                   "rental": _rental, "third_party": _third_party}.get(v.claim.get("category"), _other)
        d = handler(v)
    if d["action"] == "finish" and "VERIFICATION_FAILED" not in v.last and _take_fault("ungrounded"):
        d["assessments"][0]["evidence_ids"].append("E999")
    return json.dumps(d)


def _memory_match(v: _View) -> dict[str, Any] | None:
    """Returning client: a fact verified earlier that matches entity, amount (±5%) and year can be relied on."""
    amt, date = v.claim.get("amount"), v.claim.get("date", "")
    for eid, verified_on, statement in v.memory:
        m = _MONEY.search(statement)
        mamt = parse_amount(m.group(0)) if m else None
        years = re.findall(r"\b(?:19|20)\d\d\b", statement)
        if amt and mamt and abs(amt - mamt) <= 0.05 * mamt and date[:4] in years:
            return v.finish("supported", v.decl + [eid],
                            f"This matches a fact verified by a compliance officer on {verified_on} [{eid}]: "
                            f"{statement} The earlier verification can be relied on if still current.",
                            questions=["Confirm that the earlier verification remains up to date (no material change)."])
    return None


# ----------------------------------------------------------------- employment
def _employment(v: _View) -> dict[str, Any]:
    c, ent = v.claim, v.claim.get("entity", "")
    monthly = c.get("event") == "monthly salary" and c.get("amount")
    want = [("lookup_company", {"name": ent}), ("search_documents", {"query": ent, "doc_type": "payslip"}),
            ("search_documents", {"query": ent, "doc_type": "employment_letter"})]
    if monthly:
        want.append(("search_documents", {"query": ent, "doc_type": "tax_return"}))
    d = v.calls(want, "check the employer in the registry and find payslips, letters and tax notices")
    if d:
        return d
    company = next((r for r in v.records("lookup_company") if r.get("match") == "exact"), None) or \
        next(iter(v.records("lookup_company")), None)
    mine = lambda r: _same(r.get("fields", {}).get("employer", ""), ent)  # noqa: E731
    payslips = [r for r in v.docs("payslip") if mine(r)]
    letters = [r for r in v.docs("employment_letter") if mine(r)]
    taxes = [r for r in v.docs("tax_return") if mine(r)]
    others = [r for r in v.docs("payslip") + v.docs("employment_letter") if not mine(r)
              and text_score(r.get("fields", {}).get("employer", ""), ent) >= 0.4]
    if others and not payslips and not letters and not v.asked and v.human is None:
        name = others[0]["fields"]["employer"]
        return {"action": "ask_user", "thought": "employer name on the document differs from the declaration",
                "question": f"The document names the employer '{name}'. Is this the same employer as '{ent}'?",
                "options": ["yes", "no"], "alias_candidate": name}
    if others and v.human and v.human.lower().startswith("y"):
        payslips += [r for r in others if r.get("doc_type") == "payslip"]
        letters += [r for r in others if r.get("doc_type") == "employment_letter"]

    checks, used = [], []
    if company and c.get("date"):
        checks.append({"label": "employment start not before the employer's incorporation", "kind": "date_order",
                       "claimed": c["date"], "documented": company["incorporated"]})
    if company and company.get("dissolved") and c.get("period_end"):
        checks.append({"label": "employer not dissolved before the employment ended", "kind": "date_order",
                       "claimed": company["dissolved"], "documented": c["period_end"]})
    if c.get("amount") and c.get("event") == "annual bonus":
        p = next((p for p in payslips if _get(p["fields"], "bonus", "annual bonus")), None)
        if p:
            used.append(p)
            checks.append({"label": "bonus vs payslip", "kind": "amount", "claimed": c["amount"],
                           "documented": parse_amount(_get(p["fields"], "bonus", "annual bonus")), "currency": "HKD"})
            if c.get("date") and p["fields"].get("pay period"):
                checks.append({"label": "bonus month vs payslip period", "kind": "date", "claimed": c["date"],
                               "documented": p["fields"]["pay period"]})
    elif monthly:
        p = next((p for p in payslips if _get(p["fields"], "basic monthly salary", "basic salary", "gross pay")), None)
        if p:
            used.append(p)
            checks.append({"label": "monthly salary vs payslip", "kind": "amount", "claimed": c["amount"],
                           "documented": parse_amount(_get(p["fields"], "basic monthly salary", "basic salary",
                                                           "gross pay")), "currency": "HKD"})
        for t in taxes:
            year = re.match(r"(\d{4})", t["fields"].get("year of assessment", ""))
            income = parse_amount(t["fields"].get("total income from employment", ""))
            if year and income and c.get("date", "9999") <= f"{year.group(1)}-04":
                used.append(t)
                checks.append({"label": f"monthly salary x 12 vs salaries tax {t['fields']['year of assessment']}",
                               "kind": "amount", "claimed": c["amount"], "multiplier": 12, "documented": income,
                               "currency": "HKD"})
                break
    for lt in letters:
        used.append(lt)
        if c.get("date") and lt["fields"].get("start date"):
            checks.append({"label": "start date vs employment letter", "kind": "date", "claimed": c["date"],
                           "documented": lt["fields"]["start date"]})
        if c.get("period_end") and lt["fields"].get("end date"):
            checks.append({"label": "end date vs employment letter", "kind": "date", "claimed": c["period_end"],
                           "documented": lt["fields"]["end date"]})
    d, res = v.check(checks)
    if d:
        return d
    conflicts = [_conflict_text(r) for r in (res or {}).get("checks", []) if not r["consistent"]]
    if company and company.get("dissolved") and not c.get("period_end") and c.get("event") != "annual bonus":
        conflicts.append(f"Registry shows {company['name_en']} dissolved on {company['dissolved']}, but the claim "
                         "describes current employment.")
    ev = v.decl + ([company["evidence_id"]] if company else []) + [r["evidence_id"] for r in used + payslips[:1]] + _calc_ids(v)
    if conflicts:
        return v.finish("potential_red_flag", ev,
                        f"The registry and/or documents conflict with the declared employment at {ent}; see conflicts.",
                        conflicts=conflicts, questions=[f"Ask the client to explain the discrepancies for {ent}."])
    if not company:
        if v.failed("lookup_company"):
            return v.finish("unresolved", ev, "The Companies Registry lookup failed during this run.",
                            missing=[f"Registry extract for {ent}"], questions=["Re-run the registry check."])
        return v.finish("unresolved", ev, f"{ent} was not found in the (mock) Companies Registry.",
                        missing=[f"Business registration details of {ent} (it may be an overseas employer)"],
                        questions=[f"Confirm the legal name and place of incorporation of {ent}."])
    if not (payslips or letters):
        return v.finish("unresolved", ev,
                        f"The registry shows {company['name_en']} existed, but the packet has no payslip, employment "
                        f"letter or tax notice from {ent}; existence of the employer does not verify the employment.",
                        missing=[f"Employment letter or reference from {ent} confirming position and period",
                                 f"Payslips or salaries tax notices for the period at {ent}"])
    numbers = {}
    for r in (res or {}).get("checks", []):
        if r["kind"] == "amount" and r.get("multiplier", 1) == 1:
            numbers = {"claimed_hkd": r["claimed_hkd"], "documented_hkd": r["documented_hkd"]}
            break
    note = ""
    prior = [s for _, _, s in v.memory]
    if prior:
        note = f" An earlier verified record exists ({prior[0][:90]}...); the new figure is supported by current documents."
    return v.finish("supported", ev,
                    f"{company['name_en']} (CR {company['cr_number']}, incorporated {company['incorporated']}, "
                    f"{company['status']}) existed in the claimed period, and the documents agree with the claim "
                    f"within tolerance.{note}", numbers=numbers)


# ----------------------------------------------------------------- property helpers
def _bank_rows(v: _View) -> list[dict[str, Any]]:
    rows = []
    for r in v.docs("bank_statement"):
        for row in r.get("rows", []):
            rows.append({**row, "_ev": r["evidence_id"], "_doc": r["doc"]})
    return rows


def _month_diff(a: str, b: str) -> int:
    ya, ma = int(a[:4]), int(a[5:7] or 1)
    yb, mb = int(b[:4]), int(b[5:7] or 1)
    return (yb - ya) * 12 + (mb - ma)


def _registry_tx(prop: dict[str, Any], nature: str, party_key: str, client: str) -> dict[str, Any] | None:
    return next((t for t in prop.get("transactions", []) if t.get("nature") == nature
                 and _same(t.get(party_key, ""), client)), None)


# ----------------------------------------------------------------- property purchase
def _purchase(v: _View) -> dict[str, Any]:
    c, ent = v.claim, v.claim.get("entity", "")
    text = c.get("text", "")
    gift = bool(re.search(r"gift|parents", text, re.I))
    want = [("lookup_property", {"address": ent}), ("search_documents", {"query": ent, "doc_type": "property"}),
            ("search_documents", {"query": ent, "doc_type": "mortgage"}),
            ("search_documents", {"query": "balance brought forward", "doc_type": "bank_statement", "limit": 6})]
    if gift:
        want.append(("search_documents", {"query": "gift", "doc_type": "letter"}))
    d = v.calls(want, "check the Land Registry, purchase and mortgage papers and bank statements")
    if d:
        return d
    prop = next(iter(v.records("lookup_property")), None)
    tx = _registry_tx(prop, "Assignment", "to", v.client) if prop else None
    mort = _registry_tx(prop, "Mortgage", "mortgagor", v.client) if prop else None
    mdoc = next(iter(v.docs("mortgage")), None)
    loan = (mort or {}).get("amount") or (parse_amount(mdoc["fields"].get("loan amount", "")) if mdoc else None)
    m = re.search(r"mortgage of\s+((?:HKD|HK\$)\s?[\d,]+)", text, re.I)
    claimed_loan = parse_amount(m.group(1)) if m else None
    checks = []
    if tx:
        checks += [{"label": "purchase price vs Land Registry consideration", "kind": "amount", "claimed": c["amount"],
                    "documented": tx["consideration"], "currency": "HKD"},
                   {"label": "purchase date vs Land Registry assignment", "kind": "date", "claimed": c["date"],
                    "documented": tx["date"]}]
        if claimed_loan and loan:
            checks.append({"label": "declared mortgage vs registered mortgage", "kind": "amount",
                           "claimed": claimed_loan, "documented": loan, "currency": "HKD"})
    d, res = v.check(checks)
    if d:
        return d
    conflicts = [_conflict_text(r) for r in (res or {}).get("checks", []) if not r["consistent"]]
    base_ev = v.decl + ([prop["evidence_id"]] if prop else []) + [r["evidence_id"] for r in v.docs("property")[:1]] + \
        ([mdoc["evidence_id"]] if mdoc else [])
    if not prop or not tx:
        return v.finish("potential_red_flag" if prop else "unresolved", base_ev,
                        "The Land Registry does not show this purchase by the client." if prop else
                        f"No Land Registry record was found for {ent}.",
                        conflicts=[f"No assignment to {v.client} is registered for {ent}."] if prop else [],
                        missing=[] if prop else ["Land search / assignment for the property"],
                        questions=["Confirm the exact address and registered owner."])
    if conflicts:
        return v.finish("potential_red_flag", base_ev + _calc_ids(v),
                        "The Land Registry conflicts with the declared purchase; see conflicts.", conflicts=conflicts,
                        questions=["Ask the client to explain the difference from the registered transaction."])
    completion = parse_date(tx["date"])
    rows = _bank_rows(v)
    bf = [r for r in rows if "brought forward" in r.get("description", "").lower()
          and 0 <= _month_diff(parse_date(r["date"]), completion) <= 3]
    missing, questions = [], []
    if not bf:
        missing.append(f"Bank statements covering the deposit and completion payments "
                       f"(about {completion[:7]} and the three months before)")
        if gift:
            missing.append("Bank record of the third-party gift transfer")
        return v.finish("unresolved", base_ev + _calc_ids(v),
                        f"The Land Registry confirms the purchase (consideration HKD {tx['consideration']:,}), but no "
                        "bank statement covers the payment period, so the funding cannot be reconciled.",
                        missing=missing)
    start = bf[0]
    window = [r for r in rows if r["_ev"] == start["_ev"] and parse_date(r["date"]) <= completion]
    letter = next(iter(v.docs("letter")), None)
    donor = (letter or {}).get("fields", {}).get("donor", "")
    items = [{"date": start["date"], "label": "opening balance (brought forward)", "direction": "in",
              "amount": parse_amount(start["balance"]), "currency": "HKD", "evidence_id": start["_ev"]}]
    unexplained, sources = [], {"savings": True, "mortgage": bool(loan), "proceeds": False, "gift": False}
    for r in window:
        credit = parse_amount(r.get("credit", "")) if r.get("credit") else None
        if not credit:
            continue
        desc = r.get("description", "")
        if re.search(r"PAYROLL|SALARY|RENT RECEIVED", desc, re.I):
            items.append({"date": r["date"], "label": desc[:60], "direction": "in", "amount": credit,
                          "currency": "HKD", "evidence_id": r["_ev"]})
        elif re.search(r"SALE PROCEEDS", desc, re.I):
            sources["proceeds"] = True
            items.append({"date": r["date"], "label": desc[:60], "direction": "in", "amount": credit,
                          "currency": "HKD", "evidence_id": r["_ev"]})
        elif donor and (re.search(r"GIFT", desc, re.I) or _same(donor.split("(")[0], desc)):
            sources["gift"] = True
            items.append({"date": r["date"], "label": desc[:60], "direction": "in", "amount": credit,
                          "currency": "HKD", "evidence_id": r["_ev"]})
        else:
            unexplained.append(f"{r['date']} {desc} HKD {credit:,.0f}")
    if loan:
        items.append({"date": completion, "label": "mortgage loan at completion", "direction": "in", "amount": loan,
                      "currency": "HKD", "evidence_id": (prop or {}).get("evidence_id", "")})
    items.append({"date": completion, "label": "purchase price", "direction": "out", "amount": tx["consideration"],
                  "currency": "HKD", "evidence_id": prop["evidence_id"]})
    d, tl = v.timeline(items, f"Funding of {ent}")
    if d:
        return d
    gap = tl["funding_gap_hkd"]
    ev = base_ev + [start["_ev"]] + _calc_ids(v)
    if gap > 0.05 * tx["consideration"]:
        conf = [f"Documented savings, explained credits and the mortgage leave a funding gap of HKD {gap:,.0f} "
                f"against the price of HKD {tx['consideration']:,}."]
        if unexplained:
            conf.append("Payments rely on credits not explained by any declared source: " + "; ".join(unexplained))
        return v.finish("potential_red_flag", ev,
                        "The declared funding (mortgage and savings) does not reconcile with the purchase price; "
                        "the calculator shows a funding gap beyond tolerance.", conflicts=conf,
                        questions=["Ask the client to explain and evidence the unexplained credits / funding gap."],
                        numbers={"funding_gap_hkd": gap})
    declared = {"proceeds": bool(re.search(r"proceeds", text, re.I)), "gift": gift}
    for k, label in (("proceeds", "Bank statement showing receipt of the sale proceeds used for this purchase"),
                     ("gift", "Bank record of the third-party gift transfer")):
        if declared[k] and not sources[k]:
            missing.append(label)
    if missing:
        return v.finish("unresolved", ev,
                        f"The registry confirms the purchase and the balances cover the price (funding gap HKD {gap:,.0f}), "
                        "but a declared funding source is not evidenced in the packet.", missing=missing,
                        numbers={"funding_gap_hkd": gap})
    if unexplained:
        questions.append("Ask about these credits before the purchase: " + "; ".join(unexplained))
    return v.finish("supported", ev,
                    f"Land Registry assignment of {tx['date']} for HKD {tx['consideration']:,} matches the claim; the "
                    f"documented opening balance, explained credits and the mortgage reconcile with the price "
                    f"(funding gap HKD {gap:,.0f}).", questions=questions, numbers={"funding_gap_hkd": gap})


# ----------------------------------------------------------------- property sale
def _sale(v: _View) -> dict[str, Any]:
    c, ent = v.claim, v.claim.get("entity", "")
    d = v.calls([("lookup_property", {"address": ent}),
                 ("search_documents", {"query": "sale proceeds", "doc_type": "bank_statement"})],
                "check the Land Registry and look for the receipt of proceeds")
    if d:
        return d
    prop = next(iter(v.records("lookup_property")), None)
    tx = _registry_tx(prop, "Assignment", "from", v.client) if prop else None
    checks = []
    if tx:
        if c.get("amount"):
            checks.append({"label": "sale price vs Land Registry consideration", "kind": "amount",
                           "claimed": c["amount"], "documented": tx["consideration"], "currency": "HKD"})
        if c.get("date"):
            checks.append({"label": "sale date vs Land Registry assignment", "kind": "date", "claimed": c["date"],
                           "documented": tx["date"]})
    d, res = v.check(checks)
    if d:
        return d
    if not prop:
        return v.finish("unresolved", v.decl, f"No Land Registry record was found for {ent}.",
                        missing=["Land search for the property", "Assignment / completion statement of the sale"])
    ev = v.decl + [prop["evidence_id"]] + _calc_ids(v)
    if not tx:
        return v.finish("potential_red_flag", ev, "The Land Registry shows no sale of this property by the client.",
                        conflicts=[f"No assignment from {v.client} is registered for {ent}."],
                        questions=["Ask the client for the assignment and completion statement."])
    conflicts = [_conflict_text(r) for r in (res or {}).get("checks", []) if not r["consistent"]]
    if conflicts:
        return v.finish("potential_red_flag", ev,
                        f"The Land Registry records the sale on {tx['date']} for HKD {tx['consideration']:,}, which "
                        "conflicts with the declaration.", conflicts=conflicts,
                        questions=["Ask the client to explain the difference from the registered sale."])
    done = parse_date(tx["date"])
    proceeds = [r for r in _bank_rows(v) if re.search(r"SALE PROCEEDS", r.get("description", ""), re.I)
                and r.get("credit") and abs(_month_diff(parse_date(r["date"]), done)) <= 2]
    if not proceeds:
        return v.finish("unresolved", ev,
                        f"The Land Registry confirms the sale ({tx['date']}, HKD {tx['consideration']:,}), but the packet "
                        "has no record of the proceeds being received.",
                        missing=[f"Bank statement showing receipt of the sale proceeds around {done[:7]}"])
    p = proceeds[0]
    return v.finish("supported", ev + [p["_ev"]],
                    f"The Land Registry records the sale on {tx['date']} for HKD {tx['consideration']:,}, matching the "
                    f"claim, and the bank statement shows proceeds of {p['credit']} credited on {p['date']} "
                    "(proceeds may be net of mortgage redemption).", numbers={"registry_consideration_hkd": tx["consideration"]})


# ----------------------------------------------------------------- rental
def _rental(v: _View) -> dict[str, Any]:
    c, ent = v.claim, v.claim.get("entity", "")
    d = v.calls([("lookup_property", {"address": ent}), ("search_documents", {"query": ent, "doc_type": "tenancy"}),
                 ("search_documents", {"query": "rent received", "doc_type": "bank_statement"})],
                "check ownership, the tenancy and rent credits")
    if d:
        return d
    prop = next(iter(v.records("lookup_property")), None)
    ten = next(iter(v.docs("tenancy")), None)
    checks = []
    if ten and c.get("amount"):
        checks.append({"label": "monthly rent vs tenancy agreement", "kind": "amount", "claimed": c["amount"],
                       "documented": parse_amount(ten["fields"].get("monthly rent", "")) or 0, "currency": "HKD"})
        if c.get("date") and ten["fields"].get("term"):
            checks.append({"label": "rental start vs tenancy term", "kind": "date", "claimed": c["date"],
                           "documented": ten["fields"]["term"]})
    d, res = v.check(checks)
    if d:
        return d
    owner = prop and any(_same(o["name"], v.client) and (not o.get("to") or o["to"] >= c.get("date", ""))
                         for o in prop.get("owners", []))
    credits = [r for r in _bank_rows(v) if re.search(r"RENT", r.get("description", ""), re.I) and r.get("credit")
               and c.get("amount") and abs(parse_amount(r["credit"]) - c["amount"]) <= 0.05 * c["amount"]]
    ev = v.decl + ([prop["evidence_id"]] if prop else []) + ([ten["evidence_id"]] if ten else []) + \
        [r["_ev"] for r in credits[:1]] + _calc_ids(v)
    conflicts = [_conflict_text(r) for r in (res or {}).get("checks", []) if not r["consistent"]]
    if prop and not owner:
        conflicts.append(f"The Land Registry does not show {v.client} as owner of {ent} during the rental period.")
    if conflicts:
        return v.finish("potential_red_flag", ev, "Ownership or tenancy records conflict with the claim.",
                        conflicts=conflicts, questions=["Ask the client to explain the discrepancy."])
    missing = ([] if prop else ["Land search for the property"]) + ([] if ten else ["Tenancy agreement"]) + \
        ([] if credits else ["Bank statements showing the rent credits"])
    if missing:
        return v.finish("unresolved", ev, "Part of the evidence for the rental income is missing.", missing=missing)
    return v.finish("supported", ev,
                    f"The client is the registered owner, the tenancy agreement states rent of "
                    f"{ten['fields'].get('monthly rent')}, and recurring rent credits of that amount appear in the bank "
                    "statement.", numbers={"monthly_rent_hkd": c["amount"]})


# ----------------------------------------------------------------- third party
def _third_party(v: _View) -> dict[str, Any]:
    c = v.claim
    d = v.calls([("search_documents", {"query": "gift", "doc_type": "letter"}),
                 ("search_documents", {"query": f"{c.get('entity', '')} gift transfer", "doc_type": "bank_statement"}),
                 ("search_policy", {"query": "third-party gift funding source of wealth"})],
                "find the gift letter, the transfer and the applicable guidance")
    if d:
        return d
    letter = next(iter(v.docs("letter")), None)
    checks = []
    if letter and c.get("amount"):
        checks.append({"label": "gift amount vs gift letter", "kind": "amount", "claimed": c["amount"],
                       "documented": parse_amount(letter["fields"].get("amount", "")) or 0, "currency": "HKD"})
    d, res = v.check(checks)
    if d:
        return d
    donor = (letter or {}).get("fields", {}).get("donor", "")
    transfer = [r for r in _bank_rows(v) if r.get("credit") and donor and
                (re.search(r"GIFT", r.get("description", ""), re.I) or _same(donor.split("(")[0], r["description"]))]
    policy = [r["evidence_id"] for r in v.records("search_policy")[:1]]
    ev = v.decl + ([letter["evidence_id"]] if letter else []) + [r["_ev"] for r in transfer[:1]] + _calc_ids(v) + policy
    conflicts = [_conflict_text(r) for r in (res or {}).get("checks", []) if not r["consistent"]]
    if conflicts:
        return v.finish("potential_red_flag", ev, "The gift documents conflict with the declaration.",
                        conflicts=conflicts, questions=["Ask the client to explain the difference."])
    donor_q = [f"What is the donor's ({donor or c.get('entity', 'third party')}) own source of wealth?"]
    if not letter:
        return v.finish("unresolved", ev, "No gift letter or transfer record is in the packet.",
                        missing=["Signed gift letter", "Bank record of the transfer"], questions=donor_q)
    if not transfer:
        return v.finish("unresolved", ev,
                        f"A signed gift letter from {donor} for {letter['fields'].get('amount')} is in the packet, but no "
                        "bank record shows the transfer; guidance normally expects evidence of the transfer and of the "
                        "donor's own source of wealth.",
                        missing=["Bank record of the gift transfer (donor's and client's statements)",
                                 "Evidence of the donor's source of wealth"], questions=donor_q)
    return v.finish("supported", ev, f"The gift letter and the bank transfer agree with the claim.",
                    questions=donor_q, numbers={"gift_hkd": c["amount"]})


# ----------------------------------------------------------------- other / out of scope
def _other(v: _View) -> dict[str, Any]:
    c = v.claim
    want = [("search_policy", {"query": "business income source of wealth evidence"})]
    if c.get("entity"):
        want.append(("lookup_company", {"name": c["entity"]}))
    d = v.calls(want, "this source is outside the automated scope; record what is needed")
    if d:
        return d
    co = next(iter(v.records("lookup_company")), None)
    ev = v.decl + [r["evidence_id"] for r in v.records("search_policy")[:1]] + ([co["evidence_id"]] if co else [])
    note = (f" The registry shows {co['name_en']} ({co['status']}, incorporated {co['incorporated']}), but existence "
            "of a company does not evidence income from it.") if co else ""
    return v.finish("unresolved", ev,
                    "This source (business / consulting income) is outside the automated scope and requires manual "
                    f"review.{note}",
                    missing=[f"Audited accounts and tax returns of {c.get('entity') or 'the business'}",
                             "Records of dividends or director's fees paid to the client"],
                    questions=["How much of the client's wealth comes from this source, and over what period?"])


# ----------------------------------------------------------------- independent reviewer
def _review(text: str) -> str:
    items = json.loads(_block(text, "FINDINGS_JSON:", "END_FINDINGS") or "[]")
    out = []
    for it in items:
        spans = [s for s in it.get("cited_spans", []) if s["type"] in ("document", "registry", "memory", "calculation")]
        if it["status"] == "supported":
            ok = any(text_score(s["text"], it["claim"]) >= 0.25 for s in spans if s["type"] != "calculation")
            comment = "cited spans mention the claimed entity and figures" if ok else "no cited span clearly matches the claim"
        else:
            ok = bool(it.get("conflicts")) and any(s["type"] in ("registry", "calculation", "document") for s in spans)
            comment = "the cited records show the stated conflict" if ok else "the conflict is not visible in the cited spans"
        out.append({"claim_id": it["claim_id"], "supports": ok, "comment": comment})
    return json.dumps({"reviews": out})


# ----------------------------------------------------------------- System A baseline
def _baseline(text: str) -> str:
    """Naive single-prompt synthesis: mention of the entity anywhere in the packet counts as support,
    no arithmetic, no registry reasoning — the failure mode the proposal warns about."""
    decl = json.loads(_block(text, "DECLARATION_JSON:", "END_DECLARATION") or "[]")
    packet = json.loads(_block(text, "PACKET_JSON:", "END_PACKET") or "[]")
    out = []
    for c in _claims_from_chunks(decl):
        hits = [p for p in packet if c["entity"] and text_score(p["text"], c["entity"]) >= 0.6]
        if c["category"] == "other" or not hits:
            out.append({"claim_text": c["text"], "category": c["category"], "verdict": "unresolved",
                        "evidence_ids": [], "rationale": "mock baseline: no document mentions this",
                        "conflicts": [], "missing_evidence": ["supporting documents"]})
        else:
            out.append({"claim_text": c["text"], "category": c["category"], "verdict": "supported",
                        "evidence_ids": [hits[0]["evidence_id"]], "rationale": "mock baseline: a document mentions it",
                        "conflicts": []})
    return json.dumps({"findings": out})
