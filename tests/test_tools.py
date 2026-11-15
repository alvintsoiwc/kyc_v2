"""Tools through the real gateway: contracts, registries, calculator, retrieval, PII masking, faults."""

import unittest

from sowscout.config import Limits, Settings
from sowscout.intake import load_materials, mask_pii
from sowscout.skills import SkillLibrary
from sowscout.state import RunState
from sowscout.tools import ToolContext, ToolGateway, build_specs
from sowscout.tools.calc import calc_wealth_timeline, check_consistency
from sowscout.tools.gateway import parse_faults
from sowscout.tools.text import norm_name, parse_amount, parse_date, tfidf_rank
from sowscout.trace import Tracer

from .helpers import CASES


def gateway(case="wong", faults=""):
    s = Settings()
    st = RunState.new("t", "")
    chunks = load_materials(CASES / case / "materials")[0]
    ctx = ToolContext(registry_dir=CASES / case / "registry", policy_dir=s.policy_dir, chunks=chunks,
                      evidence=st.evidence, skills=SkillLibrary(s.skills_dir))
    lim = Limits(retry_base_delay_s=0.01)
    return ToolGateway(build_specs(), ctx, st, lim, Tracer(None, st.run_id), faults=faults), st


class TestGatewayTools(unittest.TestCase):
    def setUp(self):
        self.gw, self.st = gateway()

    def tearDown(self):
        self.gw.close()

    def one(self, tool, **args):
        return self.gw.run_batch([{"tool": tool, "arguments": args}])[0]

    def test_company_registry(self):
        o = self.one("lookup_company", name="Silverline Digital Ltd")
        self.assertTrue(o.ok)
        rec = o.data["records"][0]
        self.assertEqual((rec["cr_number"], rec["match"]), ("2581144", "exact"))
        self.assertEqual(self.st.evidence[o.evidence_ids[0]].evidence_type, "registry")
        self.assertTrue(self.one("lookup_company", name="银线").ok)            # no match is not an error
        self.assertEqual(self.one("lookup_company", name="Nonexistent Widgets Limited").data["total"], 0)

    def test_land_registry_and_document_search(self):
        o = self.one("lookup_property", address="Flat 8C, Harbour Crest, Tseung Kwan O")
        self.assertEqual(o.data["records"][0]["property_ref"], "PR-TKO-HC-8C")
        d = self.one("search_documents", query="Silverline payslip", doc_type="payslip")
        self.assertTrue(d.ok and d.data["records"][0]["fields"]["employer"] == "Silverline Digital Limited")
        self.assertEqual(self.st.evidence[d.evidence_ids[0]].identifier, "02_payslip_2023-03.md#1")
        self.assertTrue(self.st.evidence[d.evidence_ids[0]].location.startswith("02_payslip_2023-03.md, section"))

    def test_declaration_is_never_returned_as_evidence(self):
        d = self.one("search_documents", query="Harbour Crest purchased mortgage savings")
        self.assertTrue(all(r["doc_type"] != "declaration" for r in d.data["records"]))
        p = self.one("parse_document", doc="01_declaration.md")
        self.assertEqual(p.error_kind, "permanent")

    def test_parse_document_gives_numeric_bank_rows(self):
        p = self.one("parse_document", doc="04_bank_statement_2023-09.md")
        rows = p.data["records"][0]["rows"]
        tt = next(r for r in rows if "KAIWING" in r["description"])
        self.assertEqual(tt["credit_value"], 1800000.0)

    def test_policy_retrieval(self):
        o = self.one("search_policy", query="gift from a third party")
        self.assertTrue(o.ok)
        self.assertIn("Third-party", o.data["records"][0]["title"])
        self.assertEqual(self.st.evidence[o.evidence_ids[0]].evidence_type, "policy")

    def test_input_schema_rejects_bad_arguments(self):
        o = self.one("lookup_company", cr_number="ABC")
        self.assertEqual(o.error_kind, "permanent")
        o = self.one("check_consistency", checks=[{"kind": "vibes", "claimed": 1, "documented": 2}])
        self.assertEqual(o.error_kind, "permanent")

    def test_transient_fault_retries_then_succeeds(self):
        gw, _ = gateway(faults="lookup_company=timeout*1")
        o = gw.run_batch([{"tool": "lookup_company", "arguments": {"name": "Silverline Digital Limited"}}])[0]
        gw.close()
        self.assertTrue(o.ok)
        self.assertEqual(o.attempts, 2)

    def test_unavailable_is_not_retried(self):
        gw, _ = gateway(faults="lookup_property=unavailable*5")
        o = gw.run_batch([{"tool": "lookup_property", "arguments": {"address": "x"}}])[0]
        gw.close()
        self.assertEqual((o.ok, o.error_kind, o.attempts), (False, "unavailable", 1))

    def test_parallel_batch_keeps_call_ids(self):
        obs = self.gw.run_batch([{"tool": "lookup_company", "arguments": {"name": "Silverline Digital Limited"}},
                                 {"tool": "lookup_property", "arguments": {"address": "Harbour Crest Tseung Kwan O"}}])
        self.assertEqual(len({o.call_id for o in obs}), 2)
        self.assertEqual([o.tool for o in obs], ["lookup_company", "lookup_property"])

    def test_same_record_gets_one_evidence_id(self):
        a = self.one("lookup_company", name="Silverline Digital Limited")
        b = self.one("lookup_company", cr_number="2581144")
        self.assertEqual(a.evidence_ids, b.evidence_ids)

    def test_ablation_removes_calculator_tools(self):
        self.assertNotIn("check_consistency", build_specs(calculator=False))
        self.assertIn("check_consistency", build_specs())


class TestCalculator(unittest.TestCase):
    def test_amount_tolerance_multiplier_and_fx(self):
        r = check_consistency(None, [
            {"label": "a", "kind": "amount", "claimed": 85000, "documented": 83500},
            {"label": "b", "kind": "amount", "claimed": 150000, "multiplier": 12, "documented": 720000},
            {"label": "c", "kind": "amount", "claimed": 10000, "currency": "USD", "documented": 78000,
             "documented_currency": "HKD"}])["records"][0]
        a, b, c = r["checks"]
        self.assertTrue(a["consistent"])                      # 1.8% < 5%
        self.assertFalse(b["consistent"])
        self.assertEqual(b["claimed_hkd"], 1800000)
        self.assertTrue(c["consistent"])                      # USD 10,000 at the fixed 7.80 rate
        self.assertEqual(r["inconsistent"], ["b"])

    def test_dates_and_names(self):
        r = check_consistency(None, [
            {"label": "d1", "kind": "date", "claimed": "2018-03", "documented": "1 March 2018"},
            {"label": "d2", "kind": "date_order", "claimed": "2020-04", "documented": "2021-08-02"},
            {"label": "n1", "kind": "name", "claimed": "Chan Tai Man", "documented": "CHAN Tai Man"},
            {"label": "n2", "kind": "name", "claimed": "Chan Tai Man", "documented": "陳大文", "variants": ["Chan Tai Man"]}
        ])["records"][0]
        self.assertEqual([c["consistent"] for c in r["checks"]], [True, False, True, True])

    def test_wealth_timeline_gap(self):
        r = calc_wealth_timeline(None, [
            {"date": "2023-09-01", "direction": "in", "amount": 1150000, "label": "opening"},
            {"date": "2023-09-01", "direction": "in", "amount": 60500},
            {"date": "2023-10-01", "direction": "in", "amount": 60500},
            {"date": "2023-10-20", "direction": "in", "amount": 6860000, "label": "mortgage"},
            {"date": "2023-10-20", "direction": "out", "amount": 9800000, "label": "price"}])["records"][0]
        self.assertEqual(r["funding_gap_hkd"], 1669000)
        self.assertFalse(r["reconciles"])
        self.assertEqual(r["timeline"][-1]["balance_hkd"], -1669000)


class TestTextAndIntake(unittest.TestCase):
    def test_parsers(self):
        self.assertEqual(parse_amount("HK$8.2 million"), 8200000)
        self.assertEqual(parse_amount("HKD 1,234,567.00"), 1234567)
        self.assertEqual(parse_date("30 June 2021"), "2021-06-30")
        self.assertEqual(parse_date("since March 2018"), "2018-03")
        self.assertEqual(norm_name("Harbourview Logistics Ltd"), norm_name("HARBOURVIEW LOGISTICS LIMITED"))
        self.assertEqual(tfidf_rank("gift letter", ["salary slip", "gift letter from father"])[0][0], 1)

    def test_pii_masking(self):
        text, n = mask_pii("HKID: A123456(7), account 012-345678-901, Mobile: 9123 4567, a@b.com, year 2024/25")
        self.assertEqual(n, 4)
        self.assertNotIn("A123456", text)
        self.assertIn("[ACCT ...901]", text)
        self.assertIn("2024/25", text)                       # tax years are not phone numbers

    def test_declaration_spans_are_per_line(self):
        chunks, _, masked = load_materials(CASES / "chan" / "materials")
        decl = [c for c in chunks if c.doc_type == "declaration"]
        self.assertTrue(all("line " in c.location for c in decl))
        self.assertGreaterEqual(masked, 3)
        self.assertEqual({c.doc_type for c in chunks} - {"declaration"},
                         {"payslip", "employment_letter", "tax_return", "bank_statement", "mortgage", "tenancy"})

    def test_parse_faults(self):
        self.assertEqual(parse_faults("lookup_company=timeout*2"), {"lookup_company": {"kind": "transient", "remaining": 2}})


if __name__ == "__main__":
    unittest.main()
