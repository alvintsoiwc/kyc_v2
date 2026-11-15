"""SoWScout registry MCP server (Lec 5 "The shop MCP server").

Exposes the read-only mock registries (Companies Registry, Land Registry) and
the policy-guidance retriever over MCP, so any MCP-capable host can reuse them.
The SoWScout runtime uses it with `--transport mcp`: it discovers tools with
tools/list, keeps only the curated allowlist, and invokes them with tools/call.

Run standalone:  python sowscout/mcp_server.py --registry data/cases/chan/registry --policy data/policy
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FASTMCP_LOG_LEVEL", "WARNING")

from fastmcp import FastMCP  # noqa: E402
from fastmcp.exceptions import ToolError as MCPToolError  # noqa: E402

from sowscout.tools import local, registries  # noqa: E402
from sowscout.tools.base import ToolContext, ToolError  # noqa: E402

mcp = FastMCP("SoWScout mock registries")
CTX = ToolContext()


def _run(fn, **kwargs):
    kwargs = {k: v for k, v in kwargs.items() if v not in (None, "")}
    try:
        return fn(CTX, **kwargs)
    except ToolError as exc:
        raise MCPToolError(f"{exc.kind}: {exc.message}") from exc


@mcp.tool
def lookup_company(name: str = "", cr_number: str = "", limit: int = 3) -> dict:
    """Mock Companies Registry lookup by name or CR number."""
    return _run(registries.lookup_company, name=name, cr_number=cr_number, limit=limit)


@mcp.tool
def lookup_property(address: str = "", property_ref: str = "", limit: int = 3) -> dict:
    """Mock Land Registry lookup by address or property reference."""
    return _run(registries.lookup_property, address=address, property_ref=property_ref, limit=limit)


@mcp.tool
def search_policy(query: str, limit: int = 3) -> dict:
    """Retrieve AML / SoW guidance notes."""
    return _run(local.search_policy, query=query, limit=limit)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="")
    ap.add_argument("--policy", default="")
    a = ap.parse_args(argv)
    CTX.registry_dir = Path(a.registry) if a.registry else None
    CTX.policy_dir = Path(a.policy) if a.policy else None
    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
