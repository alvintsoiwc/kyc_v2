"""Tool contract (Lec 4 "Tool contract", Lec 5 "Tool definition").

A tool exposes an executable operation through a name, an input contract and
a result. The model only sees the name, description and input schema; the
runtime validates inputs and outputs and enforces execution conditions.
All SoWScout tools are read-only: none can contact a client, change a record
or approve / reject onboarding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class ToolError(Exception):
    """Structured tool failure.

    kind:
      transient   – timeout / rate limit: bounded retry may help
      permanent   – bad arguments: do not repeat unchanged
      unavailable – source not reachable in this configuration (e.g. no mock registry for the case)
    """

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass
class ToolContext:
    """Everything a handler may read. Handlers never see the model or the prompt."""
    registry_dir: Path | None = None   # data/cases/<case>/registry (mock Companies / Land Registry)
    policy_dir: Path | None = None     # data/policy (versioned guidance notes)
    chunks: list[Any] = field(default_factory=list)          # SourceChunk list (client packet, PII-masked)
    evidence: dict[str, Any] = field(default_factory=dict)   # evidence store (read-only for tools)
    skills: Any = None                 # SkillLibrary
    timeout_s: float = 10.0
    database: Any = None
    database_notes: str = ""


@dataclass
class ToolSpec:
    name: str
    description: str                   # when to use it — the model reads this
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]]
    source_label: str                  # shown in the source log
    evidence_type: str = "document"    # see state.EVIDENCE_TYPES
    record_id_field: str = ""          # field in each record used as the evidence identifier
    location_field: str = ""           # field in each record used as the source location
    read_only: bool = True
    registers_evidence: bool = True
    group: str = "core"                # "calculator" tools can be removed for the ablation

    def model_view(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.input_schema}


RESULT_ENVELOPE: dict[str, Any] = {
    "type": "object",
    "required": ["source", "total", "records"],
    "properties": {
        "source": {"type": "string"},
        "total": {"type": "integer", "minimum": 0},
        "records": {"type": "array", "items": {"type": "object"}},
        "note": {"type": "string"},
        "synthetic": {"type": "boolean"},
    },
}


def envelope(records_schema: dict[str, Any]) -> dict[str, Any]:
    env = {**RESULT_ENVELOPE, "properties": {**RESULT_ENVELOPE["properties"]}}
    env["properties"]["records"] = {"type": "array", "items": records_schema}
    return env


def string_arg(desc: str, **extra: Any) -> dict[str, Any]:
    return {"type": "string", "description": desc, "minLength": 1, "maxLength": 200, **extra}
