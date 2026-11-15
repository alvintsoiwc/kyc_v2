# Start SoWScout2

Double-click **Start SoWScout.bat** in this folder. The launcher uses this copy's own `.venv`
and opens the console on **http://127.0.0.1:8767/**, choosing a nearby free port if necessary.
Both the launcher and `python run.py ui` now default to port 8767. If occupied, the server reserves the next available port (up to 29 further ports) and opens that actual address. `--port=8770` and `--port 8770` both work; `--port 0` asks Windows to choose a free port.

Keep the terminal open while using the app. Both original project folders are unchanged.

## Use it

1. **New run**: select a fictional case and Mock for an offline demo. The original claims,
   document verification, calculators, review controls, memos and officer-confirmed memory are retained.
2. **Ask**: chat with an installed Ollama model or a configured API model. Includes streamed answers,
   saved chats, cancellation, citations, web search, text/PDF/image attachments and model downloads.
3. **Results → Ask about this memo**: attaches a completed run's memo to a chat.
4. **Model connection**: enter OpenRouter, direct DeepSeek, OpenAI-compatible or Azure settings.
   Main connection API keys remain in the server process only and must be entered again after restart,
   or supplied as environment variables. Ask's optional Ollama web-search key is saved locally.
5. **Models & data**: inspect availability, test a model, preview routing or connect a SQLite file.
   Database queries are read-only. Run results label database rows as internal context, which cannot
   satisfy the supporting-evidence gate by themselves.

Ask defaults to Auto. It requires an available local model or an API key; the workflow's Mock provider
does not generate chat answers. The model IDs and initial prices are inherited from MedScout's model
configuration. Use **Refresh prices & status** and **Test** to verify availability for your account.
Edit aliases, model IDs, capabilities and prices in **Prompts & playbooks → config/models.json**.
OpenRouter aliases include `deepseek`, `gemini` and `claude`; `deepseek-direct` uses DeepSeek's own API.
For another compatible service, use the `openai` provider in that file and set its base URL/key under
Model connection. Add a model alias with that provider, its actual model ID, context limit and prices
to expose it in Ask's selector. Azure remains available through the workflow's direct OpenAI provider.

## Data and tools

- **SoW tools** in Ask provide policy search, company/property lookups and deterministic calculations.
  Settings defaults to policy and calculators. Choose a demo case for its synthetic registry records.
  These tools do not call live Companies or Land Registries. Policy notes and FX rates are bundled
  demonstrations, not refreshed legal guidance or market rates.
- Chat history, attachments, preferences and run outputs belong to this copy's `runs/` folder.
  Your existing projects' run history, virtual environments and credentials were not copied.
- Routed runs keep custom client documents and database data on local models unless **Allow routed
  cloud models** is enabled. Ask has a separate per-chat cloud control for attachments/database data.
  Choosing the workflow's direct OpenAI provider sends its context to that configured API endpoint.
  Web search sends queries to a search provider when enabled.
- API spending limits use estimated prices/tokens; actual billed totals can differ. Configure model
  prices rather than treating an unknown or zero price as a guarantee of free API access.

## Commands (PowerShell, from this folder)

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py ui --port 8767 --open
.\.venv\Scripts\python.exe -X utf8 run.py demo
.\.venv\Scripts\python.exe -X utf8 run.py run --case wong --provider router --model auto --max-cost 0.50
.\.venv\Scripts\python.exe -X utf8 run.py test
```

For a custom packet in router mode, use `--client`, `--materials`, and optionally `--registry`.
`--allow-cloud` permits cloud models to read the packet; `--use-database` enables the configured database.
The package and environment-variable prefix remain `sowscout` / `SOWSCOUT_` for compatibility;
the new folder is named `sowcout2` as requested.
