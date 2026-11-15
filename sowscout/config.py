"""Runtime configuration: model settings, system variant, execution limits and paths.

Limits are application configuration choices (Lec 4, "Termination and retry
safety"). Every limit is enforced by the harness, not by the model.
Values can be overridden with environment variables or CLI flags.

System variants (proposal Table 1 and §4.2 ablations):
  A           single prompt, no tools                         (baselines.py)
  B           LLM + verification tools; one generic task per claim, no skills, no gate
  C           B + skill-guided planner + citation/completion gate   (default)
  C-no-calc   C without the deterministic calculator / consistency checker
  C-no-gate   C without the citation/completion gate
  C-no-skills C without the verification playbooks
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Load KEY=VALUE pairs from a local .env file into os.environ (without overwriting existing vars)."""
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        if k and k not in os.environ:
            os.environ[k] = v


load_dotenv()

SYSTEMS = {
    "B": {"skills": False, "gate": False, "calculator": True},
    "C": {"skills": True, "gate": True, "calculator": True},
    "C-no-calc": {"skills": True, "gate": True, "calculator": False},
    "C-no-gate": {"skills": True, "gate": False, "calculator": True},
    "C-no-skills": {"skills": False, "gate": True, "calculator": True},
}


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Limits:
    # Outer workflow
    max_tasks: int = 12                 # verification tasks per run
    max_evidence_rounds: int = 2        # "missing documents?" loop back to the planner (bounded)
    run_deadline_s: float = 900.0
    # Inner verification loop (one task)
    max_steps_per_task: int = 6
    max_tool_calls_per_task: int = 8
    max_calls_per_batch: int = 3
    max_format_repairs: int = 1
    max_verify_revisions: int = 1
    task_deadline_s: float = 120.0
    # Tool gateway
    tool_timeout_s: float = 10.0
    tool_max_retries: int = 2
    retry_base_delay_s: float = 0.5
    # Context budget (Lec 4, "Context budget": I+H+U+T+E+M+Y <= W)
    context_window: int = 8192
    reserved_output: int = 1024
    max_records_per_observation: int = 5
    # Cost cap (USD); 0 disables. The harness stops a task when the run exceeds it.
    max_cost_usd: float = 0.0


@dataclass
class Settings:
    provider: str = field(default_factory=lambda: _env("SOWSCOUT_PROVIDER", "mock"))
    model: str = field(default_factory=lambda: _env("SOWSCOUT_MODEL", ""))
    temperature: float = float(_env("SOWSCOUT_TEMPERATURE", "0"))
    system: str = field(default_factory=lambda: _env("SOWSCOUT_SYSTEM", "C"))
    reviewer: bool = field(default_factory=lambda: _env("SOWSCOUT_REVIEWER", "0") == "1")
    # Tool transport: "local" (in-process functions) or "mcp" (FastMCP server over stdio)
    tool_transport: str = field(default_factory=lambda: _env("SOWSCOUT_TOOL_TRANSPORT", "local"))
    interactive: bool = False
    allow_cloud: bool = field(default_factory=lambda: _env("SOWSCOUT_ALLOW_CLOUD", "0") == "1")
    use_database: bool = False
    price_in_per_m: float = float(_env("SOWSCOUT_PRICE_IN", "0"))
    price_out_per_m: float = float(_env("SOWSCOUT_PRICE_OUT", "0"))
    # Paths
    prompts_dir: Path = ROOT / "prompts"
    skills_dir: Path = ROOT / "skills"
    data_dir: Path = ROOT / "data"
    policy_dir: Path = ROOT / "data" / "policy"
    runs_dir: Path = field(default_factory=lambda: Path(_env("SOWSCOUT_RUNS_DIR", str(ROOT / "runs"))))
    db_path: Path = field(default_factory=lambda: Path(_env("SOWSCOUT_DB", str(ROOT / "runs" / "sowscout.db"))))
    limits: Limits = field(default_factory=Limits)

    @property
    def variant(self) -> dict[str, bool]:
        return SYSTEMS.get(self.system, SYSTEMS["C"])

    def default_model(self) -> str:
        if self.model:
            return self.model
        openai_default = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat") if (
            os.environ.get("DEEPSEEK_API_KEY") and not os.environ.get("OPENAI_API_KEY")) else "gpt-4o-mini"
        return {"router": "auto", "mock": "mock-scripted-policy", "ollama": "llama3.2:3b", "openai": openai_default}.get(self.provider, "")
