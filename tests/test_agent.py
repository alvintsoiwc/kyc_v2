"""Agent behaviour with the mock model: workflow, statuses, gate, evidence loop, memory, recovery."""

import json
import unittest
from pathlib import Path

from sowscout.config import Limits
from sowscout.context import ContextBuilder, observation_message
from sowscout.memory import Memory
from sowscout.state import Claim, Evidence, Finding, VerificationTask
from sowscout.verify import check_finding, completion_gate, verify_assessments
from sowscout.workflow import Workflow, remember_findings, resume

from .helpers import CASES, case_copy, env, new_state, seed, temp_settings

EXPECTED = {   # gold statuses for the six synthetic cases (eval/cases.json)
    "chan": {"Harbourview": "supported", "Pearl Delta": "unresolved", "Lime Grove": "supported",
             "Kingsford Court": "supported"},
    "wong": {"per month": "supported", "bonus": "supported", "Harbour Crest": "potential_red_flag"},
    "lee": {"Golden Crane": "potential_red_flag", "Eastwind": "supported", "Wing Fat": "supported"},
    "ho": {"May 2022": "potential_red_flag", "Seaview": "unresolved", "Mei Advisory": "unresolved",
           "in 2021": "potential_red_flag"},
    "ng": {"Kowloon Bay": "supported", "gave me": "unresolved", "Sunshine City": "unresolved"},
    "cheung": {"Tai Ping": "supported", "purchased": "supported", "sold": "supported"},
}


def find(st, needle):
    c = next(c for c in st.claims if needle.lower() in c.text.lower())
    return c, st.findings[c.claim_id]


def run_case(case, **over):
    s = temp_settings(**over)
    st, cdir = new_state(case)
    seed(s, cdir)
    wf = Workflow(s, st, case_dir=cdir, echo=False)
    wf.run()
    return s, st, wf


class TestWorkflow(unittest.TestCase):
    def test_all_cases_match_gold_statuses(self):
        for case, exp in EXPECTED.items():
            with self.subTest(case=case):
                _, st, _ = run_case(case)
                self.assertEqual(st.phase, "done")
                self.assertEqual(len(st.claims), len(exp))
                for needle, status in exp.items():
                    self.assertEqual(find(st, needle)[1].verdict, status, needle)

    def test_memo_traceability_and_safety(self):
        _, st, wf = run_case("wong")
        for f in st.findings.values():          # every cited id exists and has a location
            self.assertTrue(all(e in st.evidence and st.evidence[e].location for e in f.evidence_ids))
            self.assertTrue(f.verified)
        self.assertTrue(all(c.source_chunk_ids and st.chunk(c.source_chunk_ids[0]) for c in st.claims))
        _, rf = find(st, "Harbour Crest")
        self.assertEqual(rf.numbers["funding_gap_hkd"], 1669000)
        self.assertTrue(any("KAIWING" in x for x in rf.conflicts))
        memo = (wf.run_dir / "memo.md").read_text()
        for text in ("SYNTHETIC DATA", "cannot approve or reject", "Wealth timeline", "1,669,000", "Officer decision"):
            self.assertIn(text, memo)
        self.assertNotIn("Y765432", memo)                         # HKID masked at intake
        self.assertNotIn("024-998877-310", (wf.run_dir / "record.json").read_text())
        self.assertTrue((wf.run_dir / "packet" / "01_declaration.md").exists())   # audit snapshot

    def test_focus_limits_verification(self):
        s = temp_settings()
        st, cdir = new_state("wong", focus=["property"])
        Workflow(s, st, case_dir=cdir, echo=False).run()
        self.assertEqual({st.claim(c).category for t in st.tasks for c in t.claim_ids}, {"property_purchase"})
        self.assertEqual(find(st, "bonus")[1].task_id, "out_of_scope")

    def test_cross_claim_conflict_detected(self):
        _, st, _ = run_case("ho")
        self.assertEqual(len(st.cross_claim_conflicts), 1)
        self.assertTrue(any(q["source"] == "cross-claim check" for q in st.review_questions))

    def test_system_b_has_no_playbooks_and_no_gate(self):
        _, st, wf = run_case("lee", system="B")
        self.assertTrue(all(t.skill == "out-of-scope" or t.question.startswith("Which documents") for t in st.tasks))
        self.assertFalse(any(e["kind"] == "verify" for e in wf.tracer.events))
        self.assertTrue(all(not f.verified for f in st.findings.values()))
        self.assertIn("GATE DISABLED", (wf.run_dir / "memo.md").read_text())

    def test_no_calculator_ablation_removes_tools_and_gate_rejects_uncomputed_numbers(self):
        _, st, wf = run_case("wong", system="C-no-calc")
        self.assertNotIn("calc_wealth_timeline", wf.specs)
        self.assertFalse(any(e.evidence_type == "calculation" for e in st.evidence.values()))
        # the funding gap computed "in the head" cannot be cited, so the gate does not publish it as a red flag
        self.assertEqual(find(st, "Harbour Crest")[1].verdict, "unresolved")

    def test_independent_reviewer(self):
        _, st, wf = run_case("lee", reviewer=True)
        reviewed = [f for f in st.findings.values() if f.review]
        self.assertTrue(reviewed and all(f.review["supports"] for f in reviewed))
        self.assertIn("Independent reviewer", (wf.run_dir / "memo.md").read_text())

    def test_format_repair_and_gate_revision(self):
        s = temp_settings()
        st, cdir = new_state("wong")
        with env(SOWSCOUT_MOCK_FAULTS="malformed:1,ungrounded:1"):
            Workflow(s, st, case_dir=cdir, echo=False).run()
        self.assertEqual(st.counters.format_repairs, 1)
        self.assertEqual(st.counters.verify_rejections, 1)
        self.assertEqual(find(st, "Harbour Crest")[1].verdict, "potential_red_flag")   # recovered

    def test_registry_unavailable_gives_honest_gaps(self):
        s = temp_settings()
        s.limits.retry_base_delay_s = 0.01
        st, cdir = new_state("lee")
        with env(SOWSCOUT_FAULTS="lookup_company=unavailable*20,lookup_property=timeout*20"):
            Workflow(s, st, case_dir=cdir, echo=False).run()
        self.assertEqual(find(st, "Eastwind")[1].verdict, "unresolved")       # registry needed, not guessed
        self.assertEqual(find(st, "Wing Fat")[1].verdict, "unresolved")
        self.assertEqual(find(st, "Golden Crane")[1].verdict, "potential_red_flag")   # tax mismatch needs no registry
        self.assertGreater(st.counters.tool_errors, 0)

    def test_step_budget_handoff(self):
        _, st, _ = run_case("wong", limits=Limits(max_steps_per_task=1))
        self.assertTrue(all(t.status == "unresolved" and "step budget" in t.stop_reason for t in st.tasks))
        self.assertTrue(all(f.verdict == "unresolved" for f in st.findings.values()))

    def test_resume_from_checkpoint(self):
        s = temp_settings()
        st, cdir = new_state("chan")
        wf = Workflow(s, st, case_dir=cdir, echo=False)
        for node in ("intake", "extract_claims", "plan"):   # simulate a crash after planning
            getattr(wf, node)()
        st.phase = "verify"
        wf.checkpoint()
        wf.gateway.close()
        done = resume(s, st.run_id, echo=False)
        self.assertEqual(done.phase, "done")
        self.assertEqual(len(done.findings), len(done.claims))

    def test_missing_documents_loop_back_to_planner(self):
        extra = Path(__file__).resolve().parent / "fixtures"
        s = temp_settings()
        st, cdir = new_state("chan")
        calls = []

        def supply(gaps):
            calls.append(gaps)
            return [extra / "09_reference_letter_pearl_delta.md"]

        Workflow(s, st, case_dir=cdir, echo=False, evidence_fn=supply).run()
        self.assertEqual(len(calls), 1)                      # bounded: one extra round
        self.assertEqual(st.evidence_rounds, 2)
        self.assertEqual(find(st, "Pearl Delta")[1].verdict, "supported")
        self.assertTrue(any(t.round == 2 for t in st.tasks))

    def test_human_confirmed_name_variant_becomes_memory(self):
        cdir = case_copy("ng", {"02_payslip_2025-11.md": ("Kowloon Bay Medical Centre Ltd (九龍灣醫療中心有限公司)",
                                                          "Kowloon Bay Clinic Ltd")})
        s = temp_settings(interactive=True)
        st, _ = new_state(case_dir=cdir)
        Workflow(s, st, case_dir=cdir, ask_fn=lambda q, o: "yes", echo=False).run()
        self.assertEqual(find(st, "Kowloon Bay")[1].verdict, "supported")
        self.assertIn({"entity": "Kowloon Bay Medical Centre Limited", "variant": "Kowloon Bay Clinic Ltd"},
                      Memory(s.db_path).name_variants("Ng Siu Fung"))
        st2, _ = new_state(case_dir=cdir)                   # without a human, the doubt stays unresolved
        Workflow(temp_settings(), st2, case_dir=cdir, echo=False).run()
        self.assertEqual(find(st2, "Kowloon Bay")[1].verdict, "unresolved")

    def test_officer_confirmed_findings_become_client_memory(self):
        s, st, _ = run_case("chan")
        with self.assertRaises(ValueError):
            remember_findings(s, st.run_id, "")
        ids = remember_findings(s, st.run_id, "officer:TEST")
        self.assertEqual(len(ids), 3)                       # the three supported findings
        facts = Memory(s.db_path).client_facts("Chan Tai Man")
        self.assertTrue(all(f["confirmed_by"] == "officer:TEST" for f in facts))
        st2, cdir = new_state("chan")                       # returning client: memory is read at intake
        Workflow(s, st2, case_dir=cdir, echo=False).run()
        self.assertEqual(len(st2.memory_facts), 3)
        _, f = find(st2, "Lime Grove")
        self.assertTrue(any(st2.evidence[e].evidence_type == "memory" for e in f.evidence_ids))


class TestGate(unittest.TestCase):
    def setUp(self):
        st, _ = new_state()
        st.claims = [Claim("C1", "I earn HKD 85,000 per month at Acme Limited.", "employment", ["D1#1"],
                           entity="Acme Limited", amount=85000, currency="HKD")]
        st.evidence = {
            "E1": Evidence("E1", "declaration", "Client declaration", "decl#1", "decl, line 1", "", {}, "declaration"),
            "E2": Evidence("E2", "search_documents", "Client document", "payslip#1", "payslip, line 3", "",
                           {"fields": {"gross pay": "HKD 85,000"}}, "document"),
            "E3": Evidence("E3", "check_consistency", "Consistency checker", "consistency:1", "calc", "",
                           {"all_consistent": True, "checks": [{"claimed_hkd": 85000, "documented_hkd": 85000}]},
                           "calculation"),
            "E4": Evidence("E4", "check_consistency", "Consistency checker", "consistency:2", "calc", "",
                           {"all_consistent": False}, "calculation"),
        }
        self.st = st
        self.task = VerificationTask("T1", ["C1"], "q", "employment-income")

    def check(self, **a):
        base = {"claim_id": "C1", "verdict": "supported", "evidence_ids": ["E2", "E3"], "rationale": "x" * 12}
        return verify_assessments([{**base, **a}], self.st, self.task, {"E1", "E2", "E3", "E4"})

    def test_valid_supported_finding_passes(self):
        self.assertEqual(self.check(numbers={"documented_hkd": 85000}), [])

    def test_declaration_is_not_support(self):
        self.assertTrue(any("declaration is not support" in p for p in self.check(evidence_ids=["E1", "E3"])))

    def test_numeric_claim_needs_a_consistent_calculation(self):
        self.assertTrue(any("cite a check_consistency" in p for p in self.check(evidence_ids=["E2"])))
        self.assertTrue(any("does not reconcile" in p for p in self.check(evidence_ids=["E2", "E4"])))

    def test_numbers_must_come_from_cited_evidence(self):
        self.assertTrue(any("does not appear" in p for p in self.check(numbers={"funding_gap_hkd": 123456})))

    def test_status_preconditions_and_unknown_ids(self):
        self.assertTrue(any("unknown" in p for p in self.check(evidence_ids=["E9"])))
        self.assertTrue(any("must state the conflict" in p for p in self.check(verdict="potential_red_flag")))
        self.assertTrue(any("missing evidence" in p for p in self.check(verdict="unresolved")))
        self.assertTrue(any("not retrieved" in p for p in verify_assessments(
            [{"claim_id": "C1", "verdict": "supported", "evidence_ids": ["E2", "E3"], "rationale": "x" * 12}],
            self.st, self.task, {"E1"})))

    def test_no_approval_or_misconduct_language(self):
        for text in ("We recommend approving the client.", "The client should be rejected for onboarding.",
                     "Money laundering is confirmed."):
            self.assertTrue(any("must not approve" in p for p in self.check(rationale=text)), text)

    def test_final_gate_downgrades(self):
        self.st.findings = {"C1": Finding("C1", "supported", ["E1"], "only the declaration", task_id="T1")}
        report = completion_gate(self.st)
        self.assertFalse(report[0]["ok"])
        self.assertEqual(self.st.findings["C1"].verdict, "unresolved")
        self.assertEqual(self.st.counters.gate_downgrades, 1)
        self.assertEqual(check_finding(vars(self.st.findings["C1"]), self.st), [])   # the downgraded finding is valid


class TestContext(unittest.TestCase):
    def test_stable_prefix_and_compression_keep_evidence_ids(self):
        ctx = ContextBuilder("SYSTEM RULES", Limits(context_window=1200, reserved_output=200))
        big = [{"call_id": f"c{i}", "tool": "search_documents", "arguments": {}, "ok": True, "total": 1,
                "records": [{"evidence_id": f"E{i}", "text": "x" * 2500}]} for i in range(3)]
        hist = [observation_message([o]) for o in big]
        msgs, info = ctx.build("TASK BRIEF", hist, "WORKING_STATE: {}")
        self.assertEqual(msgs[0]["content"], "SYSTEM RULES")
        self.assertTrue(msgs[-1]["content"].endswith("WORKING_STATE: {}"))
        self.assertGreaterEqual(info["compressed_observations"], 1)
        self.assertIn('"E0"', msgs[2]["content"])
        self.assertIn("get_evidence", msgs[2]["content"])


class TestEvaluation(unittest.TestCase):
    def test_eval_scores_and_counterfactuals(self):
        from sowscout.evaluation import run_eval
        s = temp_settings()
        res = run_eval(s, systems=["A", "C"], scenarios=["wong", "cf_ng_salary_conflict"], out_dir=s.runs_dir / "eval")
        by = {(r["scenario"], r["system"]): r for r in res["rows"] + res["counterfactuals"]}
        self.assertEqual(by[("wong", "C")]["joint_correctness"], 1.0)
        self.assertEqual(by[("wong", "C")]["elvs"], 100.0)
        self.assertEqual(by[("wong", "C")]["status_accuracy"], 1.0)
        self.assertEqual(by[("wong", "C")]["evidence_accuracy"], 1.0)
        self.assertEqual(by[("wong", "C")]["arithmetic_accuracy"], 1.0)
        self.assertEqual(by[("wong", "C")]["arithmetic_errors"], 0)
        self.assertEqual(by[("wong", "A")]["red_flag_recall"], 0.0)       # naive baseline misses the gap
        self.assertEqual(by[("cf_ng_salary_conflict", "C")]["expected_behaviour_rate"], 1.0)
        self.assertEqual(by[("cf_ng_salary_conflict", "C")]["ccr"], 100.0)
        self.assertEqual(by[("cf_ng_salary_conflict", "C")]["ccr_count"], "1/1")
        self.assertEqual(by[("cf_ng_salary_conflict", "A")]["ccr"], 0.0)
        self.assertEqual(by[("cf_ng_salary_conflict", "A")]["ccr_count"], "0/1")
        self.assertTrue(list((s.runs_dir / "eval").glob("*.md")))

    def test_score_counts_link_and_numbers(self):
        from sowscout.evaluation import score
        exp = [{"match": ["gap"], "status": "potential_red_flag", "evidence": ["timeline:"],
                "values": {"funding_gap_hkd": 100000}}]
        ev = {"E1": {"identifier": "timeline:abc", "evidence_type": "calculation"}}
        good = [{"claim_text": "gap claim", "verdict": "potential_red_flag", "evidence_ids": ["E1"],
                 "numbers": {"funding_gap_hkd": 100500}}]
        wrong_num = [{**good[0], "numbers": {"funding_gap_hkd": 150000}}]
        s_good = score(good, ev, exp)
        self.assertEqual((s_good["joint_correctness"], s_good["elvs"]), (1.0, 100.0))
        r = score(wrong_num, ev, exp)
        self.assertEqual((r["joint_correctness"], r["elvs"], r["arithmetic_errors"], r["funding_gap_abs_error"]),
                         (0.0, 0.0, 1, 50000))
        self.assertEqual((r["status_accuracy"], r["evidence_accuracy"], r["arithmetic_accuracy"]), (1.0, 1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
