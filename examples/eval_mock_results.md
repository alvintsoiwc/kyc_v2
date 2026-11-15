# SoWScout evaluation 20261114-131345

provider `mock` · model `mock-scripted-policy` · temperature 0.0 · split `all` · runs per case 1

> MOCK provider: results validate the pipeline only; they are not evidence of model quality.

## Headline (micro-average over gold claims)

| system | gold claims | joint correct | joint correctness | red-flag recall | false-flag rate | evidence support | arithmetic errors | unsupported facts | tool calls | tokens in | cost USD | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 20 | 11 | 0.55 | 0.0 | 0.0 | 0.778 | 2 | 0 | 0 | 8237 | 0 | 0.01 |
| B | 20 | 20 | 1.0 | 1.0 | 0.0 | 1.0 | 0 | 0 | 83 | 199016 | 0 | 1.04 |
| C | 20 | 20 | 1.0 | 1.0 | 0.0 | 1.0 | 0 | 0 | 83 | 253758 | 0 | 1.01 |
| C-no-calc | 20 | 18 | 0.9 | 0.75 | 0.0 | 1.0 | 2 | 0 | 62 | 168147 | 0 | 0.81 |
| C-no-gate | 20 | 20 | 1.0 | 1.0 | 0.0 | 1.0 | 0 | 0 | 83 | 253758 | 0 | 1.07 |
| C-no-skills | 20 | 20 | 1.0 | 1.0 | 0.0 | 1.0 | 0 | 0 | 83 | 199016 | 0 | 1.07 |

## Per case (paired scorecard)

### chan
_clean salary, funded purchase, rental; earlier job undocumented_

| system | joint_correctness | red_flag_recall | false_flag_rate | unresolved_as_supported | macro_f1 | evidence_support | arithmetic_errors | funding_gap_abs_error | claim_f1 | field_accuracy | model_calls | tool_calls | gate_downgrades | tokens_in | wall_time_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 0.5 | – | 0.0 | 1.0 | 0.429 | 0.667 | 1 | – | 1.0 | 1.0 | 1 | 0 | 0 | 2073 | 0.01 |
| B | 1.0 | – | 0.0 | 0.0 | 1.0 | 1.0 | 0 | 0.0 | 1.0 | 1.0 | 16 | 19 | 0 | 47044 | 0.24 |
| C | 1.0 | – | 0.0 | 0.0 | 1.0 | 1.0 | 0 | 0.0 | 1.0 | 1.0 | 17 | 19 | 0 | 58417 | 0.22 |
| C-no-calc | 0.75 | – | 0.0 | 0.0 | 0.733 | 1.0 | 1 | – | 1.0 | 1.0 | 13 | 14 | 0 | 37819 | 0.18 |
| C-no-gate | 1.0 | – | 0.0 | 0.0 | 1.0 | 1.0 | 0 | 0.0 | 1.0 | 1.0 | 17 | 19 | 0 | 58417 | 0.29 |
| C-no-skills | 1.0 | – | 0.0 | 0.0 | 1.0 | 1.0 | 0 | 0.0 | 1.0 | 1.0 | 16 | 19 | 0 | 47044 | 0.26 |

- **A**: ✓ Harbourview (gold supported, got supported); ✗ Pearl Delta (gold unresolved, got supported); ✗ Lime Grove (gold supported, got supported, link/number wrong); ✓ Kingsford Court (gold supported, got supported)
- **B**: ✓ Harbourview (gold supported, got supported); ✓ Pearl Delta (gold unresolved, got unresolved); ✓ Lime Grove (gold supported, got supported); ✓ Kingsford Court (gold supported, got supported)
- **C**: ✓ Harbourview (gold supported, got supported); ✓ Pearl Delta (gold unresolved, got unresolved); ✓ Lime Grove (gold supported, got supported); ✓ Kingsford Court (gold supported, got supported)
- **C-no-calc**: ✓ Harbourview (gold supported, got supported); ✓ Pearl Delta (gold unresolved, got unresolved); ✗ Lime Grove (gold supported, got unresolved); ✓ Kingsford Court (gold supported, got supported)
- **C-no-gate**: ✓ Harbourview (gold supported, got supported); ✓ Pearl Delta (gold unresolved, got unresolved); ✓ Lime Grove (gold supported, got supported); ✓ Kingsford Court (gold supported, got supported)
- **C-no-skills**: ✓ Harbourview (gold supported, got supported); ✓ Pearl Delta (gold unresolved, got unresolved); ✓ Lime Grove (gold supported, got supported); ✓ Kingsford Court (gold supported, got supported)

### wong
_unexplained third-party credit and funding gap_

| system | joint_correctness | red_flag_recall | false_flag_rate | unresolved_as_supported | macro_f1 | evidence_support | arithmetic_errors | funding_gap_abs_error | claim_f1 | field_accuracy | model_calls | tool_calls | gate_downgrades | tokens_in | wall_time_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 0.667 | 0.0 | 0.0 | – | 0.4 | 0.667 | 1 | – | 1.0 | 1.0 | 1 | 0 | 0 | 1482 | 0.0 |
| B | 1.0 | 1.0 | 0.0 | – | 1.0 | 1.0 | 0 | 0.0 | 1.0 | 1.0 | 13 | 15 | 0 | 36720 | 0.18 |
| C | 1.0 | 1.0 | 0.0 | – | 1.0 | 1.0 | 0 | 0.0 | 1.0 | 1.0 | 14 | 15 | 0 | 46936 | 0.18 |
| C-no-calc | 0.667 | 0.0 | 0.0 | – | 0.333 | 1.0 | 1 | – | 1.0 | 1.0 | 11 | 11 | 0 | 31302 | 0.14 |
| C-no-gate | 1.0 | 1.0 | 0.0 | – | 1.0 | 1.0 | 0 | 0.0 | 1.0 | 1.0 | 14 | 15 | 0 | 46936 | 0.18 |
| C-no-skills | 1.0 | 1.0 | 0.0 | – | 1.0 | 1.0 | 0 | 0.0 | 1.0 | 1.0 | 13 | 15 | 0 | 36720 | 0.22 |

- **A**: ✓ Silverline & per month (gold supported, got supported); ✓ bonus (gold supported, got supported); ✗ Harbour Crest (gold potential_red_flag, got supported)
- **B**: ✓ Silverline & per month (gold supported, got supported); ✓ bonus (gold supported, got supported); ✓ Harbour Crest (gold potential_red_flag, got potential_red_flag)
- **C**: ✓ Silverline & per month (gold supported, got supported); ✓ bonus (gold supported, got supported); ✓ Harbour Crest (gold potential_red_flag, got potential_red_flag)
- **C-no-calc**: ✓ Silverline & per month (gold supported, got supported); ✓ bonus (gold supported, got supported); ✗ Harbour Crest (gold potential_red_flag, got unresolved)
- **C-no-gate**: ✓ Silverline & per month (gold supported, got supported); ✓ bonus (gold supported, got supported); ✓ Harbour Crest (gold potential_red_flag, got potential_red_flag)
- **C-no-skills**: ✓ Silverline & per month (gold supported, got supported); ✓ bonus (gold supported, got supported); ✓ Harbour Crest (gold potential_red_flag, got potential_red_flag)

### lee
_company-record problem and payslip / tax mismatch_

| system | joint_correctness | red_flag_recall | false_flag_rate | unresolved_as_supported | macro_f1 | evidence_support | arithmetic_errors | funding_gap_abs_error | claim_f1 | field_accuracy | model_calls | tool_calls | gate_downgrades | tokens_in | wall_time_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 0.667 | 0.0 | 0.0 | – | 0.4 | 0.667 | 0 | – | 1.0 | 1.0 | 1 | 0 | 0 | 1248 | 0.0 |
| B | 1.0 | 1.0 | 0.0 | – | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 11 | 12 | 0 | 27788 | 0.15 |
| C | 1.0 | 1.0 | 0.0 | – | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 12 | 12 | 0 | 35948 | 0.14 |
| C-no-calc | 1.0 | 1.0 | 0.0 | – | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 9 | 9 | 0 | 22823 | 0.12 |
| C-no-gate | 1.0 | 1.0 | 0.0 | – | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 12 | 12 | 0 | 35948 | 0.17 |
| C-no-skills | 1.0 | 1.0 | 0.0 | – | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 11 | 12 | 0 | 27788 | 0.13 |

- **A**: ✗ Golden Crane (gold potential_red_flag, got supported); ✓ Eastwind (gold supported, got supported); ✓ Wing Fat (gold supported, got supported)
- **B**: ✓ Golden Crane (gold potential_red_flag, got potential_red_flag); ✓ Eastwind (gold supported, got supported); ✓ Wing Fat (gold supported, got supported)
- **C**: ✓ Golden Crane (gold potential_red_flag, got potential_red_flag); ✓ Eastwind (gold supported, got supported); ✓ Wing Fat (gold supported, got supported)
- **C-no-calc**: ✓ Golden Crane (gold potential_red_flag, got potential_red_flag); ✓ Eastwind (gold supported, got supported); ✓ Wing Fat (gold supported, got supported)
- **C-no-gate**: ✓ Golden Crane (gold potential_red_flag, got potential_red_flag); ✓ Eastwind (gold supported, got supported); ✓ Wing Fat (gold supported, got supported)
- **C-no-skills**: ✓ Golden Crane (gold potential_red_flag, got potential_red_flag); ✓ Eastwind (gold supported, got supported); ✓ Wing Fat (gold supported, got supported)

### ho
_conflicting narrative, sale price conflict, unevidenced sale proceeds, business income_

| system | joint_correctness | red_flag_recall | false_flag_rate | unresolved_as_supported | macro_f1 | evidence_support | arithmetic_errors | funding_gap_abs_error | claim_f1 | field_accuracy | model_calls | tool_calls | gate_downgrades | tokens_in | wall_time_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 0.25 | 0.0 | 0.0 | 0.5 | 0.222 | 1.0 | 0 | – | 1.0 | 1.0 | 1 | 0 | 0 | 1298 | 0.0 |
| B | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 14 | 14 | 0 | 35453 | 0.2 |
| C | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 15 | 14 | 0 | 44603 | 0.19 |
| C-no-calc | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 12 | 10 | 0 | 30694 | 0.15 |
| C-no-gate | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 15 | 14 | 0 | 44603 | 0.17 |
| C-no-skills | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 14 | 14 | 0 | 35453 | 0.17 |

- **A**: ✗ May 2022 & Bayview (gold potential_red_flag, got supported); ✗ Seaview (gold unresolved, got supported); ✓ Mei Advisory (gold unresolved, got unresolved); ✗ 2021 & Bayview (gold potential_red_flag, got supported)
- **B**: ✓ May 2022 & Bayview (gold potential_red_flag, got potential_red_flag); ✓ Seaview (gold unresolved, got unresolved); ✓ Mei Advisory (gold unresolved, got unresolved); ✓ 2021 & Bayview (gold potential_red_flag, got potential_red_flag)
- **C**: ✓ May 2022 & Bayview (gold potential_red_flag, got potential_red_flag); ✓ Seaview (gold unresolved, got unresolved); ✓ Mei Advisory (gold unresolved, got unresolved); ✓ 2021 & Bayview (gold potential_red_flag, got potential_red_flag)
- **C-no-calc**: ✓ May 2022 & Bayview (gold potential_red_flag, got potential_red_flag); ✓ Seaview (gold unresolved, got unresolved); ✓ Mei Advisory (gold unresolved, got unresolved); ✓ 2021 & Bayview (gold potential_red_flag, got potential_red_flag)
- **C-no-gate**: ✓ May 2022 & Bayview (gold potential_red_flag, got potential_red_flag); ✓ Seaview (gold unresolved, got unresolved); ✓ Mei Advisory (gold unresolved, got unresolved); ✓ 2021 & Bayview (gold potential_red_flag, got potential_red_flag)
- **C-no-skills**: ✓ May 2022 & Bayview (gold potential_red_flag, got potential_red_flag); ✓ Seaview (gold unresolved, got unresolved); ✓ Mei Advisory (gold unresolved, got unresolved); ✓ 2021 & Bayview (gold potential_red_flag, got potential_red_flag)

### ng
_third-party gift and incomplete documents_

| system | joint_correctness | red_flag_recall | false_flag_rate | unresolved_as_supported | macro_f1 | evidence_support | arithmetic_errors | funding_gap_abs_error | claim_f1 | field_accuracy | model_calls | tool_calls | gate_downgrades | tokens_in | wall_time_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 0.667 | – | 0.0 | 0.5 | 0.667 | 1.0 | 0 | – | 1.0 | 1.0 | 1 | 0 | 0 | 1070 | 0.0 |
| B | 1.0 | – | 0.0 | 0.0 | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 12 | 15 | 0 | 30501 | 0.16 |
| C | 1.0 | – | 0.0 | 0.0 | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 13 | 15 | 0 | 39335 | 0.16 |
| C-no-calc | 1.0 | – | 0.0 | 0.0 | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 10 | 12 | 0 | 25830 | 0.12 |
| C-no-gate | 1.0 | – | 0.0 | 0.0 | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 13 | 15 | 0 | 39335 | 0.15 |
| C-no-skills | 1.0 | – | 0.0 | 0.0 | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 12 | 15 | 0 | 30501 | 0.17 |

- **A**: ✓ Kowloon Bay (gold supported, got supported); ✓ gave me (gold unresolved, got unresolved); ✗ Sunshine City (gold unresolved, got supported)
- **B**: ✓ Kowloon Bay (gold supported, got supported); ✓ gave me (gold unresolved, got unresolved); ✓ Sunshine City (gold unresolved, got unresolved)
- **C**: ✓ Kowloon Bay (gold supported, got supported); ✓ gave me (gold unresolved, got unresolved); ✓ Sunshine City (gold unresolved, got unresolved)
- **C-no-calc**: ✓ Kowloon Bay (gold supported, got supported); ✓ gave me (gold unresolved, got unresolved); ✓ Sunshine City (gold unresolved, got unresolved)
- **C-no-gate**: ✓ Kowloon Bay (gold supported, got supported); ✓ gave me (gold unresolved, got unresolved); ✓ Sunshine City (gold unresolved, got unresolved)
- **C-no-skills**: ✓ Kowloon Bay (gold supported, got supported); ✓ gave me (gold unresolved, got unresolved); ✓ Sunshine City (gold unresolved, got unresolved)

### cheung
_returning client with officer-verified memory_

| system | joint_correctness | red_flag_recall | false_flag_rate | unresolved_as_supported | macro_f1 | evidence_support | arithmetic_errors | funding_gap_abs_error | claim_f1 | field_accuracy | model_calls | tool_calls | gate_downgrades | tokens_in | wall_time_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 0.667 | – | 0.0 | – | 1.0 | 0.667 | 0 | – | 1.0 | 1.0 | 1 | 0 | 0 | 1066 | 0.0 |
| B | 1.0 | – | 0.0 | – | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 9 | 8 | 0 | 21510 | 0.11 |
| C | 1.0 | – | 0.0 | – | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 10 | 8 | 0 | 28519 | 0.12 |
| C-no-calc | 1.0 | – | 0.0 | – | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 8 | 6 | 0 | 19679 | 0.1 |
| C-no-gate | 1.0 | – | 0.0 | – | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 10 | 8 | 0 | 28519 | 0.11 |
| C-no-skills | 1.0 | – | 0.0 | – | 1.0 | 1.0 | 0 | – | 1.0 | 1.0 | 9 | 8 | 0 | 21510 | 0.12 |

- **A**: ✓ Tai Ping (gold supported, got supported); ✗ purchased & Grand Marine (gold supported, got supported, link/number wrong); ✓ sold & Grand Marine (gold supported, got supported)
- **B**: ✓ Tai Ping (gold supported, got supported); ✓ purchased & Grand Marine (gold supported, got supported); ✓ sold & Grand Marine (gold supported, got supported)
- **C**: ✓ Tai Ping (gold supported, got supported); ✓ purchased & Grand Marine (gold supported, got supported); ✓ sold & Grand Marine (gold supported, got supported)
- **C-no-calc**: ✓ Tai Ping (gold supported, got supported); ✓ purchased & Grand Marine (gold supported, got supported); ✓ sold & Grand Marine (gold supported, got supported)
- **C-no-gate**: ✓ Tai Ping (gold supported, got supported); ✓ purchased & Grand Marine (gold supported, got supported); ✓ sold & Grand Marine (gold supported, got supported)
- **C-no-skills**: ✓ Tai Ping (gold supported, got supported); ✓ purchased & Grand Marine (gold supported, got supported); ✓ sold & Grand Marine (gold supported, got supported)

## Counterfactual robustness

| edit | kind | system | expected behaviour rate | detail |
|---|---|---|---|---|
| cf_lee_remove_letter | (i) remove a key supporting document | A | 0.0 | Eastwind: gold unresolved, got supported |
| cf_lee_remove_letter | (i) remove a key supporting document | B | 1.0 | Eastwind: gold unresolved, got unresolved |
| cf_lee_remove_letter | (i) remove a key supporting document | C | 1.0 | Eastwind: gold unresolved, got unresolved |
| cf_lee_remove_letter | (i) remove a key supporting document | C-no-calc | 1.0 | Eastwind: gold unresolved, got unresolved |
| cf_lee_remove_letter | (i) remove a key supporting document | C-no-gate | 1.0 | Eastwind: gold unresolved, got unresolved |
| cf_lee_remove_letter | (i) remove a key supporting document | C-no-skills | 1.0 | Eastwind: gold unresolved, got unresolved |
| cf_ng_salary_conflict | (ii) change a material amount to conflict with evidence | A | 0.0 | Kowloon Bay: gold potential_red_flag, got supported |
| cf_ng_salary_conflict | (ii) change a material amount to conflict with evidence | B | 1.0 | Kowloon Bay: gold potential_red_flag, got potential_red_flag |
| cf_ng_salary_conflict | (ii) change a material amount to conflict with evidence | C | 1.0 | Kowloon Bay: gold potential_red_flag, got potential_red_flag |
| cf_ng_salary_conflict | (ii) change a material amount to conflict with evidence | C-no-calc | 1.0 | Kowloon Bay: gold potential_red_flag, got potential_red_flag |
| cf_ng_salary_conflict | (ii) change a material amount to conflict with evidence | C-no-gate | 1.0 | Kowloon Bay: gold potential_red_flag, got potential_red_flag |
| cf_ng_salary_conflict | (ii) change a material amount to conflict with evidence | C-no-skills | 1.0 | Kowloon Bay: gold potential_red_flag, got potential_red_flag |
| cf_cheung_paraphrase | (iii) paraphrase without changing facts | A | 1.0 | Tai Ping: gold supported, got supported; sold & Grand Marine: gold supported, got supported |
| cf_cheung_paraphrase | (iii) paraphrase without changing facts | B | 1.0 | Tai Ping: gold supported, got supported; sold & Grand Marine: gold supported, got supported |
| cf_cheung_paraphrase | (iii) paraphrase without changing facts | C | 1.0 | Tai Ping: gold supported, got supported; sold & Grand Marine: gold supported, got supported |
| cf_cheung_paraphrase | (iii) paraphrase without changing facts | C-no-calc | 1.0 | Tai Ping: gold supported, got supported; sold & Grand Marine: gold supported, got supported |
| cf_cheung_paraphrase | (iii) paraphrase without changing facts | C-no-gate | 1.0 | Tai Ping: gold supported, got supported; sold & Grand Marine: gold supported, got supported |
| cf_cheung_paraphrase | (iii) paraphrase without changing facts | C-no-skills | 1.0 | Tai Ping: gold supported, got supported; sold & Grand Marine: gold supported, got supported |
