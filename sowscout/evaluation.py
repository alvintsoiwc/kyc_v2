"""Evaluation harness (proposal §4, Tables 1–2, Eq. 1–2).

Runs each benchmark case through each system and scores against the gold
records in eval/cases.json:

  elvs                Evidence-Linked Verification Score (Eq. 1): 0–100 scale, defined as
                      (100 / N) * sum_i (S_i * E_i * A_i). Headline reports the equally weighted
                      mean of per-case ELVS values, plus the S, E, A components separately.
  joint_correctness   gold claims with the right status (S_i) AND a justified evidence link (E_i)
                      AND, for numeric gold values, the right figure (±1%, A_i)     [primary]
  red_flag_recall     gold red flags labelled potential_red_flag
  false_flag_rate     gold non-red-flags labelled potential_red_flag                   (lower = better)
  unresolved_as_supported  gold unresolved presented as supported                      (lower = better)
  macro_f1            over the three labels (missing claims count as wrong)
  evidence_support    status-bearing claims citing a gold evidence identifier (automatic proxy; the proposal's
                      manual span review must confirm it)
  unsupported_facts   'supported' findings that cite no document / registry / memory evidence
  arithmetic_errors   numeric gold values missing or wrong; funding_gap_abs_error (HKD)
  extraction          claim precision / recall / F1 and field accuracy (entity, amount, date, category)
  efficiency          wall time, tokens, model / tool calls, estimated cost

Counterfactual robustness (§4.3, Eq. 2): controlled edits to held-out cases
(remove a document, change an amount, paraphrase); reports the Counterfactual
Consistency Rate (CCR, Eq. 2: both original and edited statuses match gold),
paired counts (e.g. "2/3"), and conditional accuracy when the original claim
was correct.

Systems: A (baselines.run_direct) and B, C, C-no-calc, C-no-gate, C-no-skills
(workflow variants, config.SYSTEMS). With --runs N each case is run N times and
the mean and range are reported. With --provider mock the numbers only test the
pipeline (the mock's rules were written alongside the cases); report real-model runs.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import statistics
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .baselines import run_direct
from .config import ROOT, SYSTEMS
from .memory import seed_case_memory
from .state import SUPPORTING_TYPES, VERDICTS, RunState
from .tools.text import norm_name, parse_date, text_score
from .workflow import Workflow

HEADLINE = ["elvs", "joint_correctness", "red_flag_recall", "false_flag_rate", "evidence_support", "arithmetic_errors"]


@contextmanager
def _env(**kv: str):
    old = {k: os.environ.get(k) for k in kv}
    os.environ.update({k: v for k, v in kv.items() if v is not None})
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _mean(xs: list[float]) -> float | None:
    return round(statistics.mean(xs), 3) if xs else None


def _match(findings: list[dict[str, Any]], e: dict[str, Any]) -> dict[str, Any] | None:
    return next((f for f in findings if all(m.lower() in f["claim_text"].lower() for m in e["match"])), None)


def _cites(f: dict[str, Any], evidence: dict[str, dict[str, Any]], wanted: list[str]) -> bool:
    idents = [str(evidence.get(x, {}).get("identifier", "")) for x in f.get("evidence_ids", [])]
    return any(w.lower() in i.lower() for w in wanted for i in idents)


def _value_ok(f: dict[str, Any], gold: dict[str, float]) -> tuple[bool, float | None]:
    nums = f.get("numbers") or {}
    ok, err = True, None
    for k, g in gold.items():
        x = nums.get(k)
        if not isinstance(x, (int, float)) or abs(x - g) > 0.01 * max(abs(g), 1000.0):
            ok = False
        if k == "funding_gap_hkd" and isinstance(x, (int, float)):
            err = abs(x - g)                 # missing figures count as arithmetic errors, not as an abs. error
    return ok, err


def _field_ok(name: str, got: Any, want: Any) -> bool:
    if name == "entity":
        return bool(got) and (norm_name(got) == norm_name(want) or text_score(got, want) >= 0.75)
    if name == "amount":
        return isinstance(got, (int, float)) and abs(got - want) <= 0.01 * abs(want)
    if name == "date":
        return (parse_date(str(got or "")) or "").startswith(want)
    return got == want


def score(findings: list[dict[str, Any]], evidence: dict[str, dict[str, Any]], expected: list[dict[str, Any]]
          ) -> dict[str, Any]:
    pairs = [(e, _match(findings, e)) for e in expected]
    per_claim, joint, s_list, e_list, a_list, ev_support, arith = [], [], [], [], [], [], []
    gap_err: list[float] = []
    for e, f in pairs:
        got = f["verdict"] if f else None
        status_ok = got == e["status"]
        if e["status"] == "unresolved":
            link = bool(f and (f.get("missing_evidence") or f.get("open_questions")))
        else:
            link = bool(f and _cites(f, evidence, e.get("evidence", [])))
            ev_support.append(1.0 if link else 0.0)
        num_ok = True
        if e.get("values"):
            num_ok, err = _value_ok(f or {}, e["values"])
            arith.append(0 if num_ok else 1)
            if err is not None:
                gap_err.append(err)
        ok = status_ok and link and num_ok
        joint.append(1.0 if ok else 0.0)
        s_list.append(1.0 if status_ok else 0.0)
        e_list.append(1.0 if link else 0.0)
        a_list.append(1.0 if num_ok else 0.0)
        per_claim.append({"match": " & ".join(e["match"]), "expected": e["status"], "got": got, "status_ok": status_ok,
                          "link_ok": link, "numbers_ok": num_ok, "ok": ok})
    gold_rf = [(e, f) for e, f in pairs if e["status"] == "potential_red_flag"]
    gold_not_rf = [(e, f) for e, f in pairs if e["status"] != "potential_red_flag"]
    gold_unres = [(e, f) for e, f in pairs if e["status"] == "unresolved"]
    f1s = []
    for lab in VERDICTS:
        tp = sum(1 for e, f in pairs if e["status"] == lab and f and f["verdict"] == lab)
        fp = sum(1 for e, f in pairs if e["status"] != lab and f and f["verdict"] == lab)
        fn = sum(1 for e, f in pairs if e["status"] == lab and not (f and f["verdict"] == lab))
        if tp + fp + fn:
            f1s.append(2 * tp / (2 * tp + fp + fn))
    supported = [f for f in findings if f["verdict"] == "supported"]
    unsupported = sum(1 for f in supported if not any(evidence.get(x, {}).get("evidence_type") in SUPPORTING_TYPES
                                                      for x in f.get("evidence_ids", [])))
    # extraction
    matched = [(e, f) for e, f in pairs if f]
    fields = [(k, _field_ok(k, f.get(k), v)) for e, f in matched for k, v in e.get("fields", {}).items()
              if k in f]          # System A returns no typed fields: field accuracy is not applicable
    prec = len({id(f) for _, f in matched}) / len(findings) if findings else 0.0
    rec = len(matched) / len(pairs) if pairs else 0.0
    jc = _mean(joint)
    return {
        "elvs": round(100.0 * jc, 1) if jc is not None else None,
        "joint_correctness": jc,
        "status_accuracy": _mean(s_list),
        "evidence_accuracy": _mean(e_list),
        "arithmetic_accuracy": _mean(a_list),
        "red_flag_recall": _mean([1.0 if f and f["verdict"] == "potential_red_flag" else 0.0 for _, f in gold_rf]),
        "false_flag_rate": _mean([1.0 if f and f["verdict"] == "potential_red_flag" else 0.0 for _, f in gold_not_rf]),
        "unresolved_as_supported": _mean([1.0 if f and f["verdict"] == "supported" else 0.0 for _, f in gold_unres]),
        "macro_f1": round(statistics.mean(f1s), 3) if f1s else None,
        "evidence_support": _mean(ev_support),
        "unsupported_facts": unsupported,
        "arithmetic_errors": sum(arith),
        "funding_gap_abs_error": round(sum(gap_err), 2) if gap_err else None,
        "claim_precision": round(prec, 3), "claim_recall": round(rec, 3),
        "claim_f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
        "field_accuracy": _mean([1.0 if ok else 0.0 for _, ok in fields]),
        "per_claim": per_claim, "n_gold": len(pairs), "n_findings": len(findings),
    }


# ----------------------------------------------------------------- running systems
def _materialise(cdir: Path, edits: list[dict[str, Any]], tmp: Path) -> Path:
    """Copy a case and apply counterfactual edits; never touches the original case."""
    out = tmp / cdir.name
    shutil.copytree(cdir, out)
    for ed in edits:
        p = out / "materials" / ed["doc"]
        if ed["op"] == "remove":
            p.unlink()
        elif ed["op"] == "replace":
            text = p.read_text(encoding="utf-8")
            if ed["old"] not in text:
                raise ValueError(f"counterfactual edit not applicable: {ed['old'][:60]!r} not in {ed['doc']}")
            p.write_text(text.replace(ed["old"], ed["new"]))
    return out


def _run_system(settings, system: str, cdir: Path, meta: dict[str, Any], work: Path) -> dict[str, Any]:
    s = copy.deepcopy(settings)
    s.runs_dir = work / "runs"
    s.db_path = work / f"{system}-{cdir.name}-{time.time_ns()}.db"   # isolated memory per run
    seed_case_memory(s.db_path, cdir, meta["client"])
    t0 = time.perf_counter()
    if system == "A":
        r = run_direct(s, meta["client"], cdir / "materials", cdir, s.runs_dir)
        r["summary"]["wall_time_s"] = round(time.perf_counter() - t0, 2)
        return r
    s.system = system
    st = RunState.new(meta["client"], str(cdir / "materials"), meta.get("client_ref", ""))
    wf = Workflow(s, st, case_dir=cdir, echo=False)
    wf.run()
    findings = [{"claim_text": c.text, "category": c.category, "entity": c.entity, "amount": c.amount,
                 "date": c.date, "verdict": f.verdict, "evidence_ids": f.evidence_ids, "conflicts": f.conflicts,
                 "missing_evidence": f.missing_evidence, "open_questions": f.open_questions, "numbers": f.numbers}
                for c in st.claims if (f := st.findings.get(c.claim_id)) and f.task_id != "out_of_scope"]
    return {"system": system, "run_id": st.run_id, "findings": findings,
            "evidence": {k: {"identifier": e.identifier, "evidence_type": e.evidence_type} for k, e in st.evidence.items()},
            "counters": vars(st.counters),
            "summary": {**wf.tracer.summary(), "wall_time_s": round(time.perf_counter() - t0, 2)}}


def _row(sc_id: str, kind: str, system: str, runs: list[dict[str, Any]], expected) -> dict[str, Any]:
    scores = [score(r["findings"], r["evidence"], expected) for r in runs]
    row: dict[str, Any] = {"scenario": sc_id, "kind": kind, "system": system, "runs": len(runs)}
    for k in ("elvs", "joint_correctness", "status_accuracy", "evidence_accuracy", "arithmetic_accuracy",
              "red_flag_recall", "false_flag_rate", "unresolved_as_supported", "macro_f1",
              "evidence_support", "unsupported_facts", "arithmetic_errors", "funding_gap_abs_error", "claim_precision",
              "claim_recall", "claim_f1", "field_accuracy"):
        vals = [s[k] for s in scores if s[k] is not None]
        row[k] = _mean(vals) if vals else None
        if len(vals) > 1:
            row[k + "_range"] = [min(vals), max(vals)]
    for k in ("model_calls", "tool_calls", "tool_errors", "format_repairs", "verify_rejections", "gate_downgrades",
              "tokens_in", "tokens_out", "cost_usd"):
        row[k] = _mean([r["counters"].get(k, 0) for r in runs])
    row["wall_time_s"] = _mean([r["summary"].get("wall_time_s", 0) for r in runs])
    row["per_claim"] = scores[0]["per_claim"]
    row["counts"] = {"n_gold": scores[0]["n_gold"], "n_findings": scores[0]["n_findings"],
                     "joint_correct": int(sum(p["ok"] for p in scores[0]["per_claim"])),
                     "status_correct": int(sum(p["status_ok"] for p in scores[0]["per_claim"])),
                     "link_correct": int(sum(p["link_ok"] for p in scores[0]["per_claim"])),
                     "numbers_correct": int(sum(p["numbers_ok"] for p in scores[0]["per_claim"]))}
    return row


def _score_counterfactual(row: dict[str, Any], base_row: dict[str, Any] | None) -> None:
    """Compute CCR (Eq. 2): a pair is correct iff BOTH original and edited statuses match gold."""
    base_by_match = {p["match"]: p for p in (base_row or {}).get("per_claim", [])}
    pairs_ok, cond_ok, n_orig_ok = [], [], 0
    for p in row["per_claim"]:
        bp = base_by_match.get(p["match"])
        orig_ok = bp["status_ok"] if bp is not None else True
        p["orig_expected"] = bp["expected"] if bp is not None else None
        p["orig_got"] = bp["got"] if bp is not None else None
        p["orig_status_ok"] = orig_ok
        pair_ok = bool(orig_ok and p["status_ok"])
        p["pair_ok"] = pair_ok
        pairs_ok.append(1.0 if pair_ok else 0.0)
        if orig_ok:
            n_orig_ok += 1
            cond_ok.append(1.0 if p["status_ok"] else 0.0)
    m = len(pairs_ok)
    k = int(sum(pairs_ok))
    row["expected_behaviour_rate"] = _mean([1.0 if p["status_ok"] else 0.0 for p in row["per_claim"]])
    row["ccr"] = round(100.0 * k / m, 1) if m else None
    row["ccr_rate"] = _mean(pairs_ok)
    row["ccr_count"] = f"{k}/{m}"
    row["conditional_rate"] = _mean(cond_ok)
    row["conditional_count"] = f"{int(sum(cond_ok))}/{n_orig_ok}"


def run_eval(settings, systems: list[str], scenarios: list[str] | None = None, split: str = "all", runs: int = 1,
             on_row=None, out_dir: Path | None = None) -> dict[str, Any]:
    bad = [s for s in systems if s != "A" and s not in SYSTEMS]
    if bad:
        raise SystemExit(f"unknown systems {bad}; use A or {sorted(SYSTEMS)}")
    spec = json.loads((ROOT / "eval" / "cases.json").read_text(encoding="utf-8"))
    cases = [c for c in spec["scenarios"] if split == "all" or c["split"] == split]
    cfs = [c for c in spec.get("counterfactuals", []) if any(b["id"] == c["base"] for b in cases)]
    if scenarios:
        cases = [c for c in cases if c["id"] in scenarios]
        cfs = [c for c in cfs if c["id"] in scenarios or c["base"] in scenarios]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = out_dir or ROOT / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="sowscout-eval-"))
    rows, cf_rows = [], []
    base_cache: dict[tuple[str, str], dict[str, Any]] = {}
    for sc in cases + cfs:
        is_cf = sc in cfs
        base = next(c for c in spec["scenarios"] if c["id"] == (sc["base"] if is_cf else sc["id"]))
        cdir = ROOT / "data" / "cases" / base["case"]
        if is_cf:
            cdir = _materialise(cdir, sc["edits"], Path(tempfile.mkdtemp(dir=work)))
        meta = json.loads((cdir / "case.json").read_text(encoding="utf-8"))
        for system in systems:
            with _env(SOWSCOUT_FAULTS=sc.get("faults", ""), SOWSCOUT_MOCK_FAULTS=sc.get("mock_faults", "")):
                results = [_run_system(settings, system, cdir, meta, work) for _ in range(max(1, runs))]
            row = _row(sc["id"], sc.get("kind", ""), system, results, sc["expected"])
            if is_cf:
                row["base"] = base["id"]
                base_row = base_cache.get((base["id"], system))
                if base_row is None:
                    base_cdir = ROOT / "data" / "cases" / base["case"]
                    with _env(SOWSCOUT_FAULTS=base.get("faults", ""), SOWSCOUT_MOCK_FAULTS=base.get("mock_faults", "")):
                        base_res = [_run_system(settings, system, base_cdir, meta, work) for _ in range(max(1, runs))]
                    base_row = _row(base["id"], base.get("kind", ""), system, base_res, base["expected"])
                    base_cache[(base["id"], system)] = base_row
                _score_counterfactual(row, base_row)
                cf_rows.append(row)
            else:
                base_cache[(sc["id"], system)] = row
                rows.append(row)
            if on_row:
                on_row(row)
            print(f"[eval] {sc['id']:<24} {system:<11} elvs={row['elvs']} joint={row['joint_correctness']} "
                  f"rf_recall={row['red_flag_recall']} false_flag={row['false_flag_rate']} ev={row['evidence_support']} "
                  f"arith_err={row['arithmetic_errors']}"
                  + (f" ccr={row['ccr']} ({row['ccr_count']}) cf_expected={row['expected_behaviour_rate']}" if is_cf else ""))
    summary = _aggregate(rows, cf_rows, systems)
    meta = {"timestamp": stamp, "provider": settings.provider, "model": settings.default_model(),
            "temperature": settings.temperature, "split": split, "runs": runs, "limits": vars(settings.limits)}
    result = {"meta": meta, "summary": summary, "rows": rows, "counterfactuals": cf_rows}
    (out_dir / f"{stamp}.json").write_text(json.dumps(result, indent=2))
    (out_dir / f"{stamp}.md").write_text(_markdown(result))
    print(f"[eval] wrote {out_dir / (stamp + '.md')}")
    if settings.provider == "mock":
        print("[eval] NOTE: provider=mock — these numbers test the pipeline, not model quality.")
    shutil.rmtree(work, ignore_errors=True)
    return result


def _aggregate(rows: list[dict[str, Any]], cf_rows: list[dict[str, Any]], systems: list[str]) -> list[dict[str, Any]]:
    """Aggregate per-case ELVS (equally weighted mean, Eq. 1), S/E/A components, micro-averaged rates, and CCR (Eq. 2)."""
    out = []
    for s in systems:
        mine = [r for r in rows if r["system"] == s]
        my_cf = [r for r in cf_rows if r["system"] == s]
        if not mine and not my_cf:
            continue
        pc = [p for r in mine for p in r["per_claim"]]
        rf = [p for p in pc if p["expected"] == "potential_red_flag"]
        nrf = [p for p in pc if p["expected"] != "potential_red_flag"]
        elvs_vals = [r["elvs"] for r in mine if r.get("elvs") is not None]
        cf_pc = [p for r in my_cf for p in r["per_claim"]]
        cf_pairs_ok = sum(1 for p in cf_pc if p.get("pair_ok"))
        cf_orig_ok = [p for p in cf_pc if p.get("orig_status_ok", True)]
        cf_cond_ok = sum(1 for p in cf_orig_ok if p["status_ok"])
        out.append({"system": s, "cases": len(mine), "gold_claims": len(pc),
                    "elvs": round(statistics.mean(elvs_vals), 1) if elvs_vals else None,
                    "joint_correct": sum(p["ok"] for p in pc),
                    "joint_correctness": _mean([1.0 if p["ok"] else 0.0 for p in pc]),
                    "status_correct": sum(1 for p in pc if p["status_ok"]),
                    "status_accuracy": _mean([1.0 if p["status_ok"] else 0.0 for p in pc]),
                    "evidence_correct": sum(1 for p in pc if p["link_ok"]),
                    "evidence_accuracy": _mean([1.0 if p["link_ok"] else 0.0 for p in pc]),
                    "arithmetic_correct": sum(1 for p in pc if p["numbers_ok"]),
                    "arithmetic_accuracy": _mean([1.0 if p["numbers_ok"] else 0.0 for p in pc]),
                    "red_flag_recall": _mean([1.0 if p["got"] == "potential_red_flag" else 0.0 for p in rf]),
                    "false_flag_rate": _mean([1.0 if p["got"] == "potential_red_flag" else 0.0 for p in nrf]),
                    "evidence_support": _mean([r["evidence_support"] for r in mine if r["evidence_support"] is not None]),
                    "arithmetic_errors": sum(r["arithmetic_errors"] or 0 for r in mine),
                    "unsupported_facts": sum(r["unsupported_facts"] or 0 for r in mine),
                    "ccr": round(100.0 * cf_pairs_ok / len(cf_pc), 1) if cf_pc else None,
                    "ccr_count": f"{cf_pairs_ok}/{len(cf_pc)}" if cf_pc else None,
                    "ccr_conditional": f"{cf_cond_ok}/{len(cf_orig_ok)}" if cf_pc else None,
                    "tokens_in": sum(r["tokens_in"] or 0 for r in mine),
                    "tool_calls": sum(r["tool_calls"] or 0 for r in mine),
                    "cost_usd": round(sum(r["cost_usd"] or 0 for r in mine), 4),
                    "wall_time_s": round(sum(r["wall_time_s"] or 0 for r in mine), 2)})
    return out


def _markdown(result: dict[str, Any]) -> str:
    m = result["meta"]
    L = [f"# SoWScout evaluation {m['timestamp']}", "",
         f"provider `{m['provider']}` · model `{m['model']}` · temperature {m['temperature']} · split `{m['split']}` · "
         f"runs per case {m['runs']}", ""]
    if m["provider"] == "mock":
        L += ["> MOCK provider: results validate the pipeline only; they are not evidence of model quality.", ""]
    L += ["## Headline (per-case mean ELVS & micro-average over gold claims)", "",
          "| system | cases | gold claims | ELVS (mean) | joint correct | joint correctness | S (status) | E (evidence) | A (arith) | "
          "red-flag recall | false-flag rate | evidence support | arithmetic errors | unsupported facts | CCR (pairs) | tool calls | tokens in | cost USD | wall s |",
          "|" + "---|" * 19]
    for s in result["summary"]:
        L.append(f"| {s['system']} | {s.get('cases', 0)} | {s['gold_claims']} | {s.get('elvs', '–')} | {s['joint_correct']} | "
                 f"{s['joint_correctness']} | {s.get('status_accuracy', '–')} ({s.get('status_correct', 0)}) | "
                 f"{s.get('evidence_accuracy', '–')} ({s.get('evidence_correct', 0)}) | "
                 f"{s.get('arithmetic_accuracy', '–')} ({s.get('arithmetic_correct', 0)}) | "
                 f"{s['red_flag_recall']} | {s['false_flag_rate']} | {s['evidence_support']} | {s['arithmetic_errors']} | "
                 f"{s['unsupported_facts']} | {s.get('ccr', '–')} ({s.get('ccr_count') or '–'}) | "
                 f"{s['tool_calls']} | {s['tokens_in']} | {s['cost_usd']} | {s['wall_time_s']} |")
    cols = ["system", "elvs", "joint_correctness", "status_accuracy", "evidence_accuracy", "arithmetic_accuracy",
            "red_flag_recall", "false_flag_rate", "unresolved_as_supported", "macro_f1",
            "evidence_support", "arithmetic_errors", "funding_gap_abs_error", "claim_f1", "field_accuracy",
            "model_calls", "tool_calls", "gate_downgrades", "tokens_in", "wall_time_s"]
    L += ["", "## Per case (paired scorecard)", ""]
    for sid in dict.fromkeys(r["scenario"] for r in result["rows"]):
        rows = [r for r in result["rows"] if r["scenario"] == sid]
        L += [f"### {sid}", f"_{rows[0]['kind']}_", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for r in rows:
            L.append("| " + " | ".join("–" if r.get(c) is None else str(r.get(c)) for c in cols) + " |")
        L.append("")
        for r in rows:
            L.append(f"- **{r['system']}** (ELVS {r.get('elvs', '–')}): " + "; ".join(
                f"{'✓' if p['ok'] else '✗'} {p['match']} (gold {p['expected']}, got {p['got']}"
                + (f" [S={int(p['status_ok'])},E={int(p['link_ok'])},A={int(p['numbers_ok'])}]" if not p["ok"] else "") + ")"
                for p in r["per_claim"]))
        L.append("")
    if result["counterfactuals"]:
        L += ["## Counterfactual robustness (CCR, Eq. 2)", "",
              "| edit | kind | system | CCR (Eq. 2) | paired count | conditional (orig ok) | edited status ok | detail (orig -> edited) |",
              "|---|---|---|---|---|---|---|---|"]
        for r in result["counterfactuals"]:
            det = "; ".join(
                f"{p['match']}: orig ({p.get('orig_expected')} -> {p.get('orig_got')}), "
                f"edit ({p['expected']} -> {p['got']}) [{'✓' if p.get('pair_ok') else '✗'}]"
                for p in r["per_claim"]
            )
            L.append(f"| {r['scenario']} | {r['kind']} | {r['system']} | {r.get('ccr', '–')} | {r.get('ccr_count', '–')} | "
                     f"{r.get('conditional_count', '–')} ({r.get('conditional_rate', '–')}) | {r['expected_behaviour_rate']} | {det} |")
        L.append("")
    return "\n".join(L)
