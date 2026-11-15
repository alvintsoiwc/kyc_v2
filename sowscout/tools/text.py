"""Text helpers shared by tools and the runtime: tokenising, lexical scoring
(TF-IDF), amount / date parsing and entity-name normalisation."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

_WORD = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "of", "and", "or", "for", "in", "on", "with", "to", "by", "is", "are", "at", "my", "i",
        "was", "from", "as", "this", "that", "be", "it"}
LEGAL = {"limited", "ltd", "co", "company", "inc", "llc", "corp", "corporation", "holdings", "hk", "hong", "kong",
         "group", "plc", "gmbh"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})


def words(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in STOP]


def text_score(text: str, query: str) -> float:
    """Fraction of query words present in text (cheap lexical relevance)."""
    need = set(words(query))
    if not need:
        return 0.0
    return len(need & set(words(text))) / len(need)


def tfidf_rank(query: str, docs: list[str]) -> list[tuple[int, float]]:
    """Rank documents by TF-IDF cosine similarity with the query (lexical retrieval baseline)."""
    toks = [Counter(words(d)) for d in docs]
    n = len(docs)
    df = Counter(w for t in toks for w in t)
    idf = {w: math.log((1 + n) / (1 + c)) + 1 for w, c in df.items()}

    def vec(t: Counter) -> dict[str, float]:
        return {w: c * idf.get(w, 1.0) for w, c in t.items()}

    q = vec(Counter(words(query)))
    qn = math.sqrt(sum(v * v for v in q.values())) or 1.0
    out = []
    for i, t in enumerate(toks):
        v = vec(t)
        dot = sum(q.get(w, 0) * x for w, x in v.items())
        vn = math.sqrt(sum(x * x for x in v.values())) or 1.0
        out.append((i, dot / (qn * vn)))
    return sorted(out, key=lambda x: -x[1])


def norm_name(name: str) -> str:
    """Normalise a person / company name: lower case, no punctuation or legal suffixes, sorted tokens
    (so 'CHAN Tai Man' == 'Tai Man Chan')."""
    toks = [w for w in _WORD.findall((name or "").lower()) if w not in LEGAL]
    return " ".join(sorted(toks))


_AMOUNT = re.compile(r"(?:(HKD|HK\$|USD|US\$|RMB|CNY|GBP|\$)\s?)?(-?\d[\d,]*(?:\.\d+)?)\s*(million|m\b|k\b)?", re.I)


def parse_amount(value: Any) -> float | None:
    """'HKD 1,234,567.00' -> 1234567.0; 'HK$8.2 million' -> 8200000.0; numbers pass through."""
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    m = _AMOUNT.search(value.replace(" ", " "))
    if not m:
        return None
    try:
        x = float(m.group(2).replace(",", ""))
    except ValueError:
        return None
    mult = (m.group(3) or "").lower()
    if mult in ("million", "m"):
        x *= 1_000_000
    elif mult == "k":
        x *= 1_000
    return round(x, 2)


def parse_currency(value: str) -> str:
    m = re.search(r"\b(HKD|USD|RMB|CNY|GBP)\b|HK\$|US\$", value or "", re.I)
    if not m:
        return ""
    t = m.group(0).upper()
    return {"HK$": "HKD", "US$": "USD", "CNY": "RMB"}.get(t, t)


def parse_date(value: str) -> str:
    """Normalise to YYYY-MM-DD / YYYY-MM / YYYY. Accepts '2021-06-30', '30 June 2021', 'June 2021', '2021'."""
    s = (value or "").strip()
    m = re.search(r"(20\d\d|19\d\d)-(\d\d)(?:-(\d\d))?", s)
    if m:
        return "-".join(x for x in m.groups() if x)
    m = re.search(r"(?:(\d{1,2})\s+)?([A-Za-z]{3,9})\.?\s+(20\d\d|19\d\d)", s)
    if m and m.group(2).lower() in MONTHS:
        mo = MONTHS[m.group(2).lower()]
        return f"{m.group(3)}-{mo:02d}" + (f"-{int(m.group(1)):02d}" if m.group(1) else "")
    m = re.search(r"\b(20\d\d|19\d\d)\b", s)
    return m.group(1) if m else ""


def kv_fields(text: str) -> dict[str, str]:
    """'Key: value' lines, '**Key:** value' lines and two-column '| key | value |' table rows."""
    out: dict[str, str] = {}
    for ln in text.splitlines():
        ln = ln.strip().lstrip("-* ").replace("**", "")
        m = re.match(r"^([A-Za-z][A-Za-z0-9 /()&'.-]{1,40}):\s+(.+)$", ln)
        if m:
            out.setdefault(m.group(1).strip().lower(), m.group(2).strip())
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")] if ln.startswith("|") else []
        if len(cells) == 2 and cells[0] and not set(cells[0]) <= set("-: "):
            out.setdefault(cells[0].lower(), cells[1])
    return out


def table_rows(text: str) -> list[dict[str, str]]:
    """Markdown tables with a header row and 3+ columns -> list of dicts (e.g. bank transactions)."""
    rows, header = [], None
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if header is None:
            header = [c.lower() for c in cells]
            continue
        rows.append(dict(zip(header, cells)))
    return rows
