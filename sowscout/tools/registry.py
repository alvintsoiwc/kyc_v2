"""Tool registry: the explicit allowlist of operations (Lec 5 "Registration and dispatch").

Proposal §3.1 names six bounded tools: parse_document, lookup_company,
lookup_property, calc_wealth_timeline, check_consistency and search_policy.
search_documents (span retrieval), read_skill_reference and get_evidence are
helpers. Every tool is read-only.
"""

from __future__ import annotations

import json

from . import calc, documents, local, registries
from .base import ToolSpec

# Tools served by the registry MCP server when --transport mcp is used.
REGISTRY_TOOLS = {"lookup_company", "lookup_property", "search_policy"}
CALCULATOR_TOOLS = {"calc_wealth_timeline", "check_consistency"}


def build_specs(calculator: bool = True, database: bool = False) -> dict[str, ToolSpec]:
    specs = [
        ToolSpec(
            name="search_documents",
            description="Find spans in the client's supporting documents (payslips, tax returns, bank statements, "
                        "property and mortgage papers, letters). Returns text plus parsed key/value fields. The "
                        "declaration itself is never returned: it is the claim, not evidence.",
            input_schema=documents.SEARCH_DOCS_INPUT, output_schema=documents.SEARCH_DOCS_OUTPUT,
            handler=documents.search_documents, source_label="Client document", evidence_type="document",
            record_id_field="span_id", location_field="location"),
        ToolSpec(
            name="parse_document",
            description="Parse one whole supporting document: every span with key/value fields and table rows "
                        "(e.g. bank transactions with numeric debit/credit/balance values).",
            input_schema=documents.PARSE_DOC_INPUT, output_schema=documents.PARSE_DOC_OUTPUT,
            handler=documents.parse_document, source_label="Client document", evidence_type="document",
            record_id_field="span_id", location_field="location"),
        ToolSpec(
            name="lookup_company",
            description="Mock Companies Registry: incorporation date, status (Live / Dissolved), dissolution date, "
                        "English / Chinese / former names. Use to check that a claimed employer existed during "
                        "the claimed employment period.",
            input_schema=registries.LOOKUP_COMPANY_INPUT, output_schema=registries.LOOKUP_COMPANY_OUTPUT,
            handler=registries.lookup_company, source_label="Mock Companies Registry", evidence_type="registry",
            record_id_field="cr_number"),
        ToolSpec(
            name="lookup_property",
            description="Mock Land Registry: registered owners and memorials (assignments with consideration and "
                        "date, mortgages with lender and amount) for an address.",
            input_schema=registries.LOOKUP_PROPERTY_INPUT, output_schema=registries.LOOKUP_PROPERTY_OUTPUT,
            handler=registries.lookup_property, source_label="Mock Land Registry", evidence_type="registry",
            record_id_field="property_ref"),
        ToolSpec(
            name="calc_wealth_timeline",
            description="Deterministic calculator. Give dated inflows / outflows (with evidence ids); returns HKD "
                        "running balance, totals and the funding gap. Use for any funding reconciliation instead "
                        "of doing arithmetic yourself.",
            input_schema=calc.TIMELINE_INPUT, output_schema=calc.TIMELINE_OUTPUT,
            handler=calc.calc_wealth_timeline, source_label="Calculator", evidence_type="calculation",
            record_id_field="calc_id", group="calculator"),
        ToolSpec(
            name="check_consistency",
            description="Deterministic comparison of claimed vs documented values: amount (±5% default, optional "
                        "multiplier e.g. 12 for monthly->annual, currency conversion), date (same month), "
                        "date_order (claimed not earlier than documented) and name (normalised; variants).",
            input_schema=calc.CONSISTENCY_INPUT, output_schema=calc.CONSISTENCY_OUTPUT,
            handler=calc.check_consistency, source_label="Consistency checker", evidence_type="calculation",
            record_id_field="calc_id", group="calculator"),
        ToolSpec(
            name="search_policy",
            description="Retrieve AML / SoW guidance notes (small versioned corpus, paraphrased). Use to decide "
                        "what evidence is normally expected; it is never evidence about the client.",
            input_schema=local.SEARCH_POLICY_INPUT, output_schema=local.SEARCH_POLICY_OUTPUT,
            handler=local.search_policy, source_label="Policy guidance", evidence_type="policy",
            record_id_field="section_id"),
        ToolSpec(
            name="read_skill_reference",
            description="Read a reference file belonging to a skill (status rules, document checklists).",
            input_schema=local.READ_REF_INPUT, output_schema=local.GENERIC_OUTPUT,
            handler=local.read_skill_reference, source_label="Skill reference", registers_evidence=False),
        ToolSpec(
            name="get_evidence",
            description="Recover the full stored record for an evidence id that was summarised earlier.",
            input_schema=local.GET_EVIDENCE_INPUT, output_schema=local.GENERIC_OUTPUT,
            handler=local.get_evidence, source_label="Evidence store", registers_evidence=False),
    ]
    if database:
        from . import database as db
        for name, schema in [("db_list_tables", db.LIST_INPUT), ("db_describe_table", db.DESCRIBE_INPUT), ("db_query", db.QUERY_INPUT)]:
            specs.append(ToolSpec(name=name, description="Read-only internal database context; not independent verification. " + name,
                                  input_schema=schema, output_schema=db.OUTPUT, handler=getattr(db, name),
                                  source_label="Local database", evidence_type="internal", record_id_field="_row"))
    return {s.name: s for s in specs if calculator or s.group != "calculator"}


def catalog_text(specs: dict[str, ToolSpec]) -> str:
    """Compact, deterministic tool catalog for the stable prompt prefix."""
    lines = []
    for name in sorted(specs):
        s = specs[name]
        props = s.input_schema.get("properties", {})
        args = ", ".join(f"{k}: {v.get('type', 'enum' if 'enum' in v else 'any')}" for k, v in props.items())
        req = s.input_schema.get("required") or [
            "one of " + "|".join(a["required"][0] for a in s.input_schema.get("anyOf", []))]
        lines.append(f"- {name}({args})\n  required: {json.dumps(req)}\n  {s.description}")
        if name == "calc_wealth_timeline":
            lines.append('  item: {"date":"2021-06","label":"...","direction":"in|out","amount":123,"currency":"HKD",'
                         '"evidence_id":"E3"}')
        if name == "check_consistency":
            lines.append('  check: {"label":"...","kind":"amount|date|date_order|name","claimed":..,"documented":..,'
                         '"multiplier":12,"currency":"HKD","variants":["..."]}')
    return "\n".join(lines)
