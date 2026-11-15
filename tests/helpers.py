import json
import os
import shutil
import tempfile
from pathlib import Path

from sowscout.config import ROOT, Settings
from sowscout.state import RunState

CASES = ROOT / "data" / "cases"


def temp_settings(**over) -> Settings:
    tmp = Path(tempfile.mkdtemp(prefix="sowscout-test-"))
    s = Settings()
    s.provider, s.tool_transport, s.system, s.reviewer = "mock", "local", "C", False
    s.runs_dir, s.db_path = tmp / "runs", tmp / "test.db"
    for k, v in over.items():
        setattr(s, k, v)
    return s


def new_state(case: str = "wong", focus=None, case_dir: Path | None = None) -> tuple[RunState, Path]:
    cdir = case_dir or CASES / case
    meta = json.loads((cdir / "case.json").read_text())
    return RunState.new(meta["client"], str(cdir / "materials"), meta.get("client_ref", ""), focus or []), cdir


def case_copy(case: str, edits: dict[str, tuple[str, str]] | None = None, remove: list[str] | None = None) -> Path:
    """Temporary copy of a case with text replacements {doc: (old, new)} and removed documents."""
    out = Path(tempfile.mkdtemp(prefix="sowscout-case-")) / case
    shutil.copytree(CASES / case, out)
    for doc, (old, new) in (edits or {}).items():
        p = out / "materials" / doc
        p.write_text(p.read_text().replace(old, new))
    for doc in remove or []:
        (out / "materials" / doc).unlink()
    return out


def seed(settings: Settings, cdir: Path) -> None:
    from sowscout.memory import seed_case_memory
    meta = json.loads((cdir / "case.json").read_text())
    seed_case_memory(settings.db_path, cdir, meta["client"])


class env:
    """Temporarily set environment variables."""

    def __init__(self, **kv):
        self.kv, self.old = kv, {}

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.kv}
        os.environ.update(self.kv)

    def __exit__(self, *a):
        for k, v in self.old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
