"""MCP transport: discovery via tools/list and invocation via tools/call (skipped without fastmcp)."""

import importlib.util
import unittest

from sowscout.workflow import Workflow

from .helpers import new_state, temp_settings


@unittest.skipUnless(importlib.util.find_spec("fastmcp"), "fastmcp not installed")
class TestMCPTransport(unittest.TestCase):
    def test_workflow_over_mcp(self):
        s = temp_settings(tool_transport="mcp")
        st, cdir = new_state("lee")
        wf = Workflow(s, st, case_dir=cdir, echo=False)
        self.assertEqual(wf.gateway.mcp_tools, {"lookup_company", "lookup_property", "search_policy"})
        wf.run()
        mcp_calls = [e for e in wf.tracer.events if e["kind"] == "tool_call" and e["transport"] == "mcp"]
        self.assertTrue(mcp_calls and all(e["ok"] for e in mcp_calls))
        c = next(c for c in st.claims if "Golden Crane" in c.text)
        self.assertEqual(st.findings[c.claim_id].verdict, "potential_red_flag")


if __name__ == "__main__":
    unittest.main()
