"""Client-packet tools: span retrieval and structured parsing of one document.

The packet is already PII-masked by intake. Records keep the document name and
location so every finding can point at an exact span (proposal: evidence_id +
original location). The client declaration is excluded from search results:
what the client asserts is never evidence for itself.
"""

from __future__ import annotations

from typing import Any

from .base import ToolContext, ToolError, envelope, string_arg
from .text import kv_fields, parse_amount, table_rows, tfidf_rank, text_score


def _span_id(ch) -> str:
    return f"{ch.doc}#{ch.chunk_id.split('#', 1)[1]}"


def _record(ch, with_fields: bool = True) -> dict[str, Any]:
    r: dict[str, Any] = {"span_id": _span_id(ch), "doc": ch.doc, "doc_type": ch.doc_type, "doc_date": ch.doc_date,
                         "location": f"{ch.doc}, {ch.location}", "text": ch.text[:600]}
    if with_fields:
        kv = kv_fields(ch.text)
        if kv:
            r["fields"] = kv
        rows = table_rows(ch.text)
        if rows:
            r["rows"] = rows[:25]
    return r


def search_documents(ctx: ToolContext, query: str, doc_type: str = "", limit: int = 4) -> dict[str, Any]:
    pool = [c for c in ctx.chunks if c.doc_type != "declaration" and (not doc_type or c.doc_type == doc_type)]
    if not pool:
        return {"source": "Client documents", "total": 0, "records": [],
                "note": f"no documents{' of type ' + doc_type if doc_type else ''} in the packet"}
    ranked = tfidf_rank(query, [f"{c.doc} {c.doc_type} {c.text}" for c in pool])
    hits = [(pool[i], s) for i, s in ranked if s > 0 and text_score(f"{pool[i].doc} {pool[i].text}", query) > 0]
    recs = [{**_record(c), "score": round(s, 3)} for c, s in hits[:limit]]
    return {"source": "Client documents", "total": len(hits), "records": recs, "synthetic": True}


SEARCH_DOCS_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {
        "query": string_arg("Keywords, e.g. employer name, 'gross pay', a property address, 'deposit'"),
        "doc_type": {"enum": ["", "payslip", "employment_letter", "tax_return", "bank_statement", "property",
                              "mortgage", "tenancy", "letter", "other"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 8},
    },
}
SPAN_RECORD = {"type": "object", "required": ["span_id", "doc", "location", "text"]}
SEARCH_DOCS_OUTPUT = envelope(SPAN_RECORD)


def parse_document(ctx: ToolContext, doc: str) -> dict[str, Any]:
    """Every span of one document with its key/value fields and table rows (bank transactions)."""
    spans = [c for c in ctx.chunks if c.doc == doc]
    if not spans:
        docs = sorted({c.doc for c in ctx.chunks if c.doc_type != "declaration"})
        raise ToolError("permanent", f"no document named '{doc}'; packet documents: {docs}")
    if spans[0].doc_type == "declaration":
        raise ToolError("permanent", "the declaration is the client's assertion, not evidence; "
                                     "use search_documents / parse_document on supporting documents")
    recs = []
    for c in spans:
        r = _record(c)
        for row in r.get("rows", []):        # normalise numeric cells so no model arithmetic is needed to read them
            for k in ("debit", "credit", "balance", "amount"):
                if k in row and parse_amount(row[k]) is not None:
                    row[k + "_value"] = parse_amount(row[k])
        recs.append(r)
    return {"source": "Client documents", "total": len(recs), "records": recs, "synthetic": True}


PARSE_DOC_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["doc"],
    "properties": {"doc": string_arg("Document file name, exactly as shown in the packet index")},
}
PARSE_DOC_OUTPUT = envelope(SPAN_RECORD)
