# SoWScout2 — source-of-wealth verification and Ask

**An evidence-linked, human-supervised source-of-wealth (SoW) verification agent for Hong Kong client onboarding.**
SoWScout reads a client's SoW declaration and evidence packet (payslips, tax notices, bank statements, property
and mortgage papers), extracts typed, checkable claims, plans the verification, checks each claim in a bounded
tool-using loop against the documents and mock Companies / Land Registries, does all arithmetic in Python,
passes every finding through a deterministic citation and completion gate, and drafts an auditable **SoW memo**
for a compliance officer. Each claim is **supported**, **unresolved** or a **potential red flag**, with cited
evidence or an explicit list of what is missing. **It never approves or rejects a client.**

Members: Fung Chin Chun (u3665702) · Tsoi Wai Chit Alvin (u3666009) · Lam Leung Fong (u3665643)

> This copy adds MedScout-style Ask, API routing, Models & data, database tools and easy launch.
> See [START HERE](START_HERE.md) for setup, [the feature comparison](docs/V2_CHANGES.md) for details, and [AGENT HANDOFF & EVALUATION LOG](docs/AGENT_HANDOFF.md) for architecture notes, proposal alignment (ELVS/CCR), and live DeepSeek benchmark results.
> The six bundled clients and company/property registries are synthetic demonstrations.
> Live registry APIs are not connected. The original SoW verification workflow and officer decision boundary remain.

---

## Quickstart

```bash
python3 -m venv .venv && . .venv/bin/activate      # Python 3.10+ (tested on 3.13)
pip install -r requirements.txt
```

```bash
python run.py ui --open          # web console + run controller at http://127.0.0.1:8765
python run.py demo               # fictional client "Wong Ka Yan" (funding gap), offline, System C
python run.py test               # unit/integration tests using local fake model servers
python run.py eval               # 6 cases + 3 counterfactuals x systems A, B, C and ablations -> eval/results/
```

Each run writes `runs/<run_id>/memo.md` (the deliverable), `trace.jsonl` (every model call, tool call,
decision, gate check), `record.json` (full case record), `summary.json` and `packet/` (an immutable copy of the
documents that were reviewed).

### Other commands

```bash
python run.py run --case ho --reviewer                 # + optional independent reviewer (fresh context, no tools)
python run.py run --case lee --system B                # System B: tools, no playbooks, no gate
python run.py run --case wong --system C-no-calc       # ablation: no deterministic calculator
python run.py run --case chan --interactive            # officer answers questions and can add missing documents
python run.py run --case wong --focus property         # changed request: property claims only
python run.py run --case lee --transport mcp           # registry tools served over MCP (FastMCP)
python run.py remember <run_id> --officer KYC-07       # step 8: officer confirms supported findings -> client memory
python run.py resume <run_id>                          # continue an interrupted run from its checkpoint
python run.py probe --case wong --claim C3 --show-context      # one decision, no tool execution
python run.py tool-check calc_wealth_timeline '{"items":[{"date":"2023-09","direction":"in","amount":1150000},{"date":"2023-10","direction":"out","amount":1200000}]}'
SOWSCOUT_FAULTS="lookup_company=timeout*2" python run.py demo   # tool fault injection
SOWSCOUT_MOCK_FAULTS="malformed:1,ungrounded:1" python run.py demo
python run.py eval --split heldout --runs 3 --provider ollama --model llama3.1:8b
```

### Use a real model

| Provider | Setup | Command |
|---|---|---|
| Ollama (local) | `ollama pull llama3.1:8b` (tool-capable 8B+ recommended) | `python run.py demo --provider ollama --model llama3.1:8b` |
| OpenAI-compatible | `export OPENAI_BASE_URL=... OPENAI_API_KEY=...` | `python run.py demo --provider openai --model <model>` |
| Azure-style (e.g. HKU GenAI, if compatible) | `export AZURE_OPENAI_ENDPOINT=... AZURE_OPENAI_API_KEY=... AZURE_OPENAI_API_VERSION=...` | `python run.py demo --provider openai --model <deployment>` |

Cost accounting: `export SOWSCOUT_PRICE_IN=<USD / 1M input tokens> SOWSCOUT_PRICE_OUT=<...>`; optional cost cap
`max_cost_usd` in `Limits` (or in the UI). Keep credentials in environment variables only.

---

## Architecture (proposal Figure 1)

`docs/workflow.tex` is the editable TikZ source of Figure 1. Each box maps to code:

| Figure 1 | Implementation |
|---|---|
| Client declaration and evidence packet | `data/cases/<case>/materials/` (or uploads in the UI) |
| 1. Intake and standardisation | `intake.py` — document types, per-line declaration spans, source locations, **PII masking** (HKID, account numbers, phones, e-mails); packet snapshot in `runs/<id>/packet/` |
| 2. Extract checkable SoW claims | `workflow.extract_claims` + `prompts/extract.md` + `skills/claim-extraction` — typed fields: category, entity, amount, currency, date, period, event |
| 3. Verification planner (+ client memory) | `workflow.plan` + `prompts/plan.md`; officer-verified facts from `memory.py` are shown to the planner and registered as `memory` evidence |
| Branches: policy / employment / property / documents | playbooks `skills/{employment-income, property-purchase, property-sale, rental-income, third-party-funding, out-of-scope}`; tools `search_policy`, `lookup_company`, `lookup_property`, `search_documents` / `parse_document` |
| 4. Evidence and deterministic consistency checks | `harness.py` (bounded ReAct loop per task) + `check_consistency` and `calc_wealth_timeline` (`tools/calc.py`) |
| Sufficient evidence or stop limit? → missing documents? | `workflow.sufficiency` — asks the officer for documents (`--interactive` or the UI), re-plans only the affected claims; bounded by `max_evidence_rounds`; otherwise keeps the gaps |
| 5. Evidence-linked findings | `Finding` in `state.py`: status, evidence ids, conflicts, missing evidence, open questions, computed numbers; `workflow.reconcile` adds cross-claim conflicts and the wealth timeline |
| 6. Citation and completion gate | `verify.py` — per task (one bounded revision) and as a final node (downgrade to `unresolved`) |
| 7. Draft SoW memo | `memo.py` → `memo.md` |
| Optional: independent reviewer | `reviewer.py` + `prompts/reviewer.md` (`--reviewer`) — fresh context, no tools, sees only findings and cited spans |
| 8. Human compliance review | memo's officer-decision block; `python run.py remember` / "Confirm into client memory" in the UI. The agent has no write or decision tool. |
| Harness (every step) | read-only tool allowlist (`tools/registry.py`), step / tool / time / cost caps (`config.Limits`), typed state + checkpoints, `trace.jsonl`, bounded retries (`tools/gateway.py`) |

```
 workflow (outer graph, checkpointed after every node and task)
 intake → extract_claims → plan → verify → sufficiency ─┬→ reconcile → gate → review → memo → done
                            ↑                            │
                            └──── new documents ─────────┘  (max_evidence_rounds)

 verify: for each task  ── context builder [rules + tool catalog + playbook index] [task + LOADED_SKILL +
                           declaration excerpts + CLIENT_MEMORY] [history] [WORKING_STATE]
                         → LLM: tool_calls | ask_user | finish
                         → parse + schema + allowlist → gateway (parallel, timeout, retry, evidence ids)
                         → finish → citation/completion checks → accept | revise once | downgrade
```

### Status rules (fixed before annotation, proposal §4.1)

* **supported** — a cited document / registry / memory span matches the claim and every numeric check agrees
  within **±5%**. Enforced: the declaration is never support for itself; a claim with an amount needs a cited
  calculator result that agrees.
* **unresolved** — required evidence is missing or insufficient; the finding must name the missing documents or
  an open question. Tool failures and budget stops always end here, never in a guess.
* **potential red flag** — cited evidence conflicts with the claim or the numbers fail to reconcile beyond 5%;
  the conflict must be stated and backed by non-declaration evidence. It is a review trigger, not a finding of
  misconduct; approve / reject / misconduct language is rejected by the gate.

### Which decisions are the model's, which are Python's

* **Model**: which statements are checkable claims and their typed fields; the verification plan and playbook;
  which tool with which arguments; when to ask the officer; when to stop; the status and its rationale; the
  optional independent review.
* **Python**: chunking, document types, PII masking, source locations; schema and allowlist checks; budgets,
  deadlines, retries; evidence ids and provenance; **all arithmetic** (amount / date / name comparisons, FX at
  fixed versioned rates, wealth timeline and funding gap); the citation and completion gate; cross-claim
  conflicts; coverage of every claim; memo rendering; memory writes (only after an officer confirms).

### Tools (all read-only)

| Tool | Evidence type | Purpose |
|---|---|---|
| `search_documents`, `parse_document` | document | span retrieval (TF-IDF) and structured parsing (key/value fields, bank rows with numeric values); never returns the declaration |
| `lookup_company` | registry | mock Companies Registry: incorporation, status, dissolution, English / Chinese names |
| `lookup_property` | registry | mock Land Registry: owners, assignments (consideration, date), mortgages |
| `check_consistency` | calculation | claimed vs documented: amount (±5%, multiplier, FX), date, date order, name (+ confirmed variants) |
| `calc_wealth_timeline` | calculation | dated inflows / outflows → running HKD balance, totals, funding gap |
| `search_policy` | policy | versioned, *paraphrased* AML/SoW guidance notes (`data/policy/`) — guidance, never evidence about the client |
| `read_skill_reference`, `get_evidence` | – | playbook references; recover compressed evidence |

### Where each lecture concept lives

| Concept | Implementation |
|---|---|
| Bounded agent loop, stopping rules, ReAct | `harness.py` — step / tool / time / cost budgets, `finish`, `ask_user`, handoff to `unresolved` |
| Prompt chaining for predictable stages | `workflow.py` intake → extract → plan → … → memo |
| Planning / decomposition with a coverage check | `workflow.plan` (fallback task for every missed claim) |
| JSON tool protocol, allowlist, structured errors | `protocol.py`, `tools/registry.py`, `tools/gateway.py`, `tools/base.py` |
| Parallel calls with call ids, retry with backoff + jitter | `ToolGateway.run_batch`, `_execute_with_retry`; fault injection `SOWSCOUT_FAULTS` |
| Constrained generation + runtime validation + bounded repair | Ollama `format` / OpenAI `json_object` + jsonschema; one repair |
| MCP discovery and invocation | `mcp_server.py` (registries + policy) + MCP transport in the gateway |
| Context builder, stable prefix, compression with recoverable originals | `context.py`, `prompts/system.md`, `get_evidence` |
| Skills: discover → activate → references | `skills/*/SKILL.md`, `skills.py` |
| Memory: working state vs controlled semantic memory | `state.py`; `memory.py` (client facts and name variants written only with an officer's confirmation) |
| Separating planning, runtime authorisation and verified completion | planner (`plan`), gateway allowlist + read-only tools, completion gate (`verify.py`) |
| Human in the loop | `ask_user`, `request_evidence`, claim / plan review, tool approval, step mode, notes, skip (`control.py`, web UI) |
| Checkpoints and resume | `Workflow.checkpoint`, `python run.py resume`, Resume in the UI |
| Tracing, latency, cost | `trace.py`, `llm.call_model` |

---

## Synthetic benchmark (proposal §4.1)

Six FICTIONAL clients in `data/cases/`, each with a declaration, short evidence packet and mock registries.
Gold records (status, evidence links, normalised fields, gold arithmetic) are in `eval/cases.json`.

| Case | Split | Scenario | Gold |
|---|---|---|---|
| `chan` | dev | clean salary, fully funded purchase, rental income; earlier job without documents | 3 supported, 1 unresolved |
| `wong` | dev | unexplained HKD 1.8m third-party credit, funding gap HKD 1,669,000 | 2 supported, 1 red flag |
| `lee` | held-out | employer incorporated after the claimed start; tax notice 60% below claimed salary | 1 red flag, 2 supported |
| `ho` | held-out | conflicting narrative (sale price and year differ from the land register), unevidenced sale proceeds, business income (out of scope) | 2 red flags, 2 unresolved |
| `ng` | held-out | parental gift with a letter but no transfer; no bank statement for the payment period; name variant on payslip | 1 supported, 2 unresolved |
| `cheung` | held-out | returning client: officer-verified memory, new salary, new sale | 3 supported |

Counterfactual edits (§4.3) on held-out cases: remove a key document (`cf_lee_remove_letter`), change an amount
(`cf_ng_salary_conflict`), paraphrase without changing facts (`cf_cheung_paraphrase`). Edits are applied to a
temporary copy; the originals never change.

**To do before the held-out evaluation** (proposal): author 4–6 more cases (10–12 total, 5–8 claims each, with
distractor spans), have two members annotate independently with a third adjudicating and report agreement,
and freeze prompts, playbooks and thresholds.

## Evaluation (proposal §4.2–4.3)

`python run.py eval [--systems A,B,C,C-no-calc,C-no-gate,C-no-skills] [--split dev|heldout|all] [--runs 3] [--provider ...]`

| System | Configuration |
|---|---|
| A | single prompt, no tools; receives the same declaration, documents **and registry records** as plain text (`baselines.py`) |
| B | LLM + verification tools; one generic task per claim; no playbooks; no gate |
| C | B + playbook-guided planner + citation/completion gate (default) |
| C-no-calc / C-no-gate / C-no-skills | one component removed at a time |

Headline metrics: **joint finding correctness** (right status AND justified evidence link or stated missing
evidence AND, for numeric gold, the right figure), **red-flag recall**, **false-flag rate**, **evidence-support
rate**, **arithmetic error count** (+ funding-gap absolute error). Secondary: macro-F1, unresolved-presented-as-
supported, unsupported-fact count, claim P/R/F1 and field accuracy, efficiency (time, tokens, calls, cost),
and the counterfactual expected-behaviour rate. Results: `eval/results/<timestamp>.md/.json` with micro-averaged
headline, a paired per-case scorecard and per-claim marks. The evidence-support rate is an automatic proxy (cited
identifier matches gold); the proposal's blinded manual span review must confirm it.

`examples/eval_mock_results.md` shows a **mock** run. Those numbers only show that scoring works: the mock's rules
were written alongside the cases, and the mock ignores playbooks, so B, C and C-no-skills coincide. Two things
the mock does show by construction: System A's "mention = support" behaviour misses every red flag, and without
the calculator the funding gap cannot be cited, so the gate refuses to publish it.

## Reliability and recovery (tested)

| Failure | Detection | Bounded recovery | Test |
|---|---|---|---|
| Malformed model output | JSON / schema / allowlist | one repair, then controlled stop | `test_format_repair_and_gate_revision` |
| Ungrounded or unsafe finding (unknown id, declaration-only support, uncomputed number, approve/reject language) | citation/completion gate | one revision, then downgrade to `unresolved` | same + `TestGate` |
| Registry timeout / unavailable | exception classification | ≤2 retries with backoff (transient only); otherwise `unresolved` | `test_registry_unavailable_gives_honest_gaps` |
| Missing documents | `unresolved` + `missing_evidence` | officer supplies documents → re-plan affected claims (bounded) or keep gaps | `test_missing_documents_loop_back_to_planner`, `test_request_evidence_in_ui` |
| Name variant (payslip vs declaration) | model asks | one question per task; variant stored only if the officer confirms | `test_human_confirmed_name_variant_becomes_memory` |
| Step / tool / time / cost budget | harness counters | handoff to `unresolved`, reason recorded | `test_step_budget_handoff` |
| Crash / Ctrl-C / stop | checkpoint after every node and task | `python run.py resume <id>` | `test_resume_from_checkpoint`, `test_stop_then_resume` |

## Project layout

```
run.py                     CLI entry point
sowscout/
  workflow.py              outer graph (Figure 1) + checkpoints + remember_findings (step 8)
  harness.py               bounded ReAct verification loop for one task
  verify.py                citation and completion gate (deterministic)
  reviewer.py              optional independent reviewer
  memo.py                  SoW memo rendering
  intake.py                parsing, document types, PII masking
  protocol.py  context.py  llm.py  control.py  trace.py  skills.py  memory.py  config.py  state.py
  baselines.py             System A
  evaluation.py            gold scoring, ablations, counterfactuals, repeated runs
  mock_policy.py           MOCK scripted model for offline runs and tests
  mcp_server.py            mock registries + policy over MCP
  tools/                   documents, registries, calc, local (policy, references), gateway, registry, text
  web/                     local web console (python run.py ui)
prompts/                   system.md, extract.md, plan.md, reviewer.md, baseline*.md
skills/                    claim-extraction + one playbook per source type (+ references/)
data/cases/                six FICTIONAL clients: materials/ + registry/ (+ memory in case.json)
data/policy/               versioned, paraphrased guidance notes
eval/cases.json            gold records + counterfactual edits
docs/workflow.tex          editable TikZ source of Figure 1
examples/                  demo memo, mock evaluation, UI screenshots
tests/                     unittest suite (python run.py test)
```

## Mocks, unverified parts and limitations

* **Mock model** (`--provider mock`, default): keyword and field rules that read only the assembled context and
  emit the real protocol. It tests the plumbing; **mock evaluation numbers are not evidence of quality.**
* **Synthetic data only**: clients, documents, companies, properties, memorial numbers and bank records are invented.
  Registries are mock JSON files standing in for Companies Registry / Land Registry searches; there is no live access.
* **Policy corpus** (`data/policy/`) is a set of *paraphrased* study notes, not the official HKMA text; verify against
  the current guideline before relying on it. FX rates in the calculator are fixed and synthetic.
* **Retrieval** is lexical (TF-IDF). The proposal's sentence-embedding comparison (top-1 accuracy, MRR) is a stretch
  item: add an embedding ranker beside `tools/text.tfidf_rank` and score it on gold spans plus distractors.
* **Entailment** between span and claim is done by the model (and optionally the reviewer); the gate checks only that
  ids, locations, numbers and labels exist and are valid.
* **Real model clients** are tested against local fake endpoints only (`tests/test_llm_http.py`). The HKU GenAI
  endpoint format was not confirmed.
* Not covered: OCR, scanned documents, Chinese-language declarations (name variants are a stress test only),
  business ownership, inheritance, crypto.

## AI assistance

This skeleton was produced with AI assistance (Claude Code), adapting the team's MedScout harness. Per the course
guideline, submit the project-related prompts and a short declaration of which tools/models were used and how.
