"""Mock registries: Companies Registry and Land Registry (SYNTHETIC).

Each case folder may contain data/cases/<case>/registry/companies.json and
land_registry.json. They stand in for the Hong Kong Companies Registry (ICRIS)
and Land Registry (IRIS) searches an officer could order; live registry access
is out of scope (proposal §2). Every record is labelled synthetic.
"""

from __future__ import annotations

import json
from typing import Any

from .base import ToolContext, ToolError, envelope, string_arg
from .text import norm_name, text_score


def _load(ctx: ToolContext, name: str) -> tuple[list[dict[str, Any]], str]:
    if ctx.registry_dir is None:
        raise ToolError("unavailable", "no mock registry configured for this case")
    path = ctx.registry_dir / f"{name}.json"
    if not path.exists():
        raise ToolError("unavailable", f"mock registry has no '{name}' data for this case")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("records", []), data.get("registry", name)


def lookup_company(ctx: ToolContext, name: str = "", cr_number: str = "", limit: int = 3) -> dict[str, Any]:
    if not (name or cr_number):
        raise ToolError("permanent", "give a company name or a CR number")
    recs, label = _load(ctx, "companies")
    hits = []
    for r in recs:
        if cr_number and r.get("cr_number") == cr_number:
            hits.append((1.0, r))
            continue
        if name:
            names = [r.get("name_en", ""), r.get("name_zh", "")] + r.get("former_names", [])
            exact = any(norm_name(n) == norm_name(name) for n in names if n)
            score = 1.0 if exact else max(text_score(n, name) for n in names if n)
            if score >= 0.6:
                hits.append((score, r))
    hits.sort(key=lambda x: -x[0])
    out = [{**r, "match": "exact" if s == 1.0 else "partial"} for s, r in hits[:limit]]
    note = "" if out else "no company found under this name / CR number"
    return {"source": label, "total": len(hits), "records": out, "synthetic": True, **({"note": note} if note else {})}


LOOKUP_COMPANY_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "anyOf": [{"required": ["name"]}, {"required": ["cr_number"]}],
    "properties": {
        "name": string_arg("Company name (English or Chinese)"),
        "cr_number": string_arg("Companies Registry number", pattern="^[0-9]{6,8}$"),
        "limit": {"type": "integer", "minimum": 1, "maximum": 5},
    },
}
LOOKUP_COMPANY_OUTPUT = envelope({"type": "object", "required": ["cr_number", "name_en", "status"]})


def lookup_property(ctx: ToolContext, address: str = "", property_ref: str = "", limit: int = 3) -> dict[str, Any]:
    if not (address or property_ref):
        raise ToolError("permanent", "give an address or a property reference")
    recs, label = _load(ctx, "land_registry")
    hits = []
    for r in recs:
        if property_ref and r.get("property_ref") == property_ref:
            hits.append((1.0, r))
        elif address:
            s = text_score(r.get("address", ""), address)
            if s >= 0.7:
                hits.append((s, r))
    hits.sort(key=lambda x: -x[0])
    out = [r for _, r in hits[:limit]]
    note = "" if out else "no property found for this address"
    return {"source": label, "total": len(hits), "records": out, "synthetic": True, **({"note": note} if note else {})}


LOOKUP_PROPERTY_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "anyOf": [{"required": ["address"]}, {"required": ["property_ref"]}],
    "properties": {
        "address": string_arg("Property address as written in the declaration or document"),
        "property_ref": string_arg("Property reference from an earlier lookup"),
        "limit": {"type": "integer", "minimum": 1, "maximum": 5},
    },
}
LOOKUP_PROPERTY_OUTPUT = envelope({"type": "object", "required": ["property_ref", "address", "owners", "transactions"]})
