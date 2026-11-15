"""Deterministic calculator and consistency checker (proposal §3.1: arithmetic in
Python, not by free-form LLM arithmetic).

calc_wealth_timeline  orders dated inflows / outflows, converts to HKD at fixed
                      (versioned, synthetic) rates, and reports running balance,
                      totals and the funding gap.
check_consistency     compares claimed vs documented amounts (±5% by default),
                      dates (same month by default) and names (normalised, with
                      officer-confirmed variants).
Both return one record that the gateway registers as `calculation` evidence,
so findings can cite the exact numeric result they rely on.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..state import TOLERANCE
from .base import ToolContext, ToolError, envelope
from .text import norm_name, parse_date

FX_TO_HKD = {"HKD": 1.0, "USD": 7.80, "RMB": 1.08, "GBP": 9.90}   # fixed for reproducibility; version below
FX_VERSION = "fixed-synthetic-2026-01"


def _calc_id(kind: str, payload: Any) -> str:
    return f"{kind}:" + hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:10]


def _hkd(amount: float, currency: str) -> float:
    cur = (currency or "HKD").upper().replace("CNY", "RMB")
    if cur not in FX_TO_HKD:
        raise ToolError("permanent", f"unsupported currency {currency}; supported: {sorted(FX_TO_HKD)}")
    return round(amount * FX_TO_HKD[cur], 2)


def calc_wealth_timeline(ctx: ToolContext, items: list[dict[str, Any]], opening_balance: float = 0.0,
                         label: str = "") -> dict[str, Any]:
    rows = []
    for it in items:
        d = parse_date(str(it.get("date", "")))
        if not d:
            raise ToolError("permanent", f"item '{it.get('label', '?')}' has no parseable date")
        rows.append({"date": d, "label": it.get("label", ""), "direction": it["direction"],
                     "amount_hkd": _hkd(float(it["amount"]), it.get("currency", "HKD")),
                     "evidence_id": it.get("evidence_id", "")})
    rows.sort(key=lambda r: (r["date"], 0 if r["direction"] == "in" else 1))
    bal, low = float(opening_balance), float(opening_balance)
    for r in rows:
        bal += r["amount_hkd"] if r["direction"] == "in" else -r["amount_hkd"]
        r["balance_hkd"] = round(bal, 2)
        low = min(low, bal)
    tin = round(sum(r["amount_hkd"] for r in rows if r["direction"] == "in"), 2)
    tout = round(sum(r["amount_hkd"] for r in rows if r["direction"] == "out"), 2)
    gap = round(max(0.0, -low), 2)
    rec = {"calc_id": _calc_id("timeline", [items, opening_balance]), "label": label or "wealth timeline",
           "opening_balance_hkd": opening_balance, "total_in_hkd": tin, "total_out_hkd": tout,
           "closing_balance_hkd": round(bal, 2), "lowest_balance_hkd": round(low, 2), "funding_gap_hkd": gap,
           "reconciles": gap <= TOLERANCE * max(tout, 1.0), "tolerance": TOLERANCE, "fx_version": FX_VERSION,
           "timeline": rows}
    return {"source": "Calculator", "total": 1, "records": [rec]}


_ITEM = {
    "type": "object", "additionalProperties": False, "required": ["date", "direction", "amount"],
    "properties": {"date": {"type": "string"}, "label": {"type": "string"},
                   "direction": {"enum": ["in", "out"]}, "amount": {"type": "number", "minimum": 0},
                   "currency": {"type": "string"}, "evidence_id": {"type": "string"}},
}
TIMELINE_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {"type": "array", "minItems": 1, "maxItems": 40, "items": _ITEM},
        "opening_balance": {"type": "number"},
        "label": {"type": "string", "maxLength": 120},
    },
}
TIMELINE_OUTPUT = envelope({"type": "object", "required": ["calc_id", "funding_gap_hkd", "timeline"]})


def check_consistency(ctx: ToolContext, checks: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for c in checks:
        kind = c.get("kind", "amount")
        r: dict[str, Any] = {"label": c.get("label", kind), "kind": kind,
                             "claimed": c.get("claimed"), "documented": c.get("documented")}
        if kind == "amount":
            mult = float(c.get("multiplier", 1))
            tol = float(c.get("tolerance", TOLERANCE))
            claimed = _hkd(float(c["claimed"]) * mult, c.get("currency", "HKD"))
            doc = _hkd(float(c["documented"]), c.get("documented_currency", c.get("currency", "HKD")))
            diff = claimed - doc
            rel = abs(diff) / max(abs(doc), 1.0)
            r.update(claimed_hkd=claimed, documented_hkd=doc, multiplier=mult, difference_hkd=round(diff, 2),
                     relative_difference=round(rel, 4), tolerance=tol, consistent=rel <= tol)
        elif kind == "date":
            a, b = parse_date(str(c["claimed"])), parse_date(str(c["documented"]))
            if not a or not b:
                raise ToolError("permanent", f"check '{r['label']}': unparseable date")
            n = min(len(a), len(b), 7)       # compare to month precision unless one side is year-only
            r.update(claimed_norm=a, documented_norm=b, compared_to="month" if n == 7 else "year",
                     consistent=a[:n] == b[:n])
        elif kind == "date_order":         # claimed must not be earlier than documented (e.g. start >= incorporation)
            a, b = parse_date(str(c["claimed"])), parse_date(str(c["documented"]))
            if not a or not b:
                raise ToolError("permanent", f"check '{r['label']}': unparseable date")
            r.update(claimed_norm=a, documented_norm=b, consistent=a >= b[:len(a)])
        elif kind == "name":
            variants = [str(v) for v in c.get("variants", [])]
            a = norm_name(str(c["claimed"]))
            ok = a == norm_name(str(c["documented"])) or any(a == norm_name(v) for v in variants)
            r.update(claimed_norm=a, documented_norm=norm_name(str(c["documented"])), consistent=ok)
        else:
            raise ToolError("permanent", f"unknown check kind {kind}; use amount | date | date_order | name")
        results.append(r)
    rec = {"calc_id": _calc_id("consistency", checks), "checks": results,
           "all_consistent": all(r["consistent"] for r in results),
           "inconsistent": [r["label"] for r in results if not r["consistent"]]}
    return {"source": "Consistency checker", "total": 1, "records": [rec]}


_CHECK = {
    "type": "object", "additionalProperties": False, "required": ["kind", "claimed", "documented"],
    "properties": {"label": {"type": "string"}, "kind": {"enum": ["amount", "date", "date_order", "name"]},
                   "claimed": {"type": ["number", "string"]}, "documented": {"type": ["number", "string"]},
                   "currency": {"type": "string"}, "documented_currency": {"type": "string"},
                   "multiplier": {"type": "number", "minimum": 0}, "tolerance": {"type": "number", "minimum": 0,
                                                                                  "maximum": 0.5},
                   "variants": {"type": "array", "items": {"type": "string"}}},
}
CONSISTENCY_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["checks"],
    "properties": {"checks": {"type": "array", "minItems": 1, "maxItems": 10, "items": _CHECK}},
}
CONSISTENCY_OUTPUT = envelope({"type": "object", "required": ["calc_id", "checks", "all_consistent"]})
