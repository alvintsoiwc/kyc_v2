"""SoWScout local web server: a JSON API plus a single-page control UI.

Standard library only (http.server). Binds to 127.0.0.1 by default: the UI can
start runs, edit prompts and skills, and hold API keys in memory, so it is a
local tool, not something to expose on a network.

Runs execute in a background thread. The browser polls
  GET /api/runs/<id>          snapshot (record + controller state)
  GET /api/runs/<id>/events   trace events after an index
and drives the run through the RunController:
  POST /api/runs/<id>/control  pause | resume | stop | flags
  POST /api/runs/<id>/respond  answer the pending request (plan review, tool approval, question, step)
  POST /api/runs/<id>/note     reviewer note for the agent
  POST /api/runs/<id>/skip     skip a verification task
  POST /api/runs/<id>/remember officer confirms supported findings into client memory (step 8)
"""

from __future__ import annotations

import base64
import copy
import errno
import socket
import json
import mimetypes
import os
import re
import threading
import time
import traceback
import urllib.parse
from dataclasses import asdict, fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..ask.routes import AskApp
from .. import user_settings
from ..localdb import LocalDB, DatabaseError
from ..config import ROOT, SYSTEMS, Limits, Settings
from ..control import FLAGS, RunController
from ..llm import LLMError, make_llm
from ..memory import seed_case_memory
from ..skills import SkillLibrary
from ..state import CATEGORIES, THEMES, VERDICTS, RunState
from ..tools import ToolContext, ToolGateway, build_specs
from ..trace import Tracer
from ..workflow import Workflow, load_for_resume, remember_findings

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 30 * 1024 * 1024
UPLOAD_EXT = {".md", ".txt", ".pdf"}
DOWNLOADS = {"memo.md", "record.json", "trace.jsonl", "summary.json", "state.json"}
FAULT_RX = re.compile(r"^([a-z_0-9*]+=(timeout|error|transient|permanent|unavailable)(\*\d+)?)(,[a-z_0-9*]+="
                      r"(timeout|error|transient|permanent|unavailable)(\*\d+)?)*$")
MOCK_FAULT_RX = re.compile(r"^((malformed|ungrounded)(:\d+)?)(,(malformed|ungrounded)(:\d+)?)*$")
CONNECTION_ENV = {
    "openai_base_url": "OPENAI_BASE_URL", "openai_api_key": "OPENAI_API_KEY",
    "azure_endpoint": "AZURE_OPENAI_ENDPOINT", "azure_api_key": "AZURE_OPENAI_API_KEY",
    "azure_api_version": "AZURE_OPENAI_API_VERSION", "ollama_host": "OLLAMA_HOST",
    "openrouter_api_key": "OPENROUTER_API_KEY", "deepseek_api_key": "DEEPSEEK_API_KEY",
}
SECRET_KEYS = {"openai_api_key", "azure_api_key", "openrouter_api_key", "deepseek_api_key"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ---------------------------------------------------------------------------- helpers
def list_cases() -> list[dict[str, Any]]:
    out = []
    for cj in sorted((ROOT / "data" / "cases").glob("*/case.json")):
        meta = json.loads(cj.read_text(encoding="utf-8"))
        mats = sorted(p.name for p in (cj.parent / "materials").glob("*") if p.is_file())
        out.append({"case": cj.parent.name, "client": meta.get("client", ""), "client_ref": meta.get("client_ref", ""),
                    "split": meta.get("split", ""), "description": meta.get("description", ""), "materials": mats,
                    "memory": len(meta.get("memory", [])), "has_registry": (cj.parent / "registry").exists()})
    return out


def editable_files() -> list[str]:
    pats = ["prompts/*.md", "skills/*/SKILL.md", "skills/*/references/*.md", "eval/cases.json", "config/models.json"]
    return sorted(p.relative_to(ROOT).as_posix() for pat in pats for p in ROOT.glob(pat))


def _coerce(value: Any, like: Any) -> Any:
    if isinstance(like, bool):
        return bool(value)
    if isinstance(like, int):
        return max(1, int(value))
    if isinstance(like, float):
        return max(0.0, float(value))
    return value


def build_settings(base: Settings, body: dict[str, Any]) -> Settings:
    s = copy.deepcopy(base)
    o = body.get("settings") or {}
    if o.get("provider"):
        if o["provider"] not in ("mock", "ollama", "openai", "router"):
            raise ApiError(400, "provider must be mock, ollama, openai or router")
        s.provider = o["provider"]
    for key in ("allow_cloud", "use_database"):
        if key in o:
            setattr(s, key, bool(o[key]))
    if "model" in o:
        s.model = str(o["model"] or "").strip()
    if o.get("temperature") not in (None, ""):
        s.temperature = min(2.0, max(0.0, float(o["temperature"])))
    if o.get("system"):
        if o["system"] not in SYSTEMS:
            raise ApiError(400, f"system must be one of {sorted(SYSTEMS)}")
        s.system = o["system"]
    if "reviewer" in o:
        s.reviewer = bool(o["reviewer"])
    if o.get("tool_transport"):
        if o["tool_transport"] not in ("local", "mcp"):
            raise ApiError(400, "tool transport must be local or mcp")
        s.tool_transport = o["tool_transport"]
    for k in ("price_in_per_m", "price_out_per_m"):
        if o.get(k) not in (None, ""):
            setattr(s, k, max(0.0, float(o[k])))
    lim = body.get("limits") or {}
    defaults = Limits()
    for f in fields(Limits):
        if f.name in lim and lim[f.name] not in (None, ""):
            try:
                setattr(s.limits, f.name, _coerce(lim[f.name], getattr(defaults, f.name)))
            except (TypeError, ValueError) as exc:
                raise ApiError(400, f"limit {f.name}: {exc}") from exc
    return s


def snapshot(st: RunState, run_dir: Path) -> dict[str, Any]:
    for _ in range(5):        # the run thread mutates the state; retry if a dict changes mid-copy
        try:
            return _snapshot(st, run_dir)
        except RuntimeError:
            time.sleep(0.02)
    return _snapshot(st, run_dir)


def _snapshot(st: RunState, run_dir: Path) -> dict[str, Any]:
    cfg = {k: v for k, v in st.config.items() if k not in ("past_cases",)}
    return {
        "run_id": st.run_id, "client": st.client, "client_ref": st.client_ref, "focus": list(st.focus),
        "phase": st.phase, "started_at": st.started_at, "stop_reason": st.stop_reason,
        "materials_dir": st.materials_dir, "config": cfg,
        "documents": sorted({c.doc for c in st.chunks}), "chunks": len(st.chunks),
        "claims": [{**asdict(c), "sources": [f"{ch.doc}, {ch.location}" for i in c.source_chunk_ids
                                             if (ch := st.chunk(i))]} for c in list(st.claims)],
        "tasks": [asdict(t) for t in list(st.tasks)],
        "findings": {k: asdict(f) for k, f in list(st.findings.items())},
        "evidence": [asdict(e) for e in list(st.evidence.values())],
        "counters": asdict(st.counters), "review_questions": list(st.review_questions),
        "human_answers": list(st.human_answers), "cross_claim_conflicts": list(st.cross_claim_conflicts),
        "timeline": list(st.timeline), "evidence_requests": list(st.evidence_requests),
        "memory_facts": list(st.memory_facts), "pii_masked": st.pii_masked, "evidence_rounds": st.evidence_rounds,
        "has_memo": (run_dir / "memo.md").exists(),
    }


# ---------------------------------------------------------------------------- run handles
class RunHandle:
    def __init__(self, state: RunState, wf: Workflow, ctrl: RunController):
        self.state, self.wf, self.ctrl = state, wf, ctrl
        self.run_id = state.run_id
        self.run_dir = wf.run_dir
        self.status = "starting"
        self.error = ""
        self.started = time.time()
        self.finished: float | None = None
        self.thread: threading.Thread | None = None

    def alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def live_status(self) -> str:
        if self.status in ("done", "stopped", "error"):
            return self.status
        if self.ctrl.pending:
            return "waiting"
        if self.ctrl.paused:
            return "paused"
        return "running"


class App:
    def __init__(self, base: Settings):
        self.base = base
        self.runs: dict[str, RunHandle] = {}
        self.lock = threading.Lock()
        self.eval_job: dict[str, Any] | None = None
        self.ask = AskApp(base)
        self.connection: dict[str, str] = {k: os.environ.get(v, "") for k, v in CONNECTION_ENV.items()}

    # -------------------------------------------------------------- busy state
    def busy(self) -> str:
        if any(h.alive() for h in self.runs.values()):
            return "a run is in progress"
        if self.eval_job and self.eval_job["status"] == "running":
            return "an evaluation is in progress"
        return ""

    # -------------------------------------------------------------- config
    def config(self) -> dict[str, Any]:
        specs = build_specs()
        lim = asdict(Limits())
        active = next((h.run_id for h in self.runs.values() if h.alive()), None)
        return {
            "defaults": {"provider": self.base.provider, "model": self.base.model, "system": self.base.system,
                         "reviewer": self.base.reviewer,
                         "tool_transport": self.base.tool_transport, "temperature": self.base.temperature,
                         "price_in_per_m": self.base.price_in_per_m, "price_out_per_m": self.base.price_out_per_m,
                         "default_models": {p: Settings(provider=p).default_model() for p in ("mock", "ollama", "openai", "router")}},
            "limits": lim, "flags": list(FLAGS), "cases": list_cases(), "themes": THEMES, "categories": CATEGORIES,
            "verdicts": VERDICTS, "skills": SkillLibrary(self.base.skills_dir).names(), "systems": sorted(SYSTEMS),
            "tools": [{"name": s.name, "description": s.description, "input_schema": s.input_schema,
                       "evidence_type": s.evidence_type} for s in specs.values()],
            "connection": self.connection_view(), "active_run": active, "busy": self.busy(),
            "app_root": str(ROOT), "models": [{"alias": m.alias, "label": m.label, "local": m.local, "tier": m.tier} for m in self.ask.router.reg.all()],
            "database": bool(user_settings.load(self.base.runs_dir)["database_path"]), "runs_dir": str(self.base.runs_dir),
        }

    def connection_view(self) -> dict[str, Any]:
        return {k: ({"set": bool(v)} if k in SECRET_KEYS else {"set": bool(v), "value": v})
                for k, v in self.connection.items()}

    def set_connection(self, body: dict[str, Any]) -> dict[str, Any]:
        """Hold endpoints and keys in this process's environment only (never written to disk)."""
        clear = set(body.get("clear") or [])
        for k, env in CONNECTION_ENV.items():
            if k in clear:
                v = ""
            elif k in body:
                v = str(body[k] or "").strip()
                if k in SECRET_KEYS and not v:
                    continue                 # a blank password field keeps the stored key
            else:
                continue
            self.connection[k] = v
            if v:
                os.environ[env] = v
            else:
                os.environ.pop(env, None)
        return self.connection_view()

    def test_connection(self, body: dict[str, Any]) -> dict[str, Any]:
        s = build_settings(self.base, body)
        llm = make_llm(s)
        llm.timeout_s = 30
        t0 = time.perf_counter()
        try:
            r = llm.complete([{"role": "system", "content": "Reply with one JSON object."},
                              {"role": "user", "content": 'Return {"ok": true}.'}])
        except LLMError as exc:
            return {"ok": False, "error": str(exc), "latency_ms": round((time.perf_counter() - t0) * 1000)}
        return {"ok": True, "provider": s.provider, "model": r.model, "text": r.text[:300],
                "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "latency_ms": r.latency_ms}

    # -------------------------------------------------------------- runs
    def start_run(self, body: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if why := self.busy():
                raise ApiError(409, f"Cannot start: {why}. Stop it first or wait for it to finish.")
            s = build_settings(self.base, body)
            case = body.get("case") or ""
            cases = {c["case"]: c for c in list_cases()}
            uploads = body.get("uploads") or []
            focus = [f for f in body.get("focus") or [] if f in THEMES or f in CATEGORIES]
            if case:
                if case not in cases:
                    raise ApiError(400, f"unknown case {case!r}")
                client = (body.get("client") or cases[case]["client"]).strip()
                client_ref = cases[case]["client_ref"]
                case_dir: Path | None = ROOT / "data" / "cases" / case
            else:
                client = (body.get("client") or "").strip()
                client_ref = (body.get("client_ref") or "").strip()
                case_dir = None
                if not client:
                    raise ApiError(400, "Enter the client's name, or pick a demo case.")
                if not uploads:
                    raise ApiError(400, "Add the declaration and supporting documents (.md, .txt or .pdf), "
                                        "or pick a demo case.")
            faults = (body.get("faults") or "").replace(" ", "")
            if faults and not FAULT_RX.match(faults):
                raise ApiError(400, "Tool faults must look like lookup_company=timeout*2,lookup_property=unavailable*1")
            mock_faults = (body.get("mock_faults") or "").replace(" ", "")
            if mock_faults and not MOCK_FAULT_RX.match(mock_faults):
                raise ApiError(400, "Model faults must look like malformed:1,ungrounded:1")
            flags = {k: bool((body.get("control") or {}).get(k, k == "ask_reviewer")) for k in FLAGS}

            st = RunState.new(client, "", client_ref, focus)
            if case_dir is not None:
                st.materials_dir = str(case_dir / "materials")
            else:
                mdir = s.runs_dir / st.run_id / "materials"
                mdir.mkdir(parents=True, exist_ok=True)
                for u in uploads:
                    name = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(str(u.get("name", ""))).name).strip() or "document.txt"
                    if Path(name).suffix.lower() not in UPLOAD_EXT:
                        continue
                    (mdir / name).write_bytes(base64.b64decode(u.get("data_b64", "")))
                if not any(mdir.iterdir()):
                    raise ApiError(400, "None of the uploaded files were .md, .txt or .pdf.")
                st.materials_dir = str(mdir)
            os.environ["SOWSCOUT_MOCK_FAULTS"] = mock_faults
            if case_dir is not None:            # returning-client scenario: load the case's officer-verified facts
                seed_case_memory(s.db_path, case_dir, client)
            ctrl = RunController(**flags)
            st.config["ui"] = {"case": case, "control": flags, "faults": faults, "mock_faults": mock_faults}
            wf = Workflow(s, st, case_dir=case_dir, echo=False, ctrl=ctrl, faults=faults,
                          ask_fn=self._ask_fn(ctrl))
            ctrl.emit = wf.tracer.event
            h = RunHandle(st, wf, ctrl)
            self.runs[st.run_id] = h
            self._launch(h)
            return {"run_id": st.run_id}

    def resume_run(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if why := self.busy():
                raise ApiError(409, f"Cannot resume: {why}.")
            s = copy.deepcopy(self.base)
            try:
                st = load_for_resume(s, run_id)
            except SystemExit as exc:
                raise ApiError(404, str(exc)) from exc
            if st.phase == "done":
                raise ApiError(400, "This run already finished.")
            ui = st.config.get("ui") or {}
            flags = {k: bool((body.get("control") or ui.get("control") or {}).get(k, k == "ask_reviewer"))
                     for k in FLAGS}
            os.environ["SOWSCOUT_MOCK_FAULTS"] = ui.get("mock_faults", "")
            ctrl = RunController(**flags)
            wf = Workflow(s, st, echo=False, ctrl=ctrl, faults=ui.get("faults", ""), ask_fn=self._ask_fn(ctrl))
            ctrl.emit = wf.tracer.event
            h = RunHandle(st, wf, ctrl)
            self.runs[run_id] = h
            self._launch(h)
            return {"run_id": run_id}

    @staticmethod
    def _ask_fn(ctrl: RunController):
        def ask(question: str, options: list[str]) -> str | None:
            resp = ctrl.request("ask_user", {"question": question, "options": options,
                                             "task_id": ctrl.current.get("task_id")}) or {}
            ans = resp.get("answer")
            return ans if isinstance(ans, str) and ans.strip() else None
        return ask

    def _launch(self, h: RunHandle) -> None:
        def target():
            h.status = "running"
            try:
                h.wf.run()
                h.status = "done" if h.state.phase == "done" else ("stopped" if h.state.stop_reason else "done")
            except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
                h.status, h.error = "error", f"{type(exc).__name__}: {exc}"
                h.wf.tracer.event("error", error=h.error, traceback=traceback.format_exc()[-2000:])
                try:
                    h.wf.checkpoint()
                except Exception:  # pragma: no cover
                    pass
            finally:
                h.finished = time.time()
        h.thread = threading.Thread(target=target, daemon=True, name=f"run-{h.run_id}")
        h.thread.start()

    def handle(self, run_id: str) -> RunHandle:
        h = self.runs.get(run_id)
        if h is None:
            raise ApiError(404, f"Run {run_id} is not active in this server; open it from History.")
        return h

    def run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{6}", run_id):
            raise ApiError(400, "bad run id")
        d = self.base.runs_dir / run_id
        if not d.exists():
            raise ApiError(404, f"no run {run_id}")
        return d

    def run_view(self, run_id: str) -> dict[str, Any]:
        h = self.runs.get(run_id)
        if h is not None:
            snap = snapshot(h.state, h.run_dir)
            return {**snap, "status": h.live_status(), "error": h.error, "control": h.ctrl.view(), "active": h.alive(),
                    "elapsed_s": round((h.finished or time.time()) - h.started, 1)}
        d = self.run_dir(run_id)
        src = d / "state.json"
        if not src.exists():
            raise ApiError(404, f"run {run_id} has no saved state")
        st = RunState.from_json(src.read_text(encoding="utf-8"))
        status = "done" if st.phase == "done" else ("stopped" if st.stop_reason else "interrupted")
        return {**snapshot(st, d), "status": status, "error": "", "control": None, "active": False, "elapsed_s": None}

    def events(self, run_id: str, after: int) -> dict[str, Any]:
        d = self.run_dir(run_id)
        path = d / "trace.jsonl"
        if not path.exists():
            return {"events": [], "next": 0}
        lines = path.read_text(encoding="utf-8").splitlines()
        out = []
        for ln in lines[after:after + 500]:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                break
        return {"events": out, "next": after + len(out)}

    def list_runs(self) -> list[dict[str, Any]]:
        rows = []
        if not self.base.runs_dir.exists():
            return rows
        for d in sorted(self.base.runs_dir.iterdir(), reverse=True):
            if not d.is_dir() or d.name.startswith("eval-") or not (d / "state.json").exists():
                continue
            try:
                s = json.loads((d / "state.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            h = self.runs.get(d.name)
            verdicts: dict[str, int] = {}
            for f in s.get("findings", {}).values():
                if f.get("task_id") not in ("out_of_scope", "removed"):
                    verdicts[f["verdict"]] = verdicts.get(f["verdict"], 0) + 1
            status = h.live_status() if h else ("done" if s["phase"] == "done" else
                                                 ("stopped" if s.get("stop_reason") else "interrupted"))
            rows.append({"run_id": d.name, "client": s.get("client"), "client_ref": s.get("client_ref"),
                         "phase": s.get("phase"), "started_at": s.get("started_at"), "status": status,
                         "provider": s.get("config", {}).get("provider"), "model": s.get("config", {}).get("model"),
                         "claims": len(s.get("claims", [])), "verdicts": verdicts,
                         "system": s.get("config", {}).get("system"),
                         "has_memo": (d / "memo.md").exists(), "focus": s.get("focus", [])})
        return rows

    # -------------------------------------------------------------- tools
    def tool_check(self, body: dict[str, Any]) -> dict[str, Any]:
        s = build_settings(self.base, body)
        case = body.get("case") or ""
        cdir = ROOT / "data" / "cases" / case if case else None
        if case and not (cdir and (cdir / "case.json").exists()):
            raise ApiError(400, f"unknown case {case!r}")
        from ..intake import load_materials
        st = RunState.new("tool-check", "")
        chunks = load_materials(cdir / "materials")[0] if cdir else []
        ctx = ToolContext(registry_dir=cdir / "registry" if cdir else None, policy_dir=s.policy_dir, chunks=chunks,
                          skills=SkillLibrary(s.skills_dir), evidence=st.evidence, timeout_s=s.limits.tool_timeout_s)
        tracer = Tracer(None, st.run_id)
        gw = ToolGateway(build_specs(), ctx, st, s.limits, tracer, faults=body.get("faults", ""))
        try:
            args = body.get("arguments")
            if isinstance(args, str):
                args = json.loads(args or "{}")
            obs = gw.run_batch([{"tool": body.get("tool", ""), "arguments": args or {}}])[0]
        except json.JSONDecodeError as exc:
            raise ApiError(400, f"arguments are not valid JSON: {exc}") from exc
        finally:
            gw.close()
        return {"observation": obs.for_model(10), "attempts": obs.attempts, "latency_ms": obs.latency_ms,
                "evidence": [asdict(e) for e in st.evidence.values()]}

    # -------------------------------------------------------------- prompt / skill files
    def read_file(self, rel: str) -> dict[str, Any]:
        if rel not in editable_files():
            raise ApiError(403, "That file is not editable from the UI.")
        p = ROOT / rel
        return {"path": rel, "content": p.read_text(encoding="utf-8"), "modified": time.strftime("%Y-%m-%d %H:%M:%S",
                                                                                 time.localtime(p.stat().st_mtime))}

    def models_view(self, refresh: bool = False) -> dict[str, Any]:
        router = self.ask.router
        reg = router.reg
        info = [reg.refresh_local()]
        info.append(reg.refresh_catalog(force=refresh))
        info += reg.check_direct_providers()
        rows = []
        for m in reg.all():
            ok, why = reg.available(m)
            rows.append({**m.view(), "available": ok, "why": why})
        return {"models": rows, "router": reg.router_cfg, "info": [i for i in info if i],
                "openrouter_key_set": bool(os.environ.get("OPENROUTER_API_KEY")),
                "keys": {name: bool(reg.api_key(name)) for name, p in reg.providers.items() if p.get("key_env")}}

    def test_model(self, alias: str) -> dict[str, Any]:
        router = self.ask.router
        try:
            m = router.reg.get(alias)
            t0 = time.perf_counter()
            res = router.provider(m).complete(m.id, [{"role": "user", "content": 'Reply with the JSON {"ok": true}.'}],
                                              {"type": "object"}, timeout=60, max_tokens=50, think=False if m.thinking else None)
        except (LLMError, KeyError) as exc:
            return {"ok": False, "error": str(exc)}
        cost = res.cost_usd if res.cost_usd is not None else m.cost(res.tokens_in, res.tokens_out)
        return {"ok": True, "model": m.alias, "text": res.text[:200], "latency_ms": round((time.perf_counter() - t0) * 1000),
                "tokens_in": res.tokens_in, "tokens_out": res.tokens_out, "cost_usd": round(cost, 6)}

    def route_preview(self, body: dict[str, Any]) -> dict[str, Any]:
        """Which model would Ask's router pick for this question? (Nothing is answered.)"""
        from ..models.router import Needs
        router = self.ask.router
        needs = Needs(tools=bool(body.get("tools", True)), vision=bool(body.get("images")),
                      private=bool(body.get("private")), allow_cloud=bool(body.get("allow_cloud")),
                      limit=float(body.get("limit") or 0))
        try:
            d = router.for_ask(str(body.get("question") or ""), needs, router.classifier(self.ask.settings.ollama_url()))
        except LLMError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **d.view()}

    def database_view(self) -> dict[str, Any]:
        cfg = user_settings.load(self.base.runs_dir)
        out: dict[str, Any] = {**cfg, "connected": False, "tables": [],
                               "from_env": bool(os.environ.get("SOWSCOUT_DATA_DB"))}
        if cfg["database_path"]:
            try:
                db = LocalDB(cfg["database_path"])
                out["tables"] = db.tables()
                out["connected"], out["name"] = True, db.name
                db.close()
            except DatabaseError as exc:
                out["error"] = str(exc)
        return out

    def set_database(self, body: dict[str, Any]) -> dict[str, Any]:
        path = str(body.get("database_path") or "").strip()
        if path:
            try:
                LocalDB(path).close()
            except DatabaseError as exc:
                raise ApiError(400, str(exc)) from exc
        user_settings.save(self.base.runs_dir, {"database_path": path,
                                                "database_notes": str(body.get("database_notes") or "")[:2000]})
        return self.database_view()

    def write_file(self, body: dict[str, Any]) -> dict[str, Any]:
        rel = body.get("path", "")
        if rel not in editable_files():
            raise ApiError(403, "That file is not editable from the UI.")
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ApiError(400, "Refusing to save an empty file.")
        if rel.endswith(".json"):
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                raise ApiError(400, f"Not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}") from exc
        if rel == "config/models.json":
            from ..models.registry import Registry
            tmp = ROOT / "config" / ".models.check.json"
            tmp.write_text(content)
            try:
                Registry(tmp, self.base.runs_dir)
            except (ValueError, KeyError, TypeError) as exc:
                raise ApiError(400, f"models.json problem: {exc}") from exc
            finally:
                tmp.unlink(missing_ok=True)
        if rel.endswith("SKILL.md") and not content.lstrip().startswith("---"):
            raise ApiError(400, "A SKILL.md must start with front matter (--- name: ... description: ... ---).")
        (ROOT / rel).write_text(content)
        return self.read_file(rel)

    # -------------------------------------------------------------- evaluation
    def start_eval(self, body: dict[str, Any]) -> dict[str, Any]:
        from ..evaluation import run_eval
        with self.lock:
            if why := self.busy():
                raise ApiError(409, f"Cannot start the evaluation: {why}.")
            s = build_settings(self.base, body)
            allowed = ["A", *SYSTEMS]
            systems = [x for x in body.get("systems") or ["A", "B", "C"] if x in allowed]
            scenarios = body.get("scenarios") or None
            split = body.get("split") if body.get("split") in ("dev", "heldout", "all") else "all"
            runs = max(1, min(5, int(body.get("runs") or 1)))
            job: dict[str, Any] = {"status": "running", "rows": [], "error": "", "started": time.time(),
                                   "systems": systems, "scenarios": scenarios, "result_file": ""}
            self.eval_job = job

            def target():
                try:
                    res = run_eval(s, systems=systems, scenarios=scenarios, split=split, runs=runs,
                                   on_row=lambda r: job["rows"].append(r))
                    job["summary"] = res["summary"]
                    job["meta"] = res["meta"]
                    job["result_file"] = f"eval/results/{res['meta']['timestamp']}.md"
                    job["status"] = "done"
                except Exception as exc:  # noqa: BLE001
                    job["status"], job["error"] = "error", f"{type(exc).__name__}: {exc}"
            threading.Thread(target=target, daemon=True, name="eval").start()
            return {"status": "running"}

    def eval_view(self) -> dict[str, Any]:
        past = sorted((ROOT / "eval" / "results").glob("*.json"), reverse=True)[:10]
        spec = json.loads((ROOT / "eval" / "cases.json").read_text(encoding="utf-8"))
        return {"job": self.eval_job, "past": [p.stem for p in past], "systems": ["A", *SYSTEMS],
                "scenarios": [{"id": c["id"], "kind": c.get("kind", ""), "case": c.get("case", c.get("base")),
                               "split": c.get("split", "counterfactual"), "expected": len(c["expected"])}
                              for c in spec["scenarios"] + spec.get("counterfactuals", [])]}

    # -------------------------------------------------------------- step 8: officer confirmation
    def remember(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.run_dir(run_id)
        officer = (body.get("officer") or "").strip()
        if not officer:
            raise ApiError(400, "Enter the officer identifier that confirms these facts.")
        try:
            ids = remember_findings(copy.deepcopy(self.base), run_id, officer, body.get("claim_ids") or None)
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        return {"written": ids}

    def save_uploads(self, run_id: str, uploads: list[dict[str, Any]]) -> list[str]:
        """Documents supplied in answer to a request_evidence gate are staged under the run directory."""
        inbox = self.run_dir(run_id) / "incoming"
        inbox.mkdir(exist_ok=True)
        out = []
        for u in uploads or []:
            name = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(str(u.get("name", ""))).name).strip() or "document.txt"
            if Path(name).suffix.lower() not in UPLOAD_EXT:
                continue
            (inbox / name).write_bytes(base64.b64decode(u.get("data_b64", "")))
            out.append(str(inbox / name))
        return out

    def eval_result(self, stamp: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9]{8}-[0-9]{6}", stamp):
            raise ApiError(400, "bad result id")
        p = ROOT / "eval" / "results" / f"{stamp}.json"
        if not p.exists():
            raise ApiError(404, "no such result")
        return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------- HTTP layer
class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "SoWScoutUI/0.1"

    def log_message(self, fmt, *args):  # keep the terminal readable
        if os.environ.get("SOWSCOUT_UI_LOG"):
            super().log_message(fmt, *args)

    # -- plumbing
    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: Any) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8")

    def _body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ApiError(413, "Request too large (limit 30 MB).")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            obj = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise ApiError(400, f"invalid JSON body: {exc}") from exc
        if not isinstance(obj, dict):
            raise ApiError(400, "JSON body must be an object")
        return obj

    def _host_ok(self) -> bool:
        """When serving this computer only, accept only requests addressed to it (blocks DNS rebinding)."""
        bound = self.server.server_address[0]
        if bound not in ("127.0.0.1", "localhost", "::1"):
            return True
        port = self.server.server_address[1]
        return (self.headers.get("Host") or "").lower() in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    def _same_origin(self) -> None:
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host"):
            raise ApiError(403, "Cross-origin requests are not allowed.")

    def _dispatch(self, method: str) -> None:
        url = urllib.parse.urlparse(self.path)
        path, q = url.path, urllib.parse.parse_qs(url.query)
        try:
            if not self._host_ok():
                raise ApiError(403, "Open the console at http://127.0.0.1:<port>/")
            if method != "GET":
                self._same_origin()
            if self.app.ask.handles(path):
                return self.app.ask.dispatch(self, method, path)
            if not path.startswith("/api/"):
                return self._static(path)
            self._api(method, path, q)
        except (LLMError, ValueError, KeyError) as exc:
            self._json(400, {"error": str(exc)})
        except ApiError as exc:
            self._json(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _static(self, path: str) -> None:
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        p = (STATIC / name).resolve()
        if STATIC.resolve() not in p.parents or not p.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, p.read_bytes(), ctype)

    # -- routes
    def _api(self, method: str, path: str, q: dict[str, list[str]]) -> None:
        app = self.app
        m = re.fullmatch(r"/api/runs/([0-9a-f-]+)(?:/([a-z]+))?(?:/([A-Za-z0-9_.]+))?", path)
        if method == "GET" and path == "/api/config":
            return self._json(200, app.config())
        if path == "/api/connection":
            if method == "POST":
                return self._json(200, app.set_connection(self._body()))
            return self._json(200, app.connection_view())
        if method == "POST" and path == "/api/connection/test":
            return self._json(200, app.test_connection(self._body()))
        if path == "/api/runs":
            if method == "POST":
                return self._json(201, app.start_run(self._body()))
            return self._json(200, {"runs": app.list_runs()})
        if m:
            rid, action, arg = m.group(1), m.group(2), m.group(3)
            if method == "GET" and action is None:
                return self._json(200, app.run_view(rid))
            if method == "GET" and action == "events":
                return self._json(200, app.events(rid, int((q.get("after") or ["0"])[0])))
            if method == "GET" and action == "memo":
                p = app.run_dir(rid) / "memo.md"
                if not p.exists():
                    raise ApiError(404, "The memo is written in the last phase; it is not ready yet.")
                return self._json(200, {"markdown": p.read_text(encoding="utf-8")})
            if method == "GET" and action == "download" and arg in DOWNLOADS:
                p = app.run_dir(rid) / arg
                if not p.exists():
                    raise ApiError(404, f"{arg} does not exist for this run yet")
                ctype = "text/markdown" if arg.endswith(".md") else "application/json"
                return self._send(200, p.read_bytes(), ctype + "; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="{rid}-{arg}"'})
            if method == "POST" and action == "control":
                b = self._body()
                h = app.handle(rid)
                act = b.get("action")
                if act == "pause":
                    h.ctrl.pause()
                elif act == "resume":
                    h.ctrl.resume()
                elif act == "stop":
                    h.ctrl.stop()
                elif act == "flags":
                    h.ctrl.set_flags(**(b.get("flags") or {}))
                else:
                    raise ApiError(400, "action must be pause, resume, stop or flags")
                return self._json(200, h.ctrl.view())
            if method == "POST" and action == "respond":
                b = self._body()
                h = app.handle(rid)
                resp = b.get("response")
                if h.ctrl.pending and h.ctrl.pending.kind == "request_evidence" and isinstance(resp, dict):
                    resp = {"files": app.save_uploads(rid, resp.get("uploads") or [])}
                if not h.ctrl.respond(b.get("request_id", ""), resp):
                    raise ApiError(409, "That request was already answered or has expired.")
                return self._json(200, h.ctrl.view())
            if method == "POST" and action == "note":
                b = self._body()
                text = (b.get("text") or "").strip()
                if not text:
                    raise ApiError(400, "Write a note first.")
                h = app.handle(rid)
                h.ctrl.add_note(text[:2000], b.get("task_id") or None)
                return self._json(200, h.ctrl.view())
            if method == "POST" and action == "skip":
                b = self._body()
                h = app.handle(rid)
                h.ctrl.skip(b.get("task_id", ""))
                return self._json(200, h.ctrl.view())
            if method == "POST" and action == "resume":
                return self._json(200, app.resume_run(rid, self._body()))
            if method == "POST" and action == "remember":
                return self._json(200, app.remember(rid, self._body()))
        if method == "GET" and path == "/api/models":
            return self._json(200, app.models_view(refresh=bool(q.get("refresh"))))
        if method == "POST" and path == "/api/models/test":
            return self._json(200, app.test_model(str(self._body().get("model") or "")))
        if method == "POST" and path == "/api/models/route":
            return self._json(200, app.route_preview(self._body()))
        if path == "/api/database":
            if method == "POST":
                return self._json(200, app.set_database(self._body()))
            return self._json(200, app.database_view())
        if method == "POST" and path == "/api/tool-check":
            return self._json(200, app.tool_check(self._body()))
        if method == "GET" and path == "/api/files":
            return self._json(200, {"files": editable_files()})
        if path == "/api/file":
            if method == "PUT":
                return self._json(200, app.write_file(self._body()))
            return self._json(200, app.read_file((q.get("path") or [""])[0]))
        if path == "/api/eval":
            if method == "POST":
                return self._json(202, app.start_eval(self._body()))
            return self._json(200, app.eval_view())
        em = re.fullmatch(r"/api/eval/([0-9-]+)", path)
        if method == "GET" and em:
            return self._json(200, app.eval_result(em.group(1)))
        raise ApiError(404, f"no route {method} {path}")


class ScoutHTTPServer(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR can permit two listeners on the same port.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(host: str = "127.0.0.1", port: int = 8767, settings: Settings | None = None) -> ThreadingHTTPServer:
    app = App(settings or Settings())
    handler = type("BoundHandler", (Handler,), {"app": app})
    srv = ScoutHTTPServer((host, port), handler)
    srv.daemon_threads = True
    srv.app = app  # type: ignore[attr-defined]
    return srv


def make_available_server(host: str = "127.0.0.1", port: int = 8767,
                          settings: Settings | None = None, attempts: int = 30) -> ThreadingHTTPServer:
    """Reserve a listening socket before announcing its port; retry only bind conflicts."""
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    candidates = [0] if port == 0 else range(port, min(port + attempts, 65536))
    for candidate in candidates:
        try:
            srv = make_server(host, candidate, settings)
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE, 48, 98, 10048) and getattr(exc, "winerror", None) not in (10048, 10013):
                raise
            print(f"[sowscout] port {candidate} is unavailable; trying the next port", flush=True)
            continue
        return srv
    raise OSError(errno.EADDRINUSE, f"No free port near {port}; try python run.py ui --port 0")


def serve(host: str = "127.0.0.1", port: int = 8767, settings: Settings | None = None, open_browser: bool = False):
    srv = make_available_server(host, port, settings)
    url = f"http://{host}:{srv.server_address[1]}/"
    print(f"[sowscout] web interface running at {url}  (Ctrl-C to stop)", flush=True)
    if host not in ("127.0.0.1", "localhost"):
        print("[sowscout] WARNING: listening beyond localhost. Anyone who can reach this port can start runs "
              "and edit prompts. Use only on a trusted network.")
    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[sowscout] web interface stopped")
    finally:
        srv.server_close()
