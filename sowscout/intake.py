"""Intake and standardisation (proposal Fig. 1, step 1).

Loads the client declaration and evidence packet into chunks that keep their
original source location, assigns a document type, and masks PII before any
text reaches a model:

  HKID numbers         A123456(7)       -> [HKID]
  bank account numbers 012-345678-901   -> [ACCT ...901]
  phone numbers        +852 9123 4567   -> [PHONE]
  e-mail addresses                      -> [EMAIL]

Supported: .md, .txt, .pdf (pypdf, text layer only). OCR is out of scope.
"""

from __future__ import annotations

import re
from pathlib import Path

from .state import SourceChunk

MAX_CHUNK_CHARS = 900
_DATE = re.compile(r"(20\d\d-\d\d(?:-\d\d)?)")

PII_RULES: list[tuple[re.Pattern, object]] = [
    (re.compile(r"\b[A-Z]{1,2}\d{6}\s?\([0-9A]\)"), "[HKID]"),
    (re.compile(r"\b\d{3}-\d{6}-(\d{3})\b"), lambda m: f"[ACCT ...{m.group(1)}]"),
    (re.compile(r"\+852[\s-]?\d{4}[\s-]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"(?i)\b(tel|phone|mobile)(:?\s*)\d{4}[\s-]?\d{4}\b"), lambda m: f"{m.group(1)}{m.group(2)}[PHONE]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
]

DOC_TYPES = {
    "declaration": ("declaration", "sow_form", "narrative"),
    "payslip": ("payslip", "pay_slip", "salary_slip"),
    "employment_letter": ("employment_letter", "offer_letter", "employer_letter"),
    "tax_return": ("tax", "ird", "salaries_tax"),
    "bank_statement": ("bank", "statement"),
    "property": ("sale_and_purchase", "s&p", "assignment", "provisional", "property", "land"),
    "mortgage": ("mortgage", "loan"),
    "tenancy": ("tenancy", "lease"),
    "letter": ("gift", "letter"),
}


def mask_pii(text: str) -> tuple[str, int]:
    n = 0
    for rx, repl in PII_RULES:
        text, k = rx.subn(repl, text)
        n += k
    return text, n


def doc_type(name: str, text: str) -> str:
    m = re.search(r"^document type:\s*(.+)$", text[:400], re.I | re.M)
    if m:
        return m.group(1).strip().lower().replace(" ", "_")
    low = name.lower()
    for t, keys in DOC_TYPES.items():
        if any(k in low for k in keys):
            return t
    return "other"


def _doc_date(name: str, text: str) -> str:
    m = re.search(r"^date:\s*(.+)$", text[:400], re.I | re.M) or _DATE.search(name)
    return m.group(1).strip() if m else ""


def _md_chunks(text: str) -> list[tuple[str, str]]:
    """Split by headings, then by blank-line paragraphs up to MAX_CHUNK_CHARS. Returns (location, text)."""
    out: list[tuple[str, str]] = []
    section, buf, start = "(top)", [], 1
    lines = text.splitlines()

    def flush(end: int) -> None:
        body = "\n".join(buf).strip()
        if body:
            out.append((f"section '{section}', lines {start}-{end}", body))

    for i, ln in enumerate(lines, 1):
        if ln.startswith("#"):
            flush(i - 1)
            section, buf, start = ln.lstrip("# ").strip(), [], i + 1
            continue
        if not ln.strip() and sum(len(b) for b in buf) > MAX_CHUNK_CHARS:
            flush(i - 1)
            buf, start = [], i + 1
            continue
        buf.append(ln)
    flush(len(lines))
    return out


def _line_chunks(text: str) -> list[tuple[str, str]]:
    """Declarations: one span per bullet / paragraph line, so each claim links to its own line."""
    out, section = [], "(top)"
    for i, ln in enumerate(text.splitlines(), 1):
        s = ln.strip()
        if s.startswith("#"):
            section = s.lstrip("# ").strip()
        elif s and not re.match(r"^(document type|date):", s, re.I):
            out.append((f"section '{section}', line {i}", s))
    return out


def _pdf_chunks(path: Path) -> list[tuple[str, str]]:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        return [("whole file", "[PDF skipped: install pypdf]")]
    out = []
    for i, page in enumerate(PdfReader(str(path)).pages, 1):
        txt = (page.extract_text() or "").strip()
        out.append((f"page {i}", txt[:MAX_CHUNK_CHARS * 2] if txt else
                    "[no text layer on this page — OCR not supported in MVP]"))
    return out


def load_materials(materials_dir: Path, only: list[str] | None = None, start_index: int = 1
                   ) -> tuple[list[SourceChunk], list[str], int]:
    """Return (chunks, skipped files, number of PII spans masked).
    `only` + `start_index` load documents added in a later evidence round without renumbering earlier ones."""
    chunks: list[SourceChunk] = []
    skipped: list[str] = []
    masked = 0
    files = sorted(p for p in materials_dir.iterdir() if p.is_file() and not p.name.startswith(".")
                   and (only is None or p.name in only))
    for d, path in enumerate(files, start_index):
        ext = path.suffix.lower()
        if ext in (".md", ".txt"):
            raw = path.read_text(errors="replace")
            parts = _line_chunks(raw) if doc_type(path.name, raw) == "declaration" else _md_chunks(raw)
        elif ext == ".pdf":
            parts = _pdf_chunks(path)
            raw = parts[0][1] if parts else ""
        else:
            skipped.append(path.name)
            continue
        date, dtype = _doc_date(path.name, raw), doc_type(path.name, raw)
        for k, (loc, body) in enumerate(parts, 1):
            body, n = mask_pii(body)
            masked += n
            chunks.append(SourceChunk(chunk_id=f"D{d}#{k}", doc=path.name, location=loc, text=body,
                                      doc_date=date, doc_type=dtype))
    return chunks, skipped, masked
