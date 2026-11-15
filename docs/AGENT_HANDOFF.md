# Agent & Developer Handoff Guide (`sowcout_v2`)

> **Purpose of this document:** A comprehensive technical handoff, proposal-alignment reference, and experimental log for future AI coding assistants and team members working on **SoWScout2** (COMP7607 / COMP7608B project: *Evidence-Linked Source-of-Wealth Verification Agent for Hong Kong Client Onboarding*).

---

## 1. Project Overview & Core Philosophy

**SoWScout2** is a human-supervised, evidence-linked Source-of-Wealth (SoW) verification agent for Hong Kong banking/wealth-management onboarding.
- **Input:** Client's natural-language SoW declaration + supporting document packet (`.md`, `.txt`, `.pdf`) + mock Hong Kong Companies Registry & Land Registry records.
- **Output:** An auditable **SoW Verification Memo** (`runs/<run_id>/memo.md`), structured event trace (`trace.jsonl`), and full state snapshot (`record.json`).
- **Three Permitted Verdicts (tolerance ±5%):**
  1. `supported` — Backed by $\ge 1$ non-declaration evidence span (document, registry, or officer-confirmed client memory) AND all numeric checks reconcile within $\pm 5\%$ via deterministic Python calculator tools.
  2. `unresolved` — Required evidence is missing/insufficient, or budget/tool failure occurred. Must state `missing_evidence` or `open_questions`.
  3. `potential_red_flag` — Cited non-declaration evidence contradicts the claim or numbers fail to reconcile beyond $5\%$. Must state explicit `conflicts`.
- **Strict Safety Boundary:** The agent **never approves or rejects a client** and never alleges criminal misconduct/money laundering. Deterministic regex rules in `sowscout/verify.py` block unsafe onboarding language.

---

## 2. Two-Tier Back-End Architecture

### A. Outer Workflow Graph (`sowscout/workflow.py`)
Follows Proposal Figure 1 (`docs/workflow.tex`), checkpointing `RunState` (`sowscout/state.py`) to SQLite (`runs/sowscout.db`) and `runs/<run_id>/state.json` after every phase and task:
1. **`intake` (`sowscout/intake.py`):** Copies packet to `runs/<id>/packet/`, chunks documents with line locations, classifies `doc_type`, masks PII (HKID, bank account numbers, phones, emails), and loads officer-verified client memory (`sowscout/memory.py`).
2. **`extract_claims` (`prompts/extract.md` + `skills/claim-extraction`):** Extracts atomic `Claim` objects (`C1`, `C2`, ...) with Python-normalized `category`, `entity`, `amount`, `currency`, `date`, `period_end`, and `event`.
3. **`plan` (`prompts/plan.md` + `sowscout/skills.py`):**
   - **System C:** Routes each claim/group to a domain playbook (`employment-income`, `property-purchase`, `property-sale`, `rental-income`, `third-party-funding`, `out-of-scope`) and enforces a deterministic coverage check so no claim is left behind.
   - **System B (`skills=False`):** Skips the planner/playbooks and creates one generic task per claim.
4. **`verify` (`sowscout/harness.py`):** Runs `VerificationHarness` (bounded ReAct loop: max 6 steps, max 8 tool calls, max 3 parallel calls/batch) per task.
5. **`sufficiency` (`workflow.py`):** If findings are `unresolved` with `missing_evidence` and interactive mode is enabled, prompts the compliance officer for additional files and re-plans affected claims (up to `max_evidence_rounds = 2`).
6. **`reconcile` (`workflow.py`):** Detects cross-claim narrative contradictions (e.g., same property sale declared twice with different years/amounts in `ho`) and builds the sorted wealth timeline.
7. **`gate` (`sowscout/verify.py`):** Deterministic Python firewall (`check_finding` / `completion_gate`). Verifies that cited `evidence_ids` exist and were observed in the task, `supported` claims with amounts cite a consistent calculation (`check_consistency` or `calc_wealth_timeline`), figures in `numbers` appear in cited tool outputs, and no approve/reject language is used. Fails trigger 1 bounded revision inside the task, then downgrade to `unresolved`.
8. **`review` (`sowscout/reviewer.py`, optional `--reviewer`):** Fresh-context LLM call (no tools) checking whether cited spans genuinely entail the finding.
9. **`memo` (`sowscout/memo.py`):** Renders `memo.md`, `record.json`, and `summary.json`.

### B. System Variants (`sowscout/config.py` & `sowscout/baselines.py`)
| System | Implementation | Playbooks (`skills`) | Verification Tools & Python Calc | Citation/Completion Gate (`gate`) |
| :--- | :--- | :---: | :---: | :---: |
| **A** | `sowscout/baselines.py` (`run_direct`) — Single prompt with all docs + registries as plain text | ❌ | ❌ | ❌ |
| **B** | `sowscout/workflow.py` | ❌ | ✅ | ❌ |
| **C** | `sowscout/workflow.py` (Default full system) | ✅ | ✅ | ✅ |
| **C-no-calc** | Ablation: `C` without `check_consistency` / `calc_wealth_timeline` | ✅ | ❌ | ✅ |
| **C-no-gate** | Ablation: `C` without per-task and final gate | ✅ | ✅ | ❌ |
| **C-no-skills** | Ablation: `C` without domain playbooks | ❌ | ✅ | ✅ |

---

## 3. Synthetic Benchmark Cases & Counterfactuals (`data/cases/` & `eval/cases.json`)

### Development Split (`dev`)
1. **`chan` (Chan Tai Man — 4 claims):**
   - `C1` Harbourview Logistics salary (`HKD 85,000/mo` since Mar 2018) -> **`supported`**
   - `C2` Pearl Delta Trading prior job (2012–2018, no supporting docs in packet) -> **`unresolved`**
   - `C3` Flat 12B, Lime Grove purchase (`HKD 8.2M`, `4.92M` mortgage + savings) -> **`supported`** (`funding_gap_hkd: 0`)
   - `C4` Flat 5A, Kingsford Court rental income (`HKD 18,000/mo`) -> **`supported`**
2. **`wong` (Wong Ka Yan — 3 claims):**
   - `C1` Silverline Digital salary (`HKD 62,000/mo` since Jan 2019) -> **`supported`**
   - `C2` Silverline Digital annual bonus (`HKD 120,000` in Mar 2023) -> **`supported`**
   - `C3` Flat 8C, Harbour Crest purchase (`HKD 9.8M` in Oct 2023, `6.86M` mortgage) -> **`potential_red_flag`** (`funding_gap_hkd: 1,669,000`; bank statement contains an undeclared `HKD 1,800,000 TT IN KAIWING HOLDINGS LTD` third-party wire).

### Held-Out Split (`heldout`)
3. **`lee` (Lee Chi Keung — 3 claims):**
   - `C1` Golden Crane Trading salary (`HKD 150,000/mo` since Apr 2020) -> **`potential_red_flag`** (CR `3077215` shows Golden Crane was incorporated on `2021-08-02`, *after* the claimed Apr 2020 start; tax assessment `2024/25` shows annual income of `HKD 720,000`, which is 60% below `150,000 x 12 = 1,800,000`).
   - `C2` Eastwind Shipping employment (2014–2020) -> **`supported`**
   - `C3` Flat 3D, Wing Fat Mansion sale (`HKD 5.6M` in Aug 2019) -> **`supported`**
4. **`ho` (Ho Mei Ling — 4 claims):**
   - `C1` Sold Flat 18A, Bayview Garden in May 2022 for `HKD 7.5M` -> **`potential_red_flag`** (Land Registry `PR-TW-BG-18A` shows consideration was `HKD 6.9M`, an 8.7% discrepancy > 5%, and no bank statement shows proceeds).
   - `C2` Bought Flat 6B, Seaview Terrace in Jan 2023 for `HKD 10.2M` -> **`unresolved`** (no bank statement evidencing down payment / sale proceeds).
   - `C3` Consulting income from Mei Advisory Ltd -> **`unresolved`** (business ownership/income is out of MVP scope and un-evidenced).
   - `C4` Second conflicting mention in declaration ("sold Flat 18A, Bayview Garden in 2021 for about HKD 7.5M") -> **`potential_red_flag`** (conflicts with Land Registry year 2022 and price `6.9M`, plus triggers cross-claim conflict in `reconcile`).
5. **`ng` (Ng Siu Fung — 3 claims):**
   - `C1` Kowloon Bay Medical Centre Limited nurse salary (`HKD 48,000/mo` since Jul 2016) -> **`supported`** (payslip uses `Kowloon Bay Medical Centre Ltd (九龍灣醫療中心有限公司)`).
   - `C2` Parents' gift (`HKD 1.5M` in Feb 2024) -> **`unresolved`** (has signed gift letter, but no bank transfer record or donor SoW).
   - `C3` Flat 21F, Sunshine City purchase (`HKD 6.3M` in Mar 2024) -> **`unresolved`** (no bank statement for the payment period).
6. **`cheung` (Cheung Wing Sze — 3 claims, Returning Client):**
   - `C1` Tai Ping Insurance Brokers salary (`HKD 110,000/mo` since Apr 2025) -> **`supported`** (verified via new 2026 payslip).
   - `C2` Purchased Flat 9A, Grand Marine in Jul 2019 (`HKD 12.5M`) -> **`supported`** (verified via officer-confirmed `memory:` record `cws-prop-2019` seeded from `case.json`).
   - `C3` Sold Flat 9A, Grand Marine in Nov 2025 (`HKD 14.2M`) -> **`supported`** (verified via Land Registry + bank statement).

### Counterfactual Edits (`counterfactuals` in `eval/cases.json`)
- **`cf_lee_remove_letter` (`base: lee`):** Removes `04_employment_letter_eastwind.md`. Expected: `Eastwind` flips `supported` -> `unresolved`.
- **`cf_ng_salary_conflict` (`base: ng`):** Replaces `"HKD 48,000 per month"` with `"HKD 58,000 per month"` in `01_declaration.md`. Expected: `Kowloon Bay` flips `supported` -> `potential_red_flag`.
- **`cf_cheung_paraphrase` (`base: cheung`):** Paraphrases `Tai Ping` and `Grand Marine` sentences without changing facts. Expected: both stay `supported` -> `supported`.

---

## 4. Session Log: Changes Made on 15 Nov 2026

### 1. Proposal-Aligned Scoring (`ELVS` Eq. 1 & `CCR` Eq. 2)
Updated `sowscout/evaluation.py`, `sowscout/web/static/app.js`, and `tests/test_agent.py` to match Proposal §4.3 (Pages 4–5):
- **Primary Score `ELVS` (Eq. 1):**
  $$\text{ELVS} = \frac{100}{N} \sum_{i=1}^N S_i E_i A_i \in [0, 100]$$
  - Added per-case `elvs` (0–100 scale) and equally weighted mean of per-case `ELVS` in the headline summary table.
  - Added separate component accuracy metrics and counts for $S_i$ (`status_accuracy`), $E_i$ (`evidence_accuracy`), and $A_i$ (`arithmetic_accuracy`), plus per-claim failure diagnostics (`[S=1,E=1,A=0]`).
- **Counterfactual Consistency Rate `CCR` (Eq. 2):**
  $$\text{CCR} = \frac{100}{M} \sum_{j=1}^M \mathbf{1}\left[\hat{y}_j^{(0)} = y_j^{(0)} \land \hat{y}_j^{(1)} = y_j^{(1)}\right]$$
  - Added `_score_counterfactual()` in `sowscout/evaluation.py`, pairing each counterfactual claim with its unedited base-case outcome (`base_cache`).
  - Reports `ccr` (0–100), `ccr_count` (e.g. `3/4`), and `conditional_count` / `conditional_rate` (how often the edited claim is right given the original claim was right).

### 2. Automatic `.env` Loading & Direct DeepSeek Support
- Added `load_dotenv()` in `sowscout/config.py` so `.env` (containing `DEEPSEEK_API_KEY`) is loaded automatically on startup without requiring manual `export`.
- Updated `OpenAICompatLLM` in `sowscout/llm.py` and `Settings.default_model()` in `sowscout/config.py` so `--provider openai` automatically uses `https://api.deepseek.com/v1` and `deepseek-chat` when `DEEPSEEK_API_KEY` is present.
- Added the `deepseek-chat` model entry (`DeepSeek Chat V3 (direct)`) to `config/models.json`.
- Updated `Start SoWScout.command` and `launch.py` on macOS to support `~/.local/bin` (`python3.13` / `uv`).

### 3. Playbook Refinement on `dev` Split (`skills/property-purchase/SKILL.md`)
- During initial `dev` evaluation with `deepseek-chat` (`eval/results/20261115-161549.md`), System C correctly flagged `wong`'s `Harbour Crest` purchase as `potential_red_flag` (whereas System B missed it), but double-counted the cash down payment in `calc_wealth_timeline` by passing *both* the bank statement's deposit/completion debit lines (`980k + 1,960k`) *and* the full `9.8M` purchase price as `out` items (`funding_gap_hkd = 4,609,000` instead of `1,669,000`).
- Updated Step 3 of `skills/property-purchase/SKILL.md` to clarify:
  > `out: the full purchase price at completion ONLY (do NOT also add the deposit or completion balance debit rows from the bank statement as 'out' items when the mortgage loan and full purchase price are included, as that would double-count the cash down payment).`

---

## 5. Live DeepSeek (`deepseek-chat`) Evaluation Results

### A. Development Split (`dev`: `chan`, `wong`) — `eval/results/20261115-162336.md`
Command: `python run.py eval --split dev --systems A,B,C --provider openai --model deepseek-chat`

| System | Cases | Gold Claims | **ELVS (Mean)** | Joint Correct | $S$ (Status) | $E$ (Evidence) | $A$ (Arith) | Red-Flag Recall | Math Errors | `wong` Gap Error |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A** | 2 | 7 | **83.3** | 6/7 (0.857) | 1.0 (7) | 1.0 (7) | 0.857 (6) | 1.0 | 1 | HKD 131,000 |
| **B** | 2 | 7 | **83.3** | 6/7 (0.857) | 0.857 (6) | 0.857 (6) | 0.857 (6) | **0.0** | 1 | HKD 1,669,000 |
| **C** | 2 | 7 | **100.0** | **7/7 (1.000)** | **1.0 (7)** | **1.0 (7)** | **1.0 (7)** | **1.0** | **0** | **HKD 0** |

### B. Held-Out Split (`heldout`: `lee`, `ho`, `ng`, `cheung` + 3 Counterfactuals) — `eval/results/20261115-164639.md`
Command: `python run.py eval --split heldout --systems A,B,C --provider openai --model deepseek-chat`

| System | Cases | Gold Claims | **ELVS (Mean)** | Joint Correct | $S$ (Status) | $E$ (Evidence) | $A$ (Arith) | Red-Flag Recall | False-Flag Rate ↓ | **CCR (Eq. 2)** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A** | 4 | 13 | **70.8** | 9/13 (0.692) | 0.769 (10) | 0.846 (11) | 1.0 (13) | 0.667 | 0.000 | 75.0 (3/4) |
| **B** | 4 | 13 | **68.8** | 9/13 (0.692) | 0.692 (9) | 1.0 (13) | 1.0 (13) | 1.000 | 0.100 | 50.0 (2/4) |
| **C** | 4 | 13 | **83.3** | **11/13 (0.846)** | **0.846 (11)** | **1.0 (13)** | **1.0 (13)** | **1.000** | **0.000** | **75.0 (3/4)** |

#### Per-Case ELVS Across All 6 Cases (`dev` + `heldout` Combined):
| Case | Split | System A | System B | **System C** | Key Takeaway for Report |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`chan`** | `dev` | 100.0 | 100.0 | **100.0** | Clean baseline case; all systems handle standard salary/property/rental. |
| **`wong`** | `dev` | 66.7 | 66.7 | **100.0** | **A** fails mental math (`131k` error); **B** misses the `1.8M` third-party wire red flag completely (`0%` recall); **C** gets exact `1,669,000` gap. |
| **`lee`** | `heldout` | 100.0 | 100.0 | **100.0** | All catch Golden Crane; **A** fails counterfactual `cf_lee_remove_letter` (`0/1` CCR, marking Eastwind `supported` even after the letter is deleted!). |
| **`ho`** | `heldout` | 50.0 | 75.0 | **100.0** | **A** misses 2nd Bayview claim & marks Seaview `supported` without bank statement; **B** also marks Seaview `supported` without bank statement; **C** gets all 4 right. |
| **`cheung`** | `heldout` | 66.7 | 66.7 | **100.0** | **A** fails to cite `memory:` for 2019 purchase; **B** marks Tai Ping raise `unresolved`; **C** gets 100% + `2/2` on `cf_cheung_paraphrase`. |
| **`ng`** | `heldout` | 66.7 | 33.3 | **33.3** | Great error-analysis case study (see below). |
| **Mean (All 6)** | `all` | **75.0** | **73.6** | **88.9** | **System C achieves 100.0 ELVS on 5 of 6 cases** and **100% Red-Flag Recall**. |

#### Error Analysis on `ng` (For Report Discussion):
1. **`Kowloon Bay` Nurse Salary (Gold: `supported`, System B/C got: `unresolved`):**
   - Payslip lists `Kowloon Bay Medical Centre Ltd (九龍灣醫療中心有限公司)` vs declared `Kowloon Bay Medical Centre Limited`.
   - Following `prompts/system.md` line 16 (*"If a name match is ambiguous (e.g. Chinese / English names)... ask the officer once"*), the agent invoked `ask_user`. Because `run.py eval` runs unattended (`NO_HUMAN_AVAILABLE`), the agent conservatively abstained (`unresolved`) rather than auto-confirming the variant, even though `CR 1022873` in the Companies Registry contains both the English and Chinese names.
   - This also explains why `cf_ng_salary_conflict` scored `CCR = 0/1` (`orig_ok = False`), even though System C **correctly identified the edited salary conflict (`potential_red_flag`, `edited status ok = 1.0`)**.
2. **`Sunshine City` Property Purchase (Gold: `unresolved`, System C got: `supported`):**
   - Packet has no bank statement for Feb–Mar 2024. The LLM plugged the unverified gift letter amount (`1.5M`) and estimated salary into `calc_wealth_timeline`, producing `funding_gap_hkd = 0`.
   - *Potential future gate enhancement:* In `sowscout/verify.py`, require `property_purchase` claims marked `supported` to cite at least one `bank_statement` document chunk (or `memory` record) in addition to `calc_wealth_timeline`.

---

## 6. Pending Action Items & Prioritized Roadmap

### Priority 1: Optional 5-Minute Code Enhancements (To Fix the 2 Misses on `ng` or Test on New Cases)
> *Note on Benchmark Integrity:* Since `ng` is in the `heldout` split, either keep the current `heldout` score (`83.3` ELVS on `heldout`, `88.9` across all 6 cases) as the honest first-pass held-out benchmark and present `ng` as a failure-mode case study, OR report a "post-error-analysis refinement" row if applying the two fixes below:

1. **Require Bank Statement Evidence for `supported` Property Purchases (`sowscout/verify.py`):**
   - **Issue:** On `ng` Claim 3 (`Sunshine City`), the agent marked `property_purchase` as `supported` using `calc_wealth_timeline` with an unverified gift letter (`1.5M`) even though no bank statement existed for Feb–Mar 2024.
   - **Fix Location:** In `sowscout/verify.py` (`check_finding`, lines 89–102), when `claim.category == "property_purchase"` and `finding.status == "supported"` (and not backed by `memory:`): require at least one cited document evidence item with `doc_type == "bank_statement"` in addition to `calc_wealth_timeline`.
2. **Prevent Unnecessary `ask_user` on Bilingual Registry-Matched Employer Names (`skills/employment-income/SKILL.md`):**
   - **Issue:** On `ng` Claim 1 (`Kowloon Bay Medical Centre Limited`), the payslip says `Kowloon Bay Medical Centre Ltd (九龍灣醫療中心有限公司)`. In unattended `eval` mode (`NO_HUMAN_AVAILABLE`), the agent called `ask_user` and conservatively abstained (`unresolved`), which also dragged `cf_ng_salary_conflict` CCR down to `0/1` (`orig_ok = False`) even though System C caught the edited salary conflict (`edited status ok = 1.0`).
   - **Fix Location:** In `skills/employment-income/SKILL.md` (Step 1, lines 9–10), clarify that if `lookup_company` returns a Companies Registry record containing both the English and Chinese names shown on the payslip and `check_consistency(kind="name")` is consistent, treat the employer identity as verified without calling `ask_user`.

---

### Priority 2: Run the Ablation Study & Multi-Run Evaluation (Proposal §4.2)
Your codebase already implements the 3 ablation variants in `sowscout/config.py`. Run them to populate the **Ablation Table** in your final report:
1. **Run the 3 Ablations (`C-no-calc`, `C-no-gate`, `C-no-skills`):**
   ```bash
   python run.py eval --split all --systems C-no-calc,C-no-gate,C-no-skills --provider openai --model deepseek-chat
   ```
   - `C-no-calc`: Proves why deterministic Python arithmetic (`check_consistency` / `calc_wealth_timeline`) is needed over LLM mental math.
   - `C-no-gate`: Proves why the deterministic Python completion firewall (`sowscout/verify.py`) is needed to prevent unsupported `supported` verdicts.
   - `C-no-skills`: Proves why domain playbooks (`skills/*/SKILL.md`) are needed to guide multi-step verification (e.g., catching `wong`'s third-party wire).
2. **Multi-Run Stability (`--runs 3`) (Proposal §4.3):**
   ```bash
   python run.py eval --split all --systems A,B,C --runs 3 --provider openai --model deepseek-chat
   ```
   - Computes mean $\pm$ min–max range across 3 runs for the final report.
3. **Optional Local Open-Weight Model Comparison (`qwen3.5:9b` via Ollama):**
   ```bash
   SOWSCOUT_OLLAMA_THINK=false python run.py eval --split all --systems A,B,C --provider ollama --model qwen3.5:9b
   ```

---

### Priority 3: Benchmark Expansion & Annotation Agreement (Proposal §4.1)
1. **Expand Synthetic Benchmark (Optional / Time Permitting):**
   - Proposal §4.1 specifies **10–12 synthetic client onboarding cases** (5–8 claims each, ~60–90 claims total), whereas `data/cases/` currently has **6 cases** (20 base claims + 4 counterfactual claims = 24 claims).
   - Adding 4 more cases in `data/cases/` and registering them in `eval/cases.json` will bring the dataset to 10 cases.
2. **Inter-Annotator Agreement Stat:**
   - Proposal §4.1 mentions 2 independent annotators + 1 adjudicator. Record the percentage agreement / Cohen's $\kappa$ on gold claim labels (`supported` / `unresolved` / `potential_red_flag`) across the 3 teammates for the report's Dataset section.

---

### Priority 4: Final Report Writing & Optional Stretch Goals (Proposal §4.2–4.3)
1. **Report Tables & Case Studies (Ready Now):**
   - Use Section 5 tables (`dev` + `heldout` ELVS, $S/E/A$ breakdown, Red-Flag Recall, False-Flag Rate, and CCR) and the `wong`, `lee`, `ho`, `cheung`, and `ng` case studies directly in the Experiments and Discussion sections.
2. **Optional Stretch Comparisons (If Asked by Reviewer/Instructor):**
   - **Retrieval Ablation:** Compare lexical `tfidf_rank` (`sowscout/tools/text.py`) against a sentence-embedding ranker on Top-1 chunk accuracy and MRR.
   - **Blinded Human Audit:** Have two teammates score 20 cited evidence spans across Systems A, B, and C to validate the automated `E` (`evidence_support`) metric.

---

## 7. AI Usage Declaration (Ready for Final Report & Course Submission)

Per HKU COMP7607 / COMP7608B guidelines and Proposal §7, below is the consolidated record of AI tools and models used in this project:

| Category | Tool / Model | How It Was Used in SoWScout2 | Human Verification by Team |
| :--- | :--- | :--- | :--- |
| **Code Scaffolding & UI/Harness Engineering** | **Claude Code** & **OpenAI Codex** | Used to adapt the team's `MedScout` agentic harness into the two-tier `sowscout` architecture (`workflow.py` + `harness.py`), build the web UI (`sowscout/web/`, `sowscout/ask/`), MCP server (`mcp_server.py`), deterministic calculator/registry tools, synthetic document templates, and test suites (`tests/`). | All tool schemas, safety boundaries, and gold case numbers were manually checked and tested against `python run.py test`. |
| **Metrics Alignment, Debugging & Evaluation Analysis** | **Google Antigravity** | Used to audit codebase alignment against the 6-page proposal PDF, implement exact `ELVS` (Eq. 1), $S_i/E_i/A_i$ component metrics, and `CCR` (Eq. 2) in `sowscout/evaluation.py`, configure `.env` + direct DeepSeek API support, refine `skills/property-purchase/SKILL.md` to eliminate down-payment double-counting, and document `dev`/`heldout` evaluation findings. | Verified via unit tests (`tests/test_agent.py`) and live evaluation runs on `dev` (`20261115-162336.md`) and `heldout` (`20261115-164639.md`). |
| **Runtime Agent Backbone LLMs (Subject of Study)** | **DeepSeek V3 (`deepseek-chat`)**, **Qwen 3.5 (`qwen3.5:9b` via Ollama)** | Used at runtime as the evaluated LLM backbones inside Systems A, B, and C to extract claims, plan tasks, invoke verification tools, and draft evidence-linked SoW memos. | Evaluated quantitatively via `ELVS`, `CCR`, Red-Flag Recall, False-Flag Rate, and funding-gap arithmetic error against gold labels. |
