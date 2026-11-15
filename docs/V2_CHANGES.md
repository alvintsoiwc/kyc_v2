# SoWScout2 feature comparison

| Area | Original SoWScout | New copy |
|---|---|---|
| Ask | Absent | Streaming chat, history, stop/rename/delete, attachments, citations, web search |
| Domain tools in Ask | Absent | SoW policy, synthetic registries, timeline and consistency calculators |
| Run-to-chat | Absent | Attach the completed SoW memo from Results |
| API models | Direct Ollama/OpenAI-compatible/Azure workflow calls | Adds OpenRouter, direct DeepSeek and configurable compatible providers through a shared router |
| Model management | Connection form | Model catalog, availability, tests, routing preview, editable model configuration |
| Routing | One fixed provider | Per-step selection, failure escalation, privacy checks, estimated cost limits |
| Internal SQLite | No connector | Read-only Ask/run access, table inspection, separately labeled internal evidence |
| Launch | Manual CLI | Windows/macOS launchers, isolated environment, port conflict handling, UTF-8 support |
| Original SoW workflow | Claims, evidence, calculations, memo, review, memory, evaluation | Preserved and regression tested |

Medical database adapters were replaced by the existing SoW domain tools. No FDA, PubMed or clinical-trial
data is used as source-of-wealth evidence. Live official registry integrations still require separately
configured services; no live verification is claimed.

Validation uses synthetic data and local fake Ollama/API servers. Paid API endpoints were not exercised
with real credentials. Browser screenshots in `examples/ui-v2/` show the synthetic test environment.
