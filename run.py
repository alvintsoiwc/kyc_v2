#!/usr/bin/env python3
"""SoWScout command-line entry point.

  python run.py demo                                   # fictional client "wong", offline, mock model, System C
  python run.py run --case lee --provider ollama --model llama3.2:3b
  python run.py run --client "Chan Tai Man" --materials path/to/packet --registry path/to/registry
  python run.py run --case chan --system B             # System B (tools, no playbooks, no gate)
  python run.py run --case ho --reviewer               # + optional independent reviewer
  python run.py resume <run_id>
  python run.py remember <run_id> --officer KYC-07     # step 8: officer confirms supported findings -> client memory
  python run.py tool-check lookup_company '{"name": "Harbourview Logistics Limited"}' --case chan
  python run.py probe --case wong --claim C3           # one model decision, no tool execution
  python run.py eval                                   # systems A/B/C (+ ablations) x cases -> eval/results/
  python run.py test                                   # unit + integration tests (no model needed)
  python run.py ui                                     # web interface + run controller at http://127.0.0.1:8767
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

if __name__ == "__main__" and len(sys.argv) == 1:
    sys.exit(subprocess.call([sys.executable, str(Path(__file__).resolve().parent / "launch.py")]))
if __name__ == "__main__" and not sys.flags.utf8_mode and os.environ.get("PYTHONUTF8") != "1":
    sys.exit(subprocess.call([sys.executable, "-X", "utf8", __file__] + sys.argv[1:]))

from sowscout.config import ROOT, SYSTEMS, Settings
from sowscout.state import RunState


def _settings(a) -> Settings:
    s = Settings()
    for attr, val in (("provider", a.provider), ("model", a.model), ("tool_transport", a.transport),
                      ("system", getattr(a, "system", None))):
        if val:
            setattr(s, attr, val)
    if getattr(a, "reviewer", False):
        s.reviewer = True
    s.allow_cloud = s.allow_cloud or bool(getattr(a, "allow_cloud", False))
    s.use_database = bool(getattr(a, "use_database", False))
    if getattr(a, "max_cost", None) is not None:
        s.limits.max_cost_usd = max(0.0, a.max_cost)
    s.interactive = bool(getattr(a, "interactive", False))
    if getattr(a, "max_steps", None):
        s.limits.max_steps_per_task = a.max_steps
    return s


def _ask(question: str, options: list[str]) -> str | None:
    opts = f" [{'/'.join(options)}]" if options else ""
    try:
        ans = input(f"\n  ? OFFICER INPUT NEEDED: {question}{opts}\n  > ").strip()
    except EOFError:
        return None
    return ans or None


def _evidence(gaps: list[dict]) -> list[Path]:
    print("\n  ? MISSING DOCUMENTS:")
    for g in gaps:
        print(f"    {g['claim_id']}: " + "; ".join(g["missing_evidence"]))
    try:
        ans = input("  Path to a folder or files with new documents (blank = keep gaps)\n  > ").strip()
    except EOFError:
        return []
    out: list[Path] = []
    for part in filter(None, ans.split(",")):
        p = Path(part.strip()).expanduser()
        out += sorted(x for x in p.iterdir() if x.is_file()) if p.is_dir() else ([p] if p.is_file() else [])
    return out


def _case(a) -> tuple[str, str, Path, Path | None]:
    if a.case:
        cdir = ROOT / "data" / "cases" / a.case
        meta = json.loads((cdir / "case.json").read_text())
        return a.client or meta["client"], meta.get("client_ref", ""), cdir / "materials", cdir
    if not (a.client and a.materials):
        sys.exit("provide --case NAME or both --client and --materials")
    return a.client, "", Path(a.materials), None


def seed_memory(settings: Settings, case_dir: Path | None, client: str) -> int:
    from sowscout.memory import seed_case_memory
    return seed_case_memory(settings.db_path, case_dir, client)


def cmd_run(a, demo: bool = False) -> None:
    from sowscout.workflow import Workflow
    if demo:
        a.case = a.case or "wong"
    s = _settings(a)
    client, ref, materials, case_dir = _case(a)
    focus = [f.strip() for f in (a.focus or "").split(",") if f.strip()]
    st = RunState.new(client, str(materials), ref, focus)
    if a.registry:
        st.config["registry_dir"] = str(Path(a.registry).resolve())
    n = seed_memory(s, case_dir, client)
    print(f"[sowscout] run {st.run_id}: {client} · system={s.system} provider={s.provider} model={s.default_model()} "
          f"tools={s.tool_transport}" + (f" · {n} prior verified facts" if n else ""))
    wf = Workflow(s, st, case_dir=case_dir, ask_fn=_ask, echo=not a.quiet,
                  evidence_fn=_evidence if s.interactive else None)
    wf.run()
    _report(wf)


def _report(wf) -> None:
    st = wf.state
    print(f"\n[sowscout] done. Memo: {wf.run_dir / 'memo.md'}")
    print(f"           Trace: {wf.run_dir / 'trace.jsonl'} · Record: {wf.run_dir / 'record.json'}")
    for c in st.claims:
        f = st.findings.get(c.claim_id)
        if f:
            label = "(out of scope)" if f.task_id == "out_of_scope" else f.verdict
            print(f"  {c.claim_id:>4} {c.category:<18} {label:<19} {c.text[:70]}")
    print("  The compliance officer decides next steps; SoWScout does not approve or reject clients.")


def cmd_resume(a) -> None:
    from sowscout.memory import Memory
    from sowscout.workflow import resume
    s = _settings(a)
    rid = a.run_id or Memory(s.db_path).latest_run_id()
    st = resume(s, rid, ask_fn=_ask, echo=not a.quiet)
    print(f"[sowscout] run {st.run_id} phase={st.phase}; memo: {s.runs_dir / st.run_id / 'memo.md'}")


def cmd_remember(a) -> None:
    from sowscout.workflow import remember_findings
    s = _settings(a)
    ids = remember_findings(s, a.run_id, a.officer, [x.strip() for x in a.claims.split(",")] if a.claims else None)
    print(f"[sowscout] {len(ids)} officer-confirmed facts written to client memory: {ids}")


def cmd_tool_check(a) -> None:
    from sowscout.skills import SkillLibrary
    from sowscout.intake import load_materials
    from sowscout.tools import ToolContext, ToolGateway, build_specs
    from sowscout.trace import Tracer
    s = _settings(a)
    cdir = ROOT / "data" / "cases" / a.case if a.case else None
    st = RunState.new("tool-check", "")
    chunks = load_materials(cdir / "materials")[0] if cdir else []
    ctx = ToolContext(registry_dir=cdir / "registry" if cdir else None, policy_dir=s.policy_dir, chunks=chunks,
                      skills=SkillLibrary(s.skills_dir), evidence=st.evidence, timeout_s=s.limits.tool_timeout_s)
    gw = ToolGateway(build_specs(), ctx, st, s.limits, Tracer(None, st.run_id, echo=True), transport=s.tool_transport,
                     mcp_server_args=(["--registry", str(cdir / "registry")] if cdir else []) + ["--policy", str(s.policy_dir)])
    obs = gw.run_batch([{"tool": a.tool, "arguments": json.loads(a.arguments)}])[0]
    gw.close()
    print(json.dumps(obs.for_model(10), indent=2, ensure_ascii=False))


def cmd_probe(a) -> None:
    from sowscout.harness import VerificationHarness
    from sowscout.llm import call_model
    from sowscout.workflow import Workflow
    s = _settings(a)
    client, ref, materials, case_dir = _case(a)
    st = RunState.new(client, str(materials), ref)
    wf = Workflow(s, st, case_dir=case_dir, echo=False)
    wf.intake()
    wf.extract_claims()
    wf.plan()
    task = next((t for t in st.tasks if a.claim in t.claim_ids), None)
    if task is None:
        sys.exit(f"no task for claim {a.claim}; claims: {[c.claim_id + ': ' + c.text[:50] for c in st.claims]}")
    h = VerificationHarness(llm=wf.llm, gateway=wf.gateway, ctx=wf.ctx, skills=wf.skills, state=st, memory=wf.memory,
                            tracer=wf.tracer, settings=s, ask_fn=None, run_deadline=wf.deadline)
    brief, _, _ = h.prepare(task)
    msgs, info = wf.ctx.build(brief, [], h._tail(0, 0, wf.deadline, False, False))
    res = call_model(wf.llm, msgs, state=st, tracer=wf.tracer, settings=s, purpose="probe")
    wf.gateway.close()
    if a.show_context:
        for m in msgs:
            print(f"----- {m['role']} -----\n{m['content']}\n")
    print(f"claim {a.claim}: {st.claim(a.claim).text}\ncontext tokens ~{info['context_tokens']}\n"
          f"----- model output -----\n{res.text}")


def cmd_eval(a) -> None:
    from sowscout.evaluation import run_eval
    s = _settings(a)
    run_eval(s, systems=[x.strip() for x in a.systems.split(",")],
             scenarios=[x.strip() for x in a.scenarios.split(",")] if a.scenarios else None,
             split=a.split, runs=a.runs)


def cmd_ui(a) -> None:
    from sowscout.web.server import serve
    serve(host=a.host, port=a.port, settings=_settings(a), open_browser=a.open)


def cmd_test(_a) -> None:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)


def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--provider", choices=["mock", "ollama", "openai", "router"])
    common.add_argument("--model", help="Model tag or router alias; auto selects a model per call")
    common.add_argument("--allow-cloud", action="store_true", help="Allow routed cloud models to read private client documents")
    common.add_argument("--use-database", action="store_true", help="Enable read-only internal database tools")
    common.add_argument("--max-cost", type=float, help="Maximum estimated routed API spend per run (USD)")
    common.add_argument("--transport", choices=["local", "mcp"], help="tool transport for the mock registries")
    common.add_argument("--system", choices=sorted(SYSTEMS), help="system variant (default C)")
    common.add_argument("--reviewer", action="store_true", help="add the optional independent reviewer")
    common.add_argument("--quiet", action="store_true")
    case = argparse.ArgumentParser(add_help=False)
    case.add_argument("--case", help="folder under data/cases (materials/ + registry/)")
    case.add_argument("--client")
    case.add_argument("--materials", help="folder with the declaration and documents (.md/.txt/.pdf)")
    case.add_argument("--registry", help="folder with companies.json / land_registry.json (mock registries)")

    ap = argparse.ArgumentParser(description="SoWScout — evidence-linked source-of-wealth verification agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "demo"):
        p = sub.add_parser(name, parents=[common, case])
        p.add_argument("--focus", help="themes/categories, e.g. income,property or employment")
        p.add_argument("--interactive", action="store_true",
                       help="ask the officer when the agent needs input, and offer to add missing documents")
        p.add_argument("--max-steps", type=int)
    p = sub.add_parser("resume", parents=[common])
    p.add_argument("run_id", nargs="?")
    p.add_argument("--interactive", action="store_true")
    p = sub.add_parser("remember", parents=[common], help="officer confirms supported findings into client memory")
    p.add_argument("run_id")
    p.add_argument("--officer", required=True, help="officer identifier (recorded with each fact)")
    p.add_argument("--claims", help="comma list of claim ids (default: all supported, gate-verified findings)")
    p = sub.add_parser("tool-check", parents=[common])
    p.add_argument("tool")
    p.add_argument("arguments", help="JSON object")
    p.add_argument("--case")
    p = sub.add_parser("probe", parents=[common, case])
    p.add_argument("--claim", default="C1")
    p.add_argument("--show-context", action="store_true")
    p = sub.add_parser("eval", parents=[common])
    p.add_argument("--systems", default="A,B,C,C-no-calc,C-no-gate")
    p.add_argument("--scenarios", help="comma list of scenario ids; default: all")
    p.add_argument("--split", choices=["dev", "heldout", "all"], default="all")
    p.add_argument("--runs", type=int, default=1, help="runs per case (proposal: 3; mean and range reported)")
    p = sub.add_parser("ui", parents=[common], help="local web interface with the run controller")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8767, help="Preferred port; automatically tries the next free port (0 = OS assigned)")
    p.add_argument("--open", action="store_true")
    sub.add_parser("test")
    a = ap.parse_args()
    {"run": cmd_run, "demo": lambda x: cmd_run(x, demo=True), "resume": cmd_resume, "remember": cmd_remember,
     "tool-check": cmd_tool_check, "probe": cmd_probe, "eval": cmd_eval, "ui": cmd_ui, "test": cmd_test}[a.cmd](a)


if __name__ == "__main__":
    main()
