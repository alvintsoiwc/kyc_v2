"""Read-only SoW policy, synthetic case registries and calculators for Ask."""
from __future__ import annotations
import json
from typing import Any
from ..config import ROOT
from ..state import RunState
from ..tools import ToolContext, ToolGateway, build_specs
from ..trace import Tracer

ASK_TOOLS = {"lookup_company", "lookup_property", "search_policy", "calc_wealth_timeline", "check_consistency"}

def demo_cases():
    return sorted(p.parent.name for p in (ROOT / "data/cases").glob("*/registry"))

class SoWTools:
    def __init__(self, base):
        self.base = base
        self.specs = {k: v for k, v in build_specs().items() if k in ASK_TOOLS}

    @property
    def names(self):
        return set(self.specs)

    def tool_defs(self):
        return [{"type": "function", "function": {"name": s.name, "description": s.description,
                 "parameters": s.input_schema}} for s in self.specs.values()]

    def label(self, name, args):
        return name.replace("_", " ").capitalize()

    def run(self, name: str, args: dict[str, Any], backend: str, add_source):
        if backend != "policy" and backend not in demo_cases():
            return "Tool error: unknown demo case", [], "Unknown demo case"
        registry = ROOT / "data/cases" / backend / "registry" if backend != "policy" else None
        state = RunState.new("ask", "")
        ctx = ToolContext(registry_dir=registry, policy_dir=self.base.policy_dir, evidence=state.evidence,
                          timeout_s=self.base.limits.tool_timeout_s)
        gw = ToolGateway(self.specs, ctx, state, self.base.limits, Tracer(None, state.run_id), faults="")
        try:
            obs = gw.run_batch([{"tool": name, "arguments": args}])[0]
        finally:
            gw.close()
        if not obs.ok:
            return "Tool error (%s): %s" % (obs.error_kind, obs.error), [], obs.error
        data = obs.data or {}
        lines, results = [], []
        if data.get("synthetic") or name in {"lookup_company", "lookup_property"}:
            lines.append("SYNTHETIC demo registry records; not live official registry evidence.")
        if name == "search_policy":
            lines.append("Bundled, versioned policy guidance; not current legal advice or client evidence.")
        if data.get("note"):
            lines.append(str(data["note"]))
        for record in data.get("records", [])[:6]:
            title = self.specs[name].source_label + ": " + str(record.get(self.specs[name].record_id_field, name))
            n = add_source(title, "sow://%s/%s/%s" % (backend, name, len(results)), "")
            lines.append("[%d] %s" % (n, json.dumps(record, ensure_ascii=False)))
            results.append({"n": n, "title": title, "url": "", "snippet": ""})
        if not results:
            lines.append("No matching records; absence is not proof that the claim is false.")
        return "\n".join(lines), results, None
