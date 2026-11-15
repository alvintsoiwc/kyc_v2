# Validation

- Full regression suite: 136 tests passed, including streaming Ask, uploads, cancellation, model routing, cloud privacy checks, cost handling, read-only SQLite, original SoW workflows, evaluation and MCP transport.
- Final database changes: 2 targeted tests passed, including rejection of internal database rows as standalone supporting evidence and correct non-synthetic provenance.
- Browser smoke test: all console tabs, streamed local chat, completed demo workflow, memo handoff, desktop/mobile render; zero JavaScript errors.
- Python compilation and both JavaScript syntax checks passed.
- Windows CLI smoke test generated a completed fictional Wong case memo in runs/20261114-234559-063443/.

Tests use local fake model servers and synthetic cases. No paid API calls or real-account model availability were validated. Screenshots in examples/ui-v2/ are from those test servers.

Run the Python suite with `.venv/Scripts/python.exe -X utf8 run.py test`.
The optional browser smoke test uses Playwright (installed in this copy's environment) and Microsoft Edge:
`.venv/Scripts/python.exe -X utf8 tests/browser_smoke.py`.
