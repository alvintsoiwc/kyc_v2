/* SoWScout console — vanilla JS single-page app talking to sowscout/web/server.py. */
"use strict";

// ------------------------------------------------------------------ helpers
const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === "style") el.setAttribute("style", v);
    else if (["value", "checked", "disabled", "selected", "hidden", "open", "multiple"].includes(k)) el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
  return el;
}

async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  let data = {};
  try { data = await r.json(); } catch (e) { /* non-JSON */ }
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

function toast(msg, bad) {
  const t = h("div", { class: "toast" + (bad ? " bad" : ""), role: bad ? "alert" : "status", text: msg });
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), bad ? 7000 : 3500);
}

const store = {
  get(k, d) { try { const v = localStorage.getItem("sowscout." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("sowscout." + k, JSON.stringify(v)); } catch (e) { /* ignore */ } },
};

const fmtNum = (n) => (n === null || n === undefined ? "–" : Number(n).toLocaleString());
const fmtCost = (n) => "$" + Number(n || 0).toFixed(4);
const pretty = (o) => JSON.stringify(o, null, 2);
const VERDICT_LABEL = { supported: "Supported", unresolved: "Unresolved", potential_red_flag: "Potential red flag" };
const verdictPill = (v) => h("span", { class: "v " + v, text: VERDICT_LABEL[v] || v });
const statusPill = (s) => h("span", { class: "pill " + s, text: { waiting: "waiting for you", interrupted: "interrupted" }[s] || s });
const PHASES = [["intake", "Intake"], ["extract_claims", "Extract claims"], ["plan", "Plan"], ["verify", "Verify"],
  ["sufficiency", "Evidence check"], ["reconcile", "Reconcile"], ["gate", "Gate"], ["review", "Review"], ["memo", "Memo"]];
const SYSTEM_INFO = { "B": "B — tools, no playbooks, no gate", "C": "C — tools + playbooks + citation gate (default)",
  "C-no-calc": "C without the calculator (ablation)", "C-no-gate": "C without the gate (ablation)", "C-no-skills": "C without playbooks (ablation)" };

function field(label, input, help) {
  return h("label", { class: "field" }, h("span", { text: label }), input, help ? h("span", { class: "help", text: help }) : null);
}
function check(id, label, help, checked) {
  return h("label", { class: "check", for: id },
    h("input", { type: "checkbox", id, checked: !!checked }),
    h("span", {}, label, help ? h("small", { text: help }) : null));
}
function select(id, options, value) {
  return h("select", { id }, options.map(([v, l]) => h("option", { value: v, text: l, selected: v === value })));
}
function seg(name, options, value) {
  return h("div", { class: "seg", role: "radiogroup" }, options.map(([v, l]) =>
    h("label", {}, h("input", { type: "radio", name, value: v, checked: v === value }), l)));
}
const segValue = (name) => (document.querySelector(`input[name="${name}"]:checked`) || {}).value;

// ------------------------------------------------------------------ markdown (for the memo)
const INLINE = /`([^`]+)`|\*\*(.+?)\*\*|\[([^\]]+)\]\((https?:[^)\s]+)\)|(?<=^|[\s(])_(\S(?:.*?\S)?)_(?=$|[\s.,;:!?)])|(https?:\/\/[^\s<|]+)/g;
function inline(text) {
  const out = [];
  let last = 0;
  text.replace(INLINE, (m, code, bold, ltext, lurl, ital, url, off) => {
    if (off > last) out.push(text.slice(last, off));
    if (code !== undefined) out.push(h("code", { text: code }));
    else if (bold !== undefined) out.push(h("strong", {}, inline(bold)));
    else if (ltext !== undefined) out.push(h("a", { href: lurl, target: "_blank", rel: "noopener", text: ltext }));
    else if (ital !== undefined) out.push(h("em", {}, inline(ital)));
    else if (url !== undefined) out.push(h("a", { href: url, target: "_blank", rel: "noopener", text: url }));
    last = off + m.length;
    return m;
  });
  if (last < text.length) out.push(text.slice(last));
  return out;
}
function markdown(src) {
  const lines = src.replace(/\r/g, "").split("\n");
  const root = h("div", { class: "md" });
  const isBlock = (l) => /^(#{1,4}\s|```|>|\s*\||\s*[-*]\s+|\s*\d+\.\s+)/.test(l);
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    let m;
    if (!l.trim()) { i++; continue; }
    if ((m = l.match(/^(#{1,4})\s+(.*)$/))) { root.appendChild(h("h" + m[1].length, {}, inline(m[2]))); i++; continue; }
    if (l.startsWith("```")) {
      const buf = []; i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++; root.appendChild(h("pre", { class: "json" }, h("code", { text: buf.join("\n") }))); continue;
    }
    if (l.startsWith(">")) {
      const q = h("blockquote");
      while (i < lines.length && lines[i].startsWith(">")) { q.appendChild(h("p", {}, inline(lines[i].replace(/^>\s?/, "")))); i++; }
      root.appendChild(q); continue;
    }
    if (/^\s*\|/.test(l)) {
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(rows[0]);
      const body = rows.slice(1).filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r)).map(cells);
      root.appendChild(h("div", { class: "tbl" }, h("table", {},
        h("thead", {}, h("tr", {}, head.map((c) => h("th", {}, inline(c))))),
        h("tbody", {}, body.map((r) => h("tr", {}, r.map((c) => h("td", {}, inline(c)))))))));
      continue;
    }
    if (/^\s*[-*]\s+/.test(l) || /^\s*\d+\.\s+/.test(l)) {
      const ordered = /^\s*\d+\.\s+/.test(l);
      const list = h(ordered ? "ol" : "ul");
      const rx = ordered ? /^\s*\d+\.\s+/ : /^\s*[-*]\s+/;
      while (i < lines.length && rx.test(lines[i])) list.appendChild(h("li", {}, inline(lines[i++].replace(rx, ""))));
      root.appendChild(list); continue;
    }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !(buf.length && isBlock(lines[i]))) buf.push(lines[i++].replace(/\s+$/, ""));
    root.appendChild(h("p", {}, inline(buf.join(" "))));
  }
  return root;
}

// ------------------------------------------------------------------ state
const S = {
  config: null, runId: store.get("runId", null), run: null, events: [], evNext: 0,
  evFilter: store.get("evFilter", "all"), autoscroll: true, pendingId: null, uploads: [],
  built: {}, resultsTab: "memo", verdictFilter: "", file: null, fileDirty: false,
};

function setRun(id) {
  if (S.runId !== id) { S.events = []; S.evNext = 0; S.pendingId = null; S.run = null; const f = $("#feed"); if (f) fill(f); }
  S.runId = id;
  store.set("runId", id);
}

// ------------------------------------------------------------------ router
const VIEWS = ["new", "control", "results", "history", "ask", "models", "tools", "files", "eval", "connection"];
function route() {
  const name = (location.hash || "#new").slice(1);
  const view = VIEWS.includes(name) ? name : "new";
  for (const v of VIEWS) $("#view-" + v).hidden = v !== view;
  document.querySelectorAll("nav.tabs a").forEach((a) => a.setAttribute("aria-current", a.getAttribute("href") === "#" + view ? "page" : "false"));
  const build = { new: buildNew, control: buildControl, results: buildResults, history: buildHistory, ask: buildAsk, models: buildModels, tools: buildTools,
    files: buildFiles, eval: buildEval, connection: buildConnection }[view];
  if (!S.built[view]) { build(); S.built[view] = true; }
  if (view === "control") { redrawFeed(); renderControl([]); }
  if (view === "results") renderResults(true);
  if (view === "history") refreshHistory();
  if (view === "eval") refreshEval();
  document.body.classList.toggle("ask-mode", view === "ask");
  if (view === "ask") sizeAsk();
  if (view === "models") refreshModels(false);
}

// ------------------------------------------------------------------ NEW RUN
const LIMIT_INFO = {
  max_tasks: ["Max verification tasks", "Claims beyond this are reported as not verified."],
  max_evidence_rounds: ["Evidence rounds", "How often missing documents may be requested and re-checked."],
  run_deadline_s: ["Run time budget (s)", "Waiting for you does not count."],
  max_steps_per_task: ["Model decisions per task", "Step budget of the verification loop."],
  max_tool_calls_per_task: ["Tool calls per task", ""],
  max_calls_per_batch: ["Parallel calls per decision", "Independent reads run together."],
  max_format_repairs: ["Format repairs", "Retries after malformed model output."],
  max_verify_revisions: ["Gate revisions", "Chances to fix a finding the citation gate rejected."],
  task_deadline_s: ["Task time budget (s)", ""],
  tool_timeout_s: ["Tool timeout (s)", ""],
  tool_max_retries: ["Retries for transient tool errors", "Timeouts, 429, 5xx only."],
  retry_base_delay_s: ["Retry base delay (s)", "Exponential backoff with jitter."],
  context_window: ["Context window (tokens)", "Older tool results are compressed to fit."],
  reserved_output: ["Reserved for output (tokens)", ""],
  max_records_per_observation: ["Records per tool result", "Shown to the model; the rest stays in the evidence store."],
  max_cost_usd: ["Cost cap (USD)", "0 = no cap. A task stops when the run's estimated cost reaches it."],
};
const FLOAT_LIMITS = new Set(["run_deadline_s", "task_deadline_s", "tool_timeout_s", "retry_base_delay_s", "max_cost_usd"]);
const FLAG_INFO = {
  review_claims: ["Review claims before planning", "Drop claims, fix wording or change the category."],
  review_plan: ["Review the verification plan", "Reorder, drop or edit tasks and pick the playbook for each."],
  approve_tools: ["Approve every tool call", "See each proposed batch; edit arguments or reject with a note."],
  step_mode: ["Step through every decision", "The run pauses before each model decision."],
  ask_reviewer: ["Answer the agent's questions", "Off: the agent records its doubts as open questions instead."],
  request_evidence: ["Supply missing documents", "When evidence is missing, upload documents and the planner re-checks those claims."],
};
const PRESETS = {
  watch: { review_claims: false, review_plan: false, approve_tools: false, step_mode: false, ask_reviewer: true, request_evidence: false },
  review: { review_claims: true, review_plan: true, approve_tools: false, step_mode: false, ask_reviewer: true, request_evidence: true },
  full: { review_claims: true, review_plan: true, approve_tools: true, step_mode: true, ask_reviewer: true, request_evidence: true },
  auto: { review_claims: false, review_plan: false, approve_tools: false, step_mode: false, ask_reviewer: false, request_evidence: false },
};

function buildNew() {
  const cfg = S.config, d = cfg.defaults, v = $("#view-new");
  const cases = cfg.cases.map((c) => [c.case, `${c.client} (${c.case}, ${c.split})`]);
  const caseInfo = h("div", { class: "small muted", id: "case-info" });
  const fileInput = h("input", { type: "file", id: "upload", multiple: true, accept: ".md,.txt,.pdf", hidden: true });
  const fileList = h("div", { id: "upload-list", class: "small" });
  const drop = h("div", { class: "drop", id: "drop" }, "Drop .md, .txt or .pdf files here, or ",
    h("button", { type: "button", class: "small", on: { click: () => fileInput.click() } }, "choose files"));
  const addFiles = async (files) => {
    for (const f of files) {
      if (!/\.(md|txt|pdf)$/i.test(f.name)) { toast(`${f.name}: only .md, .txt and .pdf are read`, true); continue; }
      const data = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] || ""); r.readAsDataURL(f); });
      S.uploads = S.uploads.filter((u) => u.name !== f.name).concat([{ name: f.name, size: f.size, data_b64: data }]);
    }
    renderUploads();
  };
  fileInput.addEventListener("change", () => addFiles(fileInput.files));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); addFiles(e.dataTransfer.files); });
  function renderUploads() {
    fill(fileList, ...S.uploads.map((u) => h("div", { class: "row" }, h("span", { class: "mono", text: u.name }),
      h("span", { class: "muted", text: `${(u.size / 1024).toFixed(1)} KB` }),
      h("button", { type: "button", class: "small", on: { click: () => { S.uploads = S.uploads.filter((x) => x !== u); renderUploads(); } } }, "Remove"))));
  }

  const srcCase = h("div", { id: "src-case", class: "grid2" },
    field("Demo case", select("case", cases, store.get("case", cases[0] && cases[0][0])), "Fictional clients with synthetic documents and mock registries."),
    h("div", {}, caseInfo));
  const srcUpload = h("div", { id: "src-upload", class: "grid2", hidden: true },
    h("div", { style: "display:grid;gap:10px" }, drop, fileInput, fileList),
    h("div", { class: "callout warn small" }, "Use SYNTHETIC documents only. Include the client declaration (",
      h("code", { text: "Document type: declaration" }), "). Uploaded packets have no mock registry, so the registry tools report 'unavailable' and those checks stay unresolved."));

  const flagChecks = Object.entries(FLAG_INFO).map(([k, [l, hlp]]) => check("flag-" + k, l, hlp, PRESETS.review[k]));
  const limitInputs = Object.entries(cfg.limits).map(([k, val]) => field((LIMIT_INFO[k] || [k])[0],
    h("input", { type: "number", id: "lim-" + k, value: val, min: FLOAT_LIMITS.has(k) ? "0" : "1", step: FLOAT_LIMITS.has(k) ? "0.1" : "1" }),
    (LIMIT_INFO[k] || [, ""])[1]));
  const focusChecks = [
    ...Object.keys(cfg.themes).map((t) => check("focus-" + t, "Theme: " + t,
      cfg.themes[t].join(", "), false)),
    ...cfg.categories.map((c) => check("focus-" + c, "Category: " + c, "", false)),
  ];

  fill(v, 
    h("div", { class: "panel" },
      h("header", {}, h("div", {}, h("h2", { text: "Client and evidence packet" }),
        h("p", { class: "muted small", text: "Pick a demo case or upload a declaration with payslips, tax notices, bank statements and property papers." })),
        seg("src", [["case", "Demo case"], ["upload", "My documents"]], "case")),
      h("div", { style: "display:grid;gap:14px" }, srcCase, srcUpload,
        h("div", { class: "grid2" },
          field("Client name", h("input", { type: "text", id: "client", placeholder: "e.g. Wong Ka Yan" }), "For a demo case, leave blank to use the case's name."),
          field("Client reference", h("input", { type: "text", id: "client-ref", placeholder: "internal reference, never an HKID" }), "Optional.")))),
    h("div", { class: "grid2" },
      h("div", { class: "panel" },
        h("header", {}, h("h2", { text: "Model and system" })),
        h("div", { class: "grid2" },
          field("Provider", select("provider", [["router", "Auto / API model router"], ["mock", "Mock (offline, scripted)"], ["ollama", "Ollama (local model)"], ["openai", "OpenAI-compatible / Azure"]], d.provider)),
          field("Model", h("input", { type: "text", id: "model", value: d.model, placeholder: d.default_models[d.provider] }), "Blank = provider default. Router: auto or an alias from Models & data."),
          field("Temperature", h("input", { type: "number", id: "temperature", value: d.temperature, min: "0", max: "2", step: "0.1" })),
          field("System variant", select("system", cfg.systems.map((x) => [x, SYSTEM_INFO[x] || x]), d.system)),
          h("label", { class: "check", for: "reviewer" }, h("input", { type: "checkbox", id: "reviewer", checked: !!d.reviewer }),
            h("span", {}, "Independent reviewer", h("small", { text: "Optional fresh-context check of cited spans (no tools)." }))),
          check("allow-cloud", "Allow routed cloud models to read client documents", "Off keeps private documents on local models in router mode. Direct OpenAI mode sends them to your configured endpoint.", false),
          check("use-database", "Let the agent query my database", "Read-only internal context; configure in Models & data.", false),
          field("Tool transport", select("transport", [["local", "In-process functions"], ["mcp", "MCP server (FastMCP)"]], d.tool_transport)),
          h("div", { class: "grid2" },
            field("$ / 1M input tokens", h("input", { type: "number", id: "price-in", value: d.price_in_per_m, min: "0", step: "0.01" })),
            field("$ / 1M output tokens", h("input", { type: "number", id: "price-out", value: d.price_out_per_m, min: "0", step: "0.01" })))),
        h("p", { class: "small muted" }, "Endpoints and API keys are set on the ", h("a", { href: "#connection", text: "Model connection" }), " tab.")),
      h("div", { class: "panel" },
        h("header", {}, h("div", {}, h("h2", { text: "How much control" }), h("p", { class: "muted small", text: "You can change these while the run is going." })),
          h("div", { class: "row" }, ...[["watch", "Just watch"], ["review", "Review plan"], ["full", "Full control"], ["auto", "Hands-off"]].map(([k, l]) =>
            h("button", { type: "button", class: "small", on: { click: () => applyPreset(k) } }, l)))),
        h("fieldset", {}, flagChecks))),
    h("div", { class: "panel" },
      h("details", {}, h("summary", { text: "Scope: limit the request to some themes or categories" }),
        h("p", { class: "small muted", text: "Nothing ticked = verify every claim. Claims outside the focus are listed as out of scope." }),
        h("div", { class: "grid3" }, focusChecks))),
    h("div", { class: "panel" },
      h("details", {}, h("summary", { text: "Budgets and limits" }),
        h("div", { class: "grid4" }, limitInputs),
        h("div", { class: "row", style: "margin-top:12px" }, h("button", { type: "button", class: "small", on: { click: () => {
          for (const [k, val] of Object.entries(cfg.limits)) $("#lim-" + k).value = val; } } }, "Reset to defaults")))),
    h("div", { class: "panel" },
      h("details", {}, h("summary", { text: "Fault injection (reliability testing)" }),
        h("div", { class: "grid2" },
          field("Tool faults", h("input", { type: "text", id: "faults", placeholder: "lookup_company=timeout*2,lookup_property=unavailable*20" }),
            "tool=kind*count; kinds: timeout, error, unavailable. Use * as the tool name for every tool."),
          field("Model faults (mock provider only)", h("input", { type: "text", id: "mock-faults", placeholder: "malformed:1,ungrounded:1" }),
            "malformed = invalid JSON once; ungrounded = cites a non-existent evidence id once.")),
        h("div", { class: "row", style: "margin-top:10px" },
          ...[["One registry timeout", "lookup_company=timeout*1"], ["Land Registry down", "lookup_property=unavailable*50"],
            ["Every tool flaky", "*=timeout*3"], ["Clear", ""]].map(([l, val]) =>
            h("button", { type: "button", class: "small", on: { click: () => { $("#faults").value = val; } } }, l))))),
    h("div", { class: "row end" }, h("span", { class: "muted small", id: "start-msg" }),
      h("button", { type: "button", class: "primary", id: "start", on: { click: startRun } }, "Start run")),
  );

  const showCase = () => {
    const c = cfg.cases.find((x) => x.case === $("#case").value);
    if (!c) return;
    store.set("case", c.case);
    fill(caseInfo, h("p", { text: c.description }), h("p", {}, h("b", { text: "Packet: " }), c.materials.join(", ")),
      c.memory ? h("p", { class: "small" }, h("b", { text: "Returning client: " }), `${c.memory} officer-verified fact(s) from an earlier review are loaded into client memory.`) : null);
    $("#client").placeholder = c.client;
  };
  $("#case").addEventListener("change", showCase);
  showCase();
  document.querySelectorAll('input[name="src"]').forEach((r) => r.addEventListener("change", () => {
    const up = segValue("src") === "upload";
    srcCase.hidden = up; srcUpload.hidden = !up;
  }));
  $("#provider").addEventListener("change", () => { $("#model").placeholder = d.default_models[$("#provider").value] || ""; });
  applyPreset(store.get("preset", "review"));
}

function applyPreset(k) {
  for (const [f, on] of Object.entries(PRESETS[k])) { const el = $("#flag-" + f); if (el) el.checked = on; }
  store.set("preset", k);
}

function modelSettings() {
  return {
    allow_cloud: $("#allow-cloud").checked, use_database: $("#use-database").checked,
    provider: $("#provider").value, model: $("#model").value.trim(), temperature: $("#temperature").value,
    system: $("#system").value, reviewer: $("#reviewer").checked, tool_transport: $("#transport").value,
    price_in_per_m: $("#price-in").value, price_out_per_m: $("#price-out").value,
  };
}

async function startRun() {
  const cfg = S.config, btn = $("#start");
  const src = segValue("src");
  const body = {
    client: $("#client").value.trim(), client_ref: $("#client-ref").value.trim(),
    settings: modelSettings(), limits: {}, control: {},
    focus: [...Object.keys(cfg.themes), ...cfg.categories].filter((f) => $("#focus-" + f).checked),
    faults: $("#faults").value.trim(), mock_faults: $("#mock-faults").value.trim(),
  };
  if (src === "case") body.case = $("#case").value;
  else body.uploads = S.uploads;
  for (const k of Object.keys(cfg.limits)) body.limits[k] = $("#lim-" + k).value;
  for (const k of Object.keys(FLAG_INFO)) body.control[k] = $("#flag-" + k).checked;
  btn.disabled = true; $("#start-msg").textContent = "Starting…";
  try {
    const r = await api("POST", "/api/runs", body);
    setRun(r.run_id);
    toast(`Run ${r.run_id} started`);
    location.hash = "#control";
    poll();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; $("#start-msg").textContent = ""; }
}

// ------------------------------------------------------------------ CONTROL
function buildControl() {
  const v = $("#view-control");
  const filters = [["all", "All"], ["decision", "Decisions"], ["tool", "Tool calls"], ["check", "Checks"], ["reviewer", "Reviewer"], ["model", "Model calls"], ["phase", "Phases"]];
  fill(v, 
    h("div", { id: "ctl-empty", class: "empty", hidden: true }, "No run selected. ",
      h("a", { href: "#new", text: "Start a run" }), " or open one from ", h("a", { href: "#history", text: "History" }), "."),
    h("div", { id: "ctl-body", style: "display:grid;gap:16px" },
      h("div", { class: "panel", id: "ctl-head" }),
      h("div", { id: "ctl-pending" }),
      h("div", { class: "split" },
        h("div", { style: "display:grid;gap:16px;min-width:0" },
          h("div", { class: "panel" }, h("header", {}, h("h2", { text: "Verification tasks" }), h("span", { class: "small muted", id: "task-count" })),
            h("div", { class: "tasks", id: "ctl-tasks" })),
          h("div", { class: "panel" }, h("header", {}, h("div", {}, h("h2", { text: "Note to the agent" }),
            h("p", { class: "small muted", text: "Delivered as REVIEWER_NOTE before the next model decision of the chosen task." }))),
            h("div", { style: "display:grid;gap:8px" },
              field("Deliver to", h("select", { id: "note-task" })),
              h("textarea", { id: "note-text", rows: 3, placeholder: "e.g. The payslip uses the employer's Chinese name; treat it as the same company." }),
              h("div", { class: "row end" }, h("span", { class: "small muted", id: "note-queued" }),
                h("button", { type: "button", id: "note-send", on: { click: sendNote } }, "Send note"))))),
        h("div", { class: "panel", style: "min-width:0" },
          h("header", {}, h("h2", { text: "Live activity" }),
            h("label", { class: "check small" }, h("input", { type: "checkbox", id: "autoscroll", checked: true,
              on: { change: (e) => { S.autoscroll = e.target.checked; } } }), "Follow")),
          h("div", { class: "filters", style: "margin-bottom:10px" }, filters.map(([k, l]) => h("button", {
            type: "button", class: "small", "aria-pressed": String(S.evFilter === k), "data-f": k,
            on: { click: () => { S.evFilter = k; store.set("evFilter", k); document.querySelectorAll(".filters [data-f]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.f === k))); redrawFeed(); } },
          }, l))),
          h("div", { class: "feed", id: "feed" }))),
      h("div", { class: "panel" }, h("header", {}, h("h2", { text: "Findings so far" }),
        h("a", { href: "#results", class: "small", text: "Open results" })), h("div", { id: "ctl-findings" }))));
}

async function control(action, extra) {
  try { await api("POST", `/api/runs/${S.runId}/control`, { action, ...(extra || {}) }); poll(); }
  catch (e) { toast(e.message, true); }
}

async function resumeRun(id) {
  try {
    const r = await api("POST", `/api/runs/${id}/resume`, {});
    setRun(r.run_id); toast("Resumed from the last checkpoint"); location.hash = "#control"; poll();
  } catch (e) { toast(e.message, true); }
}

function renderControl(newEvents) {
  if (!S.built.control) return;
  const run = S.run;
  $("#ctl-empty").hidden = !!S.runId;
  $("#ctl-body").hidden = !S.runId;
  if (!S.runId || !run) return;
  const c = run.counters, ctrl = run.control, active = run.active;
  const phaseIdx = PHASES.findIndex(([p]) => p === run.phase);
  const flags = (ctrl && ctrl.flags) || (run.config.ui && run.config.ui.control) || {};
  const head = $("#ctl-head");
  fill(head, 
    h("header", {},
      h("div", {}, h("h2", { text: run.client + (run.client_ref ? " — " + run.client_ref : "") }),
        h("p", { class: "small muted mono", text: `${run.run_id} · system ${run.config.system} · ${run.config.provider}/${run.config.model} · tools ${run.config.tool_transport}` +
          (run.focus.length ? ` · focus ${run.focus.join(", ")}` : "") })),
      h("div", { class: "row" }, statusPill(run.status),
        active && ctrl ? (ctrl.paused ? h("button", { type: "button", class: "primary", on: { click: () => control("resume") } }, "Resume")
          : h("button", { type: "button", on: { click: () => control("pause") } }, "Pause")) : null,
        active ? h("button", { type: "button", class: "danger", on: { click: () => control("stop") }, disabled: ctrl && ctrl.stop_requested }, ctrl && ctrl.stop_requested ? "Stopping…" : "Stop") : null,
        !active && run.status !== "done" ? h("button", { type: "button", class: "primary", on: { click: () => resumeRun(run.run_id) } }, "Resume from checkpoint") : null)),
    h("div", { class: "stepper", style: "margin-bottom:12px" }, PHASES.map(([p, l], i) =>
      h("span", { class: run.phase === "done" || i < phaseIdx ? "done" : i === phaseIdx ? "now" : "", text: l }))),
    run.error ? h("div", { class: "callout bad small", style: "margin-bottom:12px", text: run.error }) : null,
    run.stop_reason ? h("div", { class: "callout warn small", style: "margin-bottom:12px" }, `Stopped: ${run.stop_reason}. The run is checkpointed; resume continues from the unfinished step.`) : null,
    h("div", { class: "stats" },
      stat(fmtNum(c.model_calls), "model calls"), stat(fmtNum(c.tool_calls), "tool calls"), stat(fmtNum(c.tool_errors), "tool errors"),
      stat(fmtNum(c.tokens_in) + " / " + fmtNum(c.tokens_out), "tokens in / out"), stat(fmtCost(c.cost_usd), "est. cost"),
      stat(fmtNum(run.claims.length), "claims"), stat(fmtNum(run.evidence.length), "evidence"),
      stat(fmtNum(c.gate_downgrades), "gate downgrades"), stat(fmtNum(run.pii_masked), "PII masked"),
      stat(run.elapsed_s === null ? "–" : run.elapsed_s + " s", "elapsed"), stat(ctrl ? ctrl.waited_s + " s" : "–", "waiting on you")),
    h("div", { style: "margin-top:14px" },
      h("div", { class: "small muted", style: "margin-bottom:6px", text: active ? "Controller (applies immediately)" : "Controller settings used by this run" }),
      h("div", { class: "row", style: "gap:14px" }, Object.entries(FLAG_INFO).map(([k, [l]]) => h("label", { class: "check small" },
        h("input", { type: "checkbox", checked: !!flags[k], disabled: !active,
          on: { change: (e) => control("flags", { flags: { [k]: e.target.checked } }) } }), l)))),
  );
  if (ctrl && ctrl.current && ctrl.current.task_id && active) head.appendChild(h("p", { class: "small muted", style: "margin:10px 0 0" },
    `Now: ${ctrl.current.task_id}` + (ctrl.current.step ? `, decision ${ctrl.current.step}` : "") + (ctrl.paused ? " (paused)" : "")));

  // pending request: rebuild only when it changes, so edits in progress are kept
  const pend = ctrl && ctrl.pending;
  const pid = pend ? pend.request_id : null;
  if (pid !== S.pendingId) {
    S.pendingId = pid;
    fill($("#ctl-pending"), pend ? renderPending(pend) : "");
    if (pend) $("#ctl-pending").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // tasks
  const cur = ctrl && ctrl.current ? ctrl.current.task_id : null;
  $("#task-count").textContent = run.tasks.length ? `${run.tasks.filter((t) => t.status !== "pending").length}/${run.tasks.length} finished` : "";
  fill($("#ctl-tasks"), ...(run.tasks.length ? run.tasks.map((t) => {
    const claims = t.claim_ids.map((id) => run.claims.find((x) => x.claim_id === id)).filter(Boolean);
    const skipped = ctrl && ctrl.skipped.includes(t.task_id);
    return h("div", { class: "task" + (t.task_id === cur && active ? " current" : "") },
      h("div", { class: "top" }, h("b", { text: t.task_id }), h("span", { class: "tag", text: t.skill || "no playbook" }), h("span", { class: "tag", text: "P" + t.priority }),
        t.round > 1 ? h("span", { class: "tag", text: "round " + t.round }) : null,
        h("span", { class: "st " + t.status, text: t.task_id === cur && active && t.status === "pending" ? "working" : t.status }),
        h("span", { class: "spacer" }),
        active && t.status === "pending" ? h("button", { type: "button", class: "small", disabled: skipped,
          on: { click: () => skipTask(t.task_id) } }, skipped ? "Skipping" : "Skip") : null,
        active && t.status === "pending" ? h("button", { type: "button", class: "small", on: { click: () => { $("#note-task").value = t.task_id; $("#note-text").focus(); } } }, "Note") : null),
      h("p", { text: t.question }),
      claims.map((cl) => h("p", { class: "muted" }, h("b", { text: cl.claim_id + " " }), cl.text)),
      t.stop_reason ? h("p", { class: "small muted", text: "Stop reason: " + t.stop_reason }) : null);
  }) : [h("div", { class: "empty", text: run.phase === "intake" || run.phase === "extract_claims" || run.phase === "plan" ? "Tasks appear after planning." : "No tasks." })]));

  // note target options
  const sel = $("#note-task"), prev = sel.value;
  const open = run.tasks.filter((t) => t.status === "pending");
  const key = open.map((t) => t.task_id + t.skill).join(",");
  if (sel.dataset.key !== key) {        // rebuild only when the task list changes, so an open dropdown stays open
    sel.dataset.key = key;
    fill(sel, h("option", { value: "", text: "Next decision (any task)" }),
      ...open.map((t) => h("option", { value: t.task_id, text: `${t.task_id} — ${t.skill || "no playbook"}` })));
    if ([...sel.options].some((o) => o.value === prev)) sel.value = prev;
  }
  $("#note-send").disabled = !active;
  $("#note-queued").textContent = ctrl && ctrl.queued_notes ? `${ctrl.queued_notes} note(s) waiting for delivery` : "";

  // feed
  for (const e of newEvents) appendEvent(e);

  // findings
  fill($("#ctl-findings"), findingsTable(run, false));
}

function stat(value, label) { return h("div", { class: "stat" }, h("b", { text: value }), h("span", { text: label })); }

async function sendNote() {
  const text = $("#note-text").value.trim();
  if (!text) { toast("Write a note first.", true); return; }
  try {
    await api("POST", `/api/runs/${S.runId}/note`, { text, task_id: $("#note-task").value || null });
    $("#note-text").value = ""; toast("Note queued; the agent sees it before its next decision"); poll();
  } catch (e) { toast(e.message, true); }
}

async function skipTask(id) {
  try { await api("POST", `/api/runs/${S.runId}/skip`, { task_id: id }); toast(`${id} will be skipped`); poll(); }
  catch (e) { toast(e.message, true); }
}

async function respond(response) {
  const pend = S.run && S.run.control && S.run.control.pending;
  if (!pend) return;
  try {
    await api("POST", `/api/runs/${S.runId}/respond`, { request_id: pend.request_id, response });
    S.pendingId = null; fill($("#ctl-pending")); poll();
  } catch (e) { toast(e.message, true); }
}

// ---- pending request renderers
function renderPending(p) {
  const kind = p.kind, pl = p.payload;
  const wrap = (title, desc, ...body) => h("div", { class: "panel request-card" },
    h("header", {}, h("div", {}, h("h2", { text: title }), desc ? h("p", { class: "small muted", text: desc }) : null)), ...body);

  if (kind === "step") {
    return wrap(`next decision for ${pl.task_id || "the run"}${pl.step ? " (decision " + pl.step + ")" : ""}`,
      "Step mode is on. Add a note on the left first if you want to steer this decision.",
      h("div", { class: "row" },
        h("button", { type: "button", class: "primary", on: { click: () => respond({ continue: true }) } }, "Next decision"),
        h("button", { type: "button", on: { click: () => control("flags", { flags: { step_mode: false } }) } }, "Run without stepping"),
        h("button", { type: "button", on: { click: () => { skipTask(pl.task_id); respond({ continue: true }); } } }, "Skip this task")));
  }

  if (kind === "ask_user") {
    const free = h("input", { type: "text", id: "ask-free", placeholder: "Type an answer" });
    return wrap("the agent has a question", pl.task_id ? `From task ${pl.task_id}.` : "",
      h("p", { style: "font-size:1rem;margin:0 0 12px", text: pl.question }),
      h("div", { class: "row" }, (pl.options || []).map((o) => h("button", { type: "button", class: "primary", on: { click: () => respond({ answer: o }) } }, o))),
      h("div", { class: "row", style: "margin-top:10px" }, h("div", { style: "flex:1;min-width:200px" }, free),
        h("button", { type: "button", on: { click: () => { if (free.value.trim()) respond({ answer: free.value.trim() }); else toast("Type an answer or pick an option.", true); } } }, "Send answer"),
        h("button", { type: "button", on: { click: () => respond({ answer: null }) } }, "I don't know — continue")));
  }

  if (kind === "request_evidence") {
    const up = h("input", { type: "file", multiple: true, accept: ".md,.txt,.pdf" });
    return wrap("evidence is missing", "Upload SYNTHETIC documents that answer these gaps; the planner re-checks the affected claims. Or keep the gaps — they go into the memo as documents to request.",
      h("ul", {}, pl.gaps.map((g) => h("li", {}, h("b", { text: g.claim_id + " " }), g.claim, h("ul", { class: "small" }, g.missing_evidence.map((m) => h("li", { text: m })))))),
      h("div", { class: "row", style: "margin-top:10px" }, up,
        h("button", { type: "button", class: "primary", on: { click: async () => {
          if (!up.files.length) { toast("Choose at least one file, or keep the gaps.", true); return; }
          const uploads = [];
          for (const f of up.files) uploads.push({ name: f.name, data_b64: await new Promise((res) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] || ""); r.readAsDataURL(f); }) });
          respond({ uploads });
        } } }, "Upload and re-check"),
        h("button", { type: "button", on: { click: () => respond({ uploads: [] }) } }, "Keep the gaps")));
  }

  if (kind === "approve_tools") {
    const tools = S.config.tools.map((t) => [t.name, t.name]);
    const items = pl.calls.map((c, i) => {
      const inc = h("input", { type: "checkbox", checked: true, id: "call-inc-" + i });
      const item = h("div", { class: "edit-item" },
        h("div", { class: "row" }, h("label", { class: "check" }, inc, "Run"), select("call-tool-" + i, tools, c.tool)),
        h("textarea", { class: "mono", rows: Math.min(8, pretty(c.arguments).split("\n").length + 1), id: "call-args-" + i, value: pretty(c.arguments) }));
      inc.addEventListener("change", () => item.classList.toggle("off", !inc.checked));
      return item;
    });
    const note = h("input", { type: "text", id: "reject-note", placeholder: "Why not / what to do instead (sent to the agent)" });
    return wrap(`approve tool calls for ${pl.task_id} (decision ${pl.step})`, pl.thought ? `Agent's reason: ${pl.thought}` : "",
      h("div", { class: "edit-list" }, items),
      h("div", { class: "row", style: "margin-top:12px" },
        h("button", { type: "button", class: "primary", on: { click: () => {
          const calls = [];
          for (let i = 0; i < pl.calls.length; i++) {
            if (!$("#call-inc-" + i).checked) continue;
            try { calls.push({ tool: $("#call-tool-" + i).value, arguments: JSON.parse($("#call-args-" + i).value || "{}") }); }
            catch (e) { toast(`Call ${i + 1}: arguments are not valid JSON (${e.message})`, true); return; }
          }
          if (!calls.length) { toast("Tick at least one call, or reject the batch.", true); return; }
          respond({ decision: "approve", calls });
        } } }, "Run selected calls"),
        h("button", { type: "button", on: { click: () => { control("flags", { flags: { approve_tools: false } }); respond({ decision: "approve" }); } } }, "Approve this and stop asking"),
        h("div", { style: "flex:1;min-width:220px" }, note),
        h("button", { type: "button", class: "danger", on: { click: () => respond({ decision: "reject", note: note.value.trim() }) } }, "Reject")));
  }

  if (kind === "review_claims") {
    const items = pl.claims.map((c) => {
      const keep = h("input", { type: "checkbox", checked: true, "data-id": c.claim_id, class: "claim-keep" });
      const item = h("div", { class: "edit-item" },
        h("div", { class: "row" }, h("label", { class: "check" }, keep, h("b", { text: c.claim_id })),
          select("claim-cat-" + c.claim_id, pl.categories.map((x) => [x, x]), c.category),
          select("claim-mat-" + c.claim_id, [["high", "high"], ["medium", "medium"], ["low", "low"]], c.materiality),
          h("span", { class: "tag", text: [c.entity, c.amount !== null && c.amount !== undefined ? `${c.currency} ${fmtNum(c.amount)}` : "", c.date].filter(Boolean).join(" · ") })),
        h("textarea", { rows: 2, id: "claim-text-" + c.claim_id, value: c.text }),
        h("div", { class: "small muted", text: (c.sources || []).join(" · ") }));
      keep.addEventListener("change", () => item.classList.toggle("off", !keep.checked));
      return item;
    });
    return wrap(`review ${pl.claims.length} extracted claims`, "Untick claims that are not worth checking. Edits change what the agent verifies.",
      h("div", { class: "edit-list" }, items),
      h("div", { class: "row", style: "margin-top:12px" },
        h("button", { type: "button", class: "primary", on: { click: () => respond({ claims: pl.claims.map((c) => ({
          claim_id: c.claim_id, keep: document.querySelector(`.claim-keep[data-id="${c.claim_id}"]`).checked,
          text: $("#claim-text-" + c.claim_id).value, category: $("#claim-cat-" + c.claim_id).value,
          materiality: $("#claim-mat-" + c.claim_id).value })) }) } }, "Approve claims"),
        h("button", { type: "button", on: { click: () => respond({}) } }, "Keep all as extracted")));
  }

  if (kind === "review_plan") {
    let order = pl.tasks.map((t) => t.task_id);
    const list = h("div", { class: "edit-list" });
    const items = {};
    for (const t of pl.tasks) {
      const keep = h("input", { type: "checkbox", checked: true, id: "task-keep-" + t.task_id });
      const item = h("div", { class: "edit-item" },
        h("div", { class: "row" }, h("label", { class: "check" }, keep, h("b", { text: t.task_id })),
          select("task-skill-" + t.task_id, pl.skills.map((x) => [x, x]), t.skill),
          select("task-prio-" + t.task_id, [["1", "priority 1"], ["2", "priority 2"], ["3", "priority 3"]], String(t.priority)),
          h("span", { class: "spacer" }),
          h("button", { type: "button", class: "small", "aria-label": "Move up", on: { click: () => move(t.task_id, -1) } }, "↑"),
          h("button", { type: "button", class: "small", "aria-label": "Move down", on: { click: () => move(t.task_id, 1) } }, "↓")),
        h("textarea", { rows: 2, id: "task-q-" + t.task_id, value: t.question }),
        t.claims.map((c) => h("div", { class: "small muted" }, h("b", { text: c.claim_id + " " }), `(${c.category}) ${c.text}`)));
      keep.addEventListener("change", () => item.classList.toggle("off", !keep.checked));
      items[t.task_id] = item;
    }
    const draw = () => fill(list, ...order.map((id) => items[id]));
    const move = (id, d) => { const i = order.indexOf(id), j = i + d; if (j < 0 || j >= order.length) return; [order[i], order[j]] = [order[j], order[i]]; draw(); };
    draw();
    return wrap(`review the verification plan (${pl.tasks.length} tasks)`, "Tasks run top to bottom. Untick a task to leave its claims unverified.",
      list,
      h("div", { class: "row", style: "margin-top:12px" },
        h("button", { type: "button", class: "primary", on: { click: () => respond({ tasks: order.map((id) => ({
          task_id: id, keep: $("#task-keep-" + id).checked, question: $("#task-q-" + id).value,
          skill: $("#task-skill-" + id).value, priority: Number($("#task-prio-" + id).value) })) }) } }, "Approve plan"),
        h("button", { type: "button", on: { click: () => respond({}) } }, "Run as proposed")));
  }
  return wrap(kind, "", h("pre", { class: "json", text: pretty(pl) }),
    h("button", { type: "button", class: "primary", on: { click: () => respond({}) } }, "Continue"));
}

// ---- activity feed
const EV_GROUP = { decision: "decision", tool_call: "tool", verify: "check", format_repair: "check", control: "reviewer", ask_user: "reviewer",
  model_call: "model", context: "model", model_error: "model", phase: "phase", plan: "phase", stop: "phase", error: "phase",
  warning: "phase", mcp_discovery: "phase" };
function evVisible(e) { return S.evFilter === "all" ? e.kind !== "context" : EV_GROUP[e.kind] === S.evFilter; }
function redrawFeed() {
  const f = $("#feed");
  if (!f) return;
  fill(f, ...S.events.filter(evVisible).slice(-600).map(eventRow));
  f.scrollTop = f.scrollHeight;
}
function appendEvent(e) {
  const f = $("#feed");
  if (!f || !evVisible(e)) return;
  f.appendChild(eventRow(e));
  while (f.children.length > 600) f.firstChild.remove();
  if (S.autoscroll) f.scrollTop = f.scrollHeight;
}
function eventRow(e) {
  let body = [], bad = false;
  const code = (t) => h("code", { text: t });
  switch (e.kind) {
    case "phase":
      if (e.task_id) body = [h("b", { text: `${e.task_id} ` }), `${e.skill}: ${e.claim || ""}`];
      else if (e.claims !== undefined) body = [`Extracted ${e.claims} claims `, h("span", { class: "muted", text: JSON.stringify(e.by_category || {}) })];
      else if (e.documents !== undefined && e.chunks !== undefined) body = [`Loaded ${e.documents} documents (${e.chunks} spans); ${e.pii_masked} PII spans masked`, e.memory_facts ? `; ${e.memory_facts} verified facts in client memory` : "", e.skipped && e.skipped.length ? `; skipped ${e.skipped.join(", ")}` : ""];
      else if (e.cross_claim_conflicts !== undefined) body = [`Reconciled: ${e.cross_claim_conflicts} cross-claim conflicts, ${e.evidence_requests} documents to request, ${e.review_questions} questions`];
      else if (e.decision) body = [`Evidence check: ${e.decision}`];
      else if (e.phase === "gate" && e.enabled !== undefined) body = [e.enabled ? `Completion gate: ${e.checked} findings checked` + (e.downgraded.length ? `, downgraded ${e.downgraded.join(", ")}` : ", all passed") : "Completion gate disabled in this system variant"];
      else if (e.phase === "review" && e.reviewed !== undefined) body = [`Independent reviewer: ${e.reviewed} findings`, e.disagreements.length ? `, disagrees on ${e.disagreements.join(", ")}` : ", no disagreements"];
      else if (e.path) body = ["Memo written"];
      else body = [`Phase: ${e.phase}`, e.provider ? ` (${e.provider}, system ${e.system}, tools ${e.transport})` : ""];
      break;
    case "plan":
      body = e.tasks ? [`Planned ${e.tasks.length} tasks: `, e.tasks.map((t) => `${t.task_id} ${t.skill}`).join(", ")] : [e.message || "", e.claims ? " " + e.claims.join(", ") : ""];
      break;
    case "decision": body = [h("b", { text: `${e.task_id} · decision ${e.step + 1}: ${e.action} ` }), e.summary || ""]; break;
    case "tool_call":
      bad = !e.ok;
      body = [code(`${e.tool}(${JSON.stringify(e.arguments)})`), " → ",
        e.ok ? h("span", { text: (e.evidence_ids && e.evidence_ids.length ? e.evidence_ids.join(", ") : "no records") }) : h("span", { text: `${e.error_kind}: ${e.error}` }),
        h("span", { class: "muted", text: ` · ${e.latency_ms} ms · attempts ${e.attempts} · ${e.transport}` })];
      break;
    case "verify":
      bad = !e.ok;
      body = e.ok ? [`${e.task_id}: finding passed the citation/completion checks`] : [`${e.task_id}: gate rejected the finding — `, e.problems.join("; ")];
      break;
    case "format_repair": bad = true; body = [`${e.task_id || e.phase}: malformed output, asking for a repair — ${e.error}`]; break;
    case "model_call":
      body = [h("b", { text: `${e.purpose}${e.task_id ? " " + e.task_id : ""} ` }),
        h("span", { class: "muted", text: `context ~${fmtNum(e.context_tokens)} tok · in ${fmtNum(e.tokens_in)} / out ${fmtNum(e.tokens_out)} · ${e.latency_ms} ms` }),
        h("details", {}, h("summary", { text: "model output" }), h("pre", { text: e.output || "" }))];
      break;
    case "context": body = [`${e.task_id}: context ~${fmtNum(e.context_tokens)} tokens`, e.compressed_observations ? `, ${e.compressed_observations} observations compressed` : "", e.over_budget ? " (over budget)" : ""]; break;
    case "ask_user": body = [`${e.task_id} asked: “${e.question}” → `, h("b", { text: e.answer === null ? "no answer" : e.answer })]; break;
    case "control": body = [controlText(e)]; break;
    case "stop": bad = true; body = [`${e.task_id ? e.task_id + ": " : ""}${e.reason}`]; break;
    case "error": bad = true; body = [e.error, h("details", {}, h("summary", { text: "traceback" }), h("pre", { text: e.traceback || "" }))]; break;
    case "model_error": bad = true; body = [`model call failed (attempt ${e.attempt}): ${e.error}`]; break;
    case "warning": bad = true; body = [e.message || "", e.claim ? ` — ${e.claim}` : ""]; break;
    case "mcp_discovery": body = [`MCP tools/list: ${e.discovered.join(", ")}; allowed: ${e.allowed.join(", ")}`]; break;
    default: body = [JSON.stringify(e)];
  }
  return h("div", { class: "ev" + (bad ? " bad" : "") }, h("time", { text: e.ts || "" }),
    h("span", { class: "k " + e.kind, text: e.kind.replace("_", " ") }), h("div", { class: "body" }, body));
}
function controlText(e) {
  switch (e.event) {
    case "waiting": return `Waiting for you: ${e.request.replace("_", " ")}`;
    case "answered": return `You answered: ${e.request.replace("_", " ")}`;
    case "paused": return "Paused by you";
    case "resumed": return "Resumed";
    case "stop_requested": return "Stop requested";
    case "flags": return "Controller: " + Object.entries(e.flags).filter(([, v]) => v).map(([k]) => k).join(", ") || "Controller: all gates off";
    case "note": return `Note queued${e.task_id ? " for " + e.task_id : ""}: ${e.text}`;
    case "note_delivered": return `Note delivered to ${e.task_id}: ${e.text}`;
    case "skip": return `Skip requested for ${e.task_id}`;
    case "tools_rejected": return `You rejected tool calls in ${e.task_id}${e.note ? ": " + e.note : ""}`;
    case "tools_edited": return `You edited tool calls in ${e.task_id}: ${JSON.stringify(e.calls)}`;
    case "claims_reviewed": return `Claims reviewed: kept ${e.kept}${e.dropped.length ? ", dropped " + e.dropped.join(", ") : ""}`;
    case "plan_reviewed": return `Plan reviewed: ${e.tasks.length} tasks` + (e.removed.length ? `, removed ${e.removed.join(", ")}` : "");
    default: return JSON.stringify(e);
  }
}

// ------------------------------------------------------------------ RESULTS
function buildResults() {
  fill($("#view-results"), 
    h("div", { class: "panel" },
      h("header", {}, h("div", {}, h("h2", { id: "res-title", text: "Results" }), h("p", { class: "small muted mono", id: "res-meta" })),
        h("div", { class: "row", id: "res-downloads" })),
      h("div", { class: "row", style: "margin-bottom:14px" }, seg("restab", [["memo", "Memo"], ["findings", "Findings"], ["timeline", "Wealth timeline"], ["evidence", "Evidence log"], ["claims", "Claims"]], S.resultsTab)),
      h("div", { id: "res-remember" }),
      h("div", { id: "res-body" })));
  document.querySelectorAll('input[name="restab"]').forEach((r) => r.addEventListener("change", () => { S.resultsTab = segValue("restab"); renderResults(true); }));
}

let lastResultsSig = null;
async function renderResults(force) {
  const body = $("#res-body");
  if (!S.runId) { fill(body, h("div", { class: "empty" }, "No run selected. Open one from ", h("a", { href: "#history", text: "History" }), ".")); return; }
  const run = S.run;
  if (!run) return;
  $("#res-title").textContent = run.client + (run.client_ref ? " — " + run.client_ref : "");
  $("#res-meta").textContent = `${run.run_id} · ${run.status} · system ${run.config.system} · ${run.config.provider}/${run.config.model}`;
  fill($("#res-downloads"), statusPill(run.status), run.has_memo ? h("button", {type: "button", on: {click: () => askAboutRun(run.run_id)}}, "Ask about this memo") : null, ...["memo.md", "record.json", "trace.jsonl", "summary.json"].map((n) =>
    h("a", { href: `/api/runs/${run.run_id}/download/${n}`, class: "small", text: n, download: true })));
  const tab = S.resultsTab;
  const sig = [run.run_id, run.status, run.phase, run.has_memo, run.evidence.length, Object.keys(run.findings).length,
    run.claims.length, tab, S.verdictFilter].join("|");
  if (!force && sig === lastResultsSig) return;   // keep expanded rows and scroll position
  lastResultsSig = sig;
  fill($("#res-remember"), run.status === "done" ? rememberPanel(run) : null);
  if (tab === "memo") {
    if (!run.has_memo) { fill(body, h("div", { class: "empty", text: "The memo is written in the last phase. Findings so far are on the Findings tab." })); return; }
    try { const b = await api("GET", `/api/runs/${run.run_id}/memo`); fill(body, markdown(b.markdown)); }
    catch (e) { fill(body, h("div", { class: "callout bad", text: e.message })); }
    return;
  }
  if (tab === "findings") {
    const chips = h("div", { class: "filters", style: "margin-bottom:10px" }, [["", "All"], ...Object.entries(VERDICT_LABEL)].map(([k, l]) =>
      h("button", { type: "button", class: "small", "aria-pressed": String(S.verdictFilter === k), on: { click: () => { S.verdictFilter = k; renderResults(true); } } }, l)));
    fill(body, chips, findingsTable(run, true));
  } else if (tab === "timeline") {
    fill(body, run.timeline.length ? h("div", { class: "tbl" }, h("table", {}, h("thead", {}, h("tr", {}, ["Date", "Claim", "Event", "Entity", "Amount", "Status"].map((x) => h("th", { text: x })))),
      h("tbody", {}, run.timeline.map((t) => h("tr", {}, h("td", { class: "mono", text: t.date }), h("td", { class: "mono", text: t.claim_id }), h("td", { text: t.event }),
        h("td", { text: t.entity }), h("td", { class: "num", text: t.amount === null ? "" : `${t.currency} ${fmtNum(t.amount)}` }), h("td", {}, verdictPill(t.status)))))))
      : h("div", { class: "empty", text: "The timeline is built in the reconcile phase." }));
  } else if (tab === "evidence") {
    fill(body, evidenceTable(run.evidence));
  } else {
    fill(body, h("div", { class: "tbl" }, h("table", {}, h("thead", {}, h("tr", {}, ["ID", "Category", "Claim", "Entity", "Amount", "Date", "Event", "Source"].map((x) => h("th", { text: x })))),
      h("tbody", {}, run.claims.map((c) => h("tr", {}, h("td", { class: "mono", text: c.claim_id }), h("td", { text: c.category }), h("td", { text: c.text }),
        h("td", { text: c.entity }), h("td", { class: "num", text: c.amount === null ? "" : `${c.currency} ${fmtNum(c.amount)}` }), h("td", { class: "mono", text: c.date + (c.period_end ? " – " + c.period_end : "") }),
        h("td", { text: c.event }), h("td", { class: "small", text: c.sources.join("; ") })))))));
  }
}

function rememberPanel(run) {
  const n = Object.values(run.findings).filter((f) => f.verdict === "supported" && f.verified).length;
  if (!n) return null;
  const officer = h("input", { type: "text", id: "officer-id", placeholder: "officer identifier" });
  return h("div", { class: "callout small", style: "margin-bottom:12px" },
    h("b", { text: "Step 8 — human compliance review. " }),
    `After reviewing the memo, an officer can confirm the ${n} supported, gate-verified finding(s) as client memory for future reviews. The agent never writes memory on its own.`,
    h("div", { class: "row", style: "margin-top:8px" }, h("div", { style: "min-width:200px" }, officer),
      h("button", { type: "button", on: { click: async () => {
        try { const r = await api("POST", `/api/runs/${run.run_id}/remember`, { officer: officer.value.trim() }); toast(`${r.written.length} fact(s) written to client memory`); }
        catch (e) { toast(e.message, true); }
      } } }, "Confirm into client memory")));
}

function findingsTable(run, detailed) {
  const parked = (f) => f.task_id === "out_of_scope" || f.task_id === "removed";
  let rows = run.claims.map((c) => [c, run.findings[c.claim_id]]).filter(([, f]) => f && (!S.verdictFilter || f.verdict === S.verdictFilter))
    .sort((a, b) => parked(a[1]) - parked(b[1]));
  const nParked = rows.filter(([, f]) => parked(f)).length;
  if (!detailed) rows = rows.filter(([, f]) => !parked(f));   // the live view shows verified claims only
  const parkedNote = !detailed && nParked ? h("p", { class: "small muted", text: `${nParked} claim(s) out of scope or removed from the plan; see Results.` }) : null;
  if (!rows.length) return h("div", {}, h("div", { class: "empty", text: run.claims.length ? "No findings yet." : "No claims extracted yet." }), parkedNote);
  const ev = Object.fromEntries(run.evidence.map((e) => [e.evidence_id, e]));
  const tbody = h("tbody");
  for (const [c, f] of rows) {
    const scope = f.task_id === "out_of_scope" ? "out of scope" : f.task_id === "removed" ? "removed by you" : "";
    const tr = h("tr", { class: detailed ? "clickable" : "" },
      h("td", { class: "mono", text: c.claim_id }), h("td", { text: c.category }),
      h("td", {}, scope ? h("span", { class: "tag", text: scope }) : verdictPill(f.verdict),
        f.gate_notes && f.gate_notes.length ? h("span", { class: "tag", text: "downgraded" }) : null,
        f.review && f.review.supports === false ? h("span", { class: "tag", text: "reviewer disagrees" }) : null),
      h("td", { text: c.text }), h("td", { class: "num", text: f.evidence_ids.length }), h("td", { class: "num", text: f.conflicts.length }));
    tbody.appendChild(tr);
    if (detailed) {
      const det = h("tr", { class: "detail", hidden: true }, h("td", { colspan: 6 },
        h("p", {}, h("b", { text: "Finding: " }), f.rationale),
        f.numbers && Object.keys(f.numbers).length ? h("p", {}, h("b", { text: "Computed figures: " }), Object.entries(f.numbers).map(([k, x]) => `${k} = ${fmtNum(x)}`).join(", ")) : null,
        f.evidence_ids.length ? h("div", {}, h("b", { text: "Evidence" }), h("ul", {}, f.evidence_ids.filter((id) => ev[id]).map((id) => {
          const e = ev[id];
          return h("li", {}, h("code", { text: id }), ` ${e.source} · ${e.location} `, h("span", { class: "tag", text: e.evidence_type }));
        }))) : null,
        f.conflicts.length ? h("div", {}, h("b", { text: "Conflicts" }), h("ul", {}, f.conflicts.map((x) => h("li", { text: x })))) : null,
        f.missing_evidence.length ? h("div", {}, h("b", { text: "Missing evidence" }), h("ul", {}, f.missing_evidence.map((x) => h("li", { text: x })))) : null,
        f.open_questions.length ? h("div", {}, h("b", { text: "Open questions" }), h("ul", {}, f.open_questions.map((x) => h("li", { text: x })))) : null));
      tr.addEventListener("click", () => { det.hidden = !det.hidden; });
      tbody.appendChild(det);
    }
  }
  return h("div", {}, h("div", { class: "tbl" }, h("table", {}, h("thead", {}, h("tr", {}, ["ID", "Category", "Status", "Claim", "Evidence", "Conflicts"].map((x) => h("th", { text: x })))), tbody)), parkedNote);
}

function evidenceTable(evidence) {
  if (!evidence.length) return h("div", { class: "empty", text: "No evidence retrieved yet." });
  return h("div", { class: "tbl" }, h("table", {}, h("thead", {}, h("tr", {}, ["ID", "Type", "Source", "Identifier", "Location", "Retrieved"].map((x) => h("th", { text: x })))),
    h("tbody", {}, evidence.map((e) => h("tr", {}, h("td", { class: "mono", text: e.evidence_id }), h("td", {}, h("span", { class: "tag", text: e.evidence_type })), h("td", { text: e.source }),
      h("td", { class: "mono", text: e.identifier }), h("td", { class: "small", text: e.location }), h("td", { class: "small", text: e.retrieved_at }))))));
}

// ------------------------------------------------------------------ HISTORY
function buildHistory() {
  fill($("#view-history"), h("div", { class: "panel" },
    h("header", {}, h("div", {}, h("h2", { text: "Run history" }), h("p", { class: "small muted", text: "Runs saved in " + S.config.runs_dir })),
      h("button", { type: "button", on: { click: refreshHistory } }, "Refresh")),
    h("div", { id: "hist-body" })));
}
async function refreshHistory() {
  const body = $("#hist-body");
  if (!body) return;
  try {
    const { runs } = await api("GET", "/api/runs");
    if (!runs.length) { fill(body, h("div", { class: "empty" }, "No runs yet. ", h("a", { href: "#new", text: "Start one" }), ".")); return; }
    fill(body, h("div", { class: "tbl" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Started", "Client", "Status", "Phase", "System / model", "Claims", "Statuses", ""].map((x) => h("th", { text: x })))),
      h("tbody", {}, runs.map((r) => h("tr", {},
        h("td", { class: "small mono", text: r.started_at }), h("td", {}, h("b", { text: r.client }), r.client_ref ? " — " + r.client_ref : "", r.focus.length ? h("div", { class: "small muted", text: "focus: " + r.focus.join(", ") }) : null),
        h("td", {}, statusPill(r.status)), h("td", { text: r.phase }), h("td", { class: "small", text: `${r.system || "C"} · ${r.provider}/${r.model}` }), h("td", { class: "num", text: r.claims }),
        h("td", {}, Object.entries(r.verdicts).map(([v, n]) => h("span", { style: "margin-right:4px" }, verdictPill(v), " " + n))),
        h("td", {}, h("div", { class: "row" },
          h("button", { type: "button", class: "small", on: { click: () => { setRun(r.run_id); poll(); location.hash = r.status === "done" ? "#results" : "#control"; } } }, "Open"),
          ["stopped", "interrupted", "error"].includes(r.status) ? h("button", { type: "button", class: "small primary", on: { click: () => resumeRun(r.run_id) } }, "Resume") : null))))))));
  } catch (e) { fill(body, h("div", { class: "callout bad", text: e.message })); }
}

// ------------------------------------------------------------------ TOOLS
const TOOL_EXAMPLES = {
  lookup_company: { name: "Silverline Digital Limited" }, lookup_property: { address: "Flat 8C, Harbour Crest, Tseung Kwan O" },
  search_documents: { query: "Silverline salary", doc_type: "payslip" }, parse_document: { doc: "04_bank_statement_2023-09.md" },
  check_consistency: { checks: [{ label: "monthly salary vs payslip", kind: "amount", claimed: 62000, documented: 62000 },
    { label: "salary x 12 vs tax", kind: "amount", claimed: 62000, multiplier: 12, documented: 744000 }] },
  calc_wealth_timeline: { label: "Funding of Flat 8C", items: [
    { date: "2023-09-01", label: "opening balance", direction: "in", amount: 1150000 },
    { date: "2023-10-20", label: "mortgage", direction: "in", amount: 6860000 },
    { date: "2023-10-20", label: "price", direction: "out", amount: 9800000 }] },
  search_policy: { query: "third-party gift source of wealth" },
  read_skill_reference: { skill: "employment-income", file: "references/hk-documents.md" }, get_evidence: { evidence_id: "E1" },
};
function buildTools() {
  const tools = S.config.tools;
  const cases = S.config.cases.map((c) => [c.case, `Case packet + registries: ${c.case} (${c.client})`]);
  fill($("#view-tools"), h("div", { class: "grid2" },
    h("div", { class: "panel" },
      h("header", {}, h("div", {}, h("h2", { text: "Tool playground" }), h("p", { class: "small muted", text: "Runs one call through the real gateway: argument validation, timeout, retries and output contract. No model involved." }))),
      h("div", { style: "display:grid;gap:10px" },
        field("Tool", select("tool-name", tools.map((t) => [t.name, t.name]), "lookup_company")),
        h("p", { class: "small muted", id: "tool-desc" }),
        field("Case", select("tool-src", cases, "wong")),
        field("Arguments (JSON)", h("textarea", { class: "mono", rows: 6, id: "tool-args" })),
        field("Inject a fault (optional)", h("input", { type: "text", id: "tool-faults", placeholder: "lookup_company=timeout*1" })),
        h("div", { class: "row end" }, h("button", { type: "button", class: "primary", id: "tool-run", on: { click: runTool } }, "Run tool")),
        h("details", {}, h("summary", { text: "Input contract (JSON schema)" }), h("pre", { class: "json", id: "tool-schema" })))),
    h("div", { class: "panel" }, h("header", {}, h("h2", { text: "Observation" }), h("span", { class: "small muted", id: "tool-meta" })),
      h("div", { id: "tool-out" }, h("div", { class: "empty", text: "Run a tool to see what the model would observe." })))));
  const sync = () => {
    const t = tools.find((x) => x.name === $("#tool-name").value);
    $("#tool-desc").textContent = t.description + ` (evidence type: ${t.evidence_type})`;
    $("#tool-schema").textContent = pretty(t.input_schema);
    $("#tool-args").value = pretty(TOOL_EXAMPLES[t.name] || {});
  };
  $("#tool-name").addEventListener("change", sync);
  sync();
}
async function runTool() {
  const src = $("#tool-src").value, btn = $("#tool-run");
  let args;
  try { args = JSON.parse($("#tool-args").value || "{}"); } catch (e) { toast("Arguments are not valid JSON: " + e.message, true); return; }
  btn.disabled = true;
  try {
    const r = await api("POST", "/api/tool-check", { tool: $("#tool-name").value, arguments: args, faults: $("#tool-faults").value.trim(),
      case: src });
    $("#tool-meta").textContent = `${r.latency_ms} ms · attempts ${r.attempts}`;
    fill($("#tool-out"), 
      r.observation.ok ? h("div", { class: "callout small", style: "margin-bottom:10px", text: `${r.observation.total} matching record(s); ${r.evidence.length} evidence item(s) registered.` })
        : h("div", { class: "callout bad small", style: "margin-bottom:10px", text: `${r.observation.error_kind}: ${r.observation.error}` }),
      h("pre", { class: "json", text: pretty(r.observation) }));
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; }
}

// ------------------------------------------------------------------ PROMPTS & SKILLS
function buildFiles() {
  fill($("#view-files"), h("div", { class: "split" },
    h("div", { class: "panel" }, h("header", {}, h("h2", { text: "Files" })), h("div", { class: "file-list", id: "file-list" })),
    h("div", { class: "panel" },
      h("header", {}, h("div", {}, h("h2", { class: "mono", id: "file-path", text: "Choose a file" }), h("p", { class: "small muted", id: "file-meta",
        text: "Prompts, playbooks (skills) and the gold benchmark. Changes apply to the next run." })),
        h("div", { class: "row" }, h("button", { type: "button", id: "file-revert", disabled: true, on: { click: () => openFile(S.file, true) } }, "Discard changes"),
          h("button", { type: "button", class: "primary", id: "file-save", disabled: true, on: { click: saveFile } }, "Save"))),
      h("textarea", { class: "mono", id: "file-text", rows: 30, disabled: true, spellcheck: "false",
        on: { input: () => { S.fileDirty = true; $("#file-save").disabled = false; $("#file-revert").disabled = false; } } }))));
  api("GET", "/api/files").then(({ files }) => {
    const list = $("#file-list"); let grp = "";
    for (const f of files) {
      const g = f.split("/").slice(0, f.startsWith("skills/") ? 2 : 1).join("/");
      if (g !== grp) { grp = g; list.appendChild(h("div", { class: "grp", text: g })); }
      list.appendChild(h("button", { type: "button", "data-path": f, text: f.slice(g.length + 1) || f, on: { click: () => openFile(f) } }));
    }
  }).catch((e) => toast(e.message, true));
}
async function openFile(path, force) {
  if (S.fileDirty && !force && !confirm("Discard unsaved changes?")) return;
  try {
    const f = await api("GET", "/api/file?path=" + encodeURIComponent(path));
    S.file = path; S.fileDirty = false;
    $("#file-path").textContent = f.path; $("#file-meta").textContent = "Last saved " + f.modified + ". Changes apply to the next run.";
    const t = $("#file-text"); t.value = f.content; t.disabled = false;
    $("#file-save").disabled = true; $("#file-revert").disabled = true;
    document.querySelectorAll("#file-list button").forEach((b) => b.setAttribute("aria-current", String(b.dataset.path === path)));
  } catch (e) { toast(e.message, true); }
}
async function saveFile() {
  try {
    const f = await api("PUT", "/api/file", { path: S.file, content: $("#file-text").value });
    S.fileDirty = false; $("#file-save").disabled = true; $("#file-revert").disabled = true;
    $("#file-meta").textContent = "Saved " + f.modified + ". Changes apply to the next run."; toast("Saved " + f.path);
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ EVALUATION
function buildEval() {
  fill($("#view-eval"), 
    h("div", { class: "panel" },
      h("header", {}, h("div", {}, h("h2", { text: "Evaluation" }), h("p", { class: "small muted", text: "Runs the benchmark cases and counterfactual edits in eval/cases.json through systems A–C and the ablations, then scores them against the gold records." }))),
      h("div", { class: "grid3" },
        h("fieldset", { id: "eval-scen" }, h("legend", { text: "Scenarios" })),
        h("fieldset", {}, h("legend", { text: "Systems" }),
          check("sys-A", "A — single prompt, no tools", "same information as plain text", true),
          ...S.config.systems.map((x) => check("sys-" + x, SYSTEM_INFO[x] || x, "", ["B", "C"].includes(x))),
          field("Runs per case", h("input", { type: "number", id: "eval-runs", value: 1, min: "1", max: "5" }), "Proposal: 3 runs, mean and range.")),
        h("fieldset", {}, h("legend", { text: "Model" }),
          field("Provider", select("eval-provider", [["router", "Auto / API model router"], ["mock", "Mock"], ["ollama", "Ollama"], ["openai", "OpenAI-compatible"]], S.config.defaults.provider)),
          field("Model", h("input", { type: "text", id: "eval-model", placeholder: "provider default" })))),
      h("div", { class: "row end", style: "margin-top:12px" }, h("span", { class: "small muted", id: "eval-status" }),
        h("button", { type: "button", class: "primary", id: "eval-run", on: { click: startEval } }, "Run evaluation"))),
    h("div", { class: "panel" }, h("header", {}, h("h2", { text: "Results" }),
      h("div", { class: "row" }, h("select", { id: "eval-past", "aria-label": "Past results" }), h("button", { type: "button", class: "small", on: { click: loadPastEval } }, "Load"))),
      h("div", { id: "eval-body" }, h("div", { class: "empty", text: "Run the evaluation or load a past result." }))));
}
let evalTimer = null;
async function refreshEval() {
  try {
    const v = await api("GET", "/api/eval");
    const scen = $("#eval-scen");
    if (scen && !scen.dataset.filled) {
      scen.dataset.filled = "1";
      v.scenarios.forEach((s) => scen.appendChild(check("scen-" + s.id, `${s.id} (${s.split})`, `${s.kind} · ${s.expected} gold claims`, true)));
    }
    const past = $("#eval-past");
    if (past) fill(past, ...v.past.map((p) => h("option", { value: p, text: p })));
    const job = v.job;
    if (job) {
      $("#eval-status").textContent = job.status === "running" ? `Running… ${job.rows.length} result row(s) so far` : job.status === "error" ? job.error : `Finished: ${job.result_file}`;
      $("#eval-run").disabled = job.status === "running";
      if (job.rows.length) fill($("#eval-body"), evalTable(job.rows, job.meta || { provider: $("#eval-provider").value }, job.summary));
      clearTimeout(evalTimer);
      if (job.status === "running") evalTimer = setTimeout(refreshEval, 1200);
    }
  } catch (e) { toast(e.message, true); }
}
async function startEval() {
  const scenarios = [...document.querySelectorAll("#eval-scen input:checked")].map((i) => i.id.slice(5));
  const systems = ["A", ...S.config.systems].filter((s) => $("#sys-" + s) && $("#sys-" + s).checked);
  if (!scenarios.length || !systems.length) { toast("Pick at least one scenario and one system.", true); return; }
  try {
    await api("POST", "/api/eval", { scenarios, systems, runs: Number($("#eval-runs").value || 1), settings: { provider: $("#eval-provider").value, model: $("#eval-model").value.trim() } });
    toast("Evaluation started"); refreshEval();
  } catch (e) { toast(e.message, true); }
}
async function loadPastEval() {
  const id = $("#eval-past").value;
  if (!id) return;
  try { const r = await api("GET", "/api/eval/" + id); fill($("#eval-body"), evalTable(r.rows.concat(r.counterfactuals || []), r.meta, r.summary)); }
  catch (e) { toast(e.message, true); }
}
function evalTable(rows, meta, summary) {
  const cols = [["system", "System"], ["elvs", "ELVS"], ["joint_correctness", "Joint correct"], ["status_accuracy", "S (status)"],
    ["evidence_accuracy", "E (evidence)"], ["arithmetic_accuracy", "A (arith)"], ["red_flag_recall", "Red-flag recall"], ["false_flag_rate", "False flag ↓"],
    ["unresolved_as_supported", "Unres.→supp. ↓"], ["macro_f1", "Macro-F1"], ["evidence_support", "Evidence support"], ["arithmetic_errors", "Arith. err ↓"],
    ["claim_f1", "Claim F1"], ["field_accuracy", "Field acc."], ["ccr", "CCR (Eq. 2)"], ["ccr_count", "CCR pairs"], ["expected_behaviour_rate", "CF expected"],
    ["model_calls", "Model calls"], ["tool_calls", "Tool calls"], ["gate_downgrades", "Gate downgr."], ["tokens_in", "Tokens in"], ["cost_usd", "Cost $"], ["wall_time_s", "Time s"]];
  const out = [];
  if (meta && meta.provider === "mock") out.push(h("div", { class: "callout warn small", style: "margin-bottom:10px", text: "Mock provider: these numbers test the pipeline, not model quality." }));
  if (summary && summary.length) {
    const sc = [["system", "System"], ["gold_claims", "Gold claims"], ["elvs", "ELVS (mean)"], ["joint_correct", "Joint correct"], ["joint_correctness", "Joint correctness"],
      ["status_accuracy", "S (status)"], ["evidence_accuracy", "E (evidence)"], ["arithmetic_accuracy", "A (arith)"],
      ["red_flag_recall", "Red-flag recall"], ["false_flag_rate", "False flag ↓"], ["evidence_support", "Evidence support"],
      ["arithmetic_errors", "Arith. errors ↓"], ["unsupported_facts", "Unsupported facts ↓"], ["ccr", "CCR (Eq. 2)"], ["ccr_count", "CCR pairs"], ["cost_usd", "Cost $"]];
    out.push(h("h3", { style: "margin:4px 0", text: "Headline (per-case mean ELVS & micro-average over gold claims)" }), h("div", { class: "tbl" }, h("table", {},
      h("thead", {}, h("tr", {}, sc.map(([, l]) => h("th", { text: l })))),
      h("tbody", {}, summary.map((r) => h("tr", {}, sc.map(([k]) => h("td", { class: k === "system" ? "" : "num", text: r[k] === null || r[k] === undefined ? "–" : String(r[k]) }))))))));
  }
  const byScen = {};
  rows.forEach((r) => (byScen[r.scenario] = byScen[r.scenario] || []).push(r));
  for (const [sid, rs] of Object.entries(byScen)) {
    out.push(h("h3", { style: "margin:14px 0 4px", text: sid }), h("p", { class: "small muted", style: "margin:0 0 6px", text: rs[0].kind }),
      h("div", { class: "tbl" }, h("table", {}, h("thead", {}, h("tr", {}, cols.map(([, l]) => h("th", { text: l })))),
        h("tbody", {}, rs.map((r) => h("tr", {}, cols.map(([k]) => h("td", { class: k === "system" ? "" : "num", text: r[k] === null || r[k] === undefined ? "–" : String(r[k]) }))))))));
    out.push(h("details", {}, h("summary", { class: "small", text: "Per-claim results (paired scorecard)" }),
      ...rs.map((r) => h("div", {}, h("b", { class: "small", text: r.system }), h("ul", { class: "small" }, r.per_claim.map((p) => h("li", {}, p.ok ? "✓ " : "✗ ",
        h("b", { text: p.match }), `: gold ${p.expected}, got ${p.got || "not found"}` + (p.status_ok && !p.ok ? " (evidence link or figure wrong)" : ""))))))));
  }
  return h("div", {}, out);
}

// ------------------------------------------------------------------ CONNECTION
const CONN_FIELDS = [
  ["openrouter_api_key", "OpenRouter API key", "password", ""],
  ["deepseek_api_key", "DeepSeek API key (direct)", "password", ""],
  ["openai_base_url", "OpenAI-compatible base URL", "text", "e.g. https://api.openai.com/v1 or http://localhost:8000/v1"],
  ["openai_api_key", "OpenAI-compatible API key", "password", ""],
  ["azure_endpoint", "Azure-style endpoint", "text", "Set this instead of the base URL for Azure deployments"],
  ["azure_api_key", "Azure API key", "password", ""],
  ["azure_api_version", "Azure API version", "text", "e.g. 2024-06-01"],
  ["ollama_host", "Ollama host", "text", "default http://localhost:11434"],
];
function buildConnection() {
  const conn = S.config.connection;
  fill($("#view-connection"), h("div", { class: "grid2" },
    h("div", { class: "panel" },
      h("header", {}, h("div", {}, h("h2", { text: "Endpoints and keys" }),
        h("p", { class: "small muted", text: "Kept in this server process's memory only, never written to disk. Restarting the server clears them unless they are set as environment variables." }))),
      h("div", { style: "display:grid;gap:10px" }, CONN_FIELDS.map(([k, l, type, ph]) => field(l,
        h("input", { type, id: "conn-" + k, value: type === "password" ? "" : (conn[k].value || ""), autocomplete: "off",
          placeholder: type === "password" ? (conn[k].set ? "•••••• set (leave blank to keep)" : "not set") : ph }))),
        h("div", { class: "row end" },
          h("button", { type: "button", on: { click: () => saveConnection(true) } }, "Clear keys"),
          h("button", { type: "button", class: "primary", on: { click: () => saveConnection(false) } }, "Save")))),
    h("div", { class: "panel" },
      h("header", {}, h("div", {}, h("h2", { text: "Test the model" }), h("p", { class: "small muted", text: "Sends one tiny request and reports latency and token counts." }))),
      h("div", { style: "display:grid;gap:10px" },
        field("Provider", select("test-provider", [["router", "Auto / API model router"], ["ollama", "Ollama"], ["openai", "OpenAI-compatible / Azure"], ["mock", "Mock"]], "ollama")),
        field("Model", h("input", { type: "text", id: "test-model", placeholder: "provider default" })),
        h("div", { class: "row end" }, h("button", { type: "button", class: "primary", id: "test-run", on: { click: testConnection } }, "Test connection")),
        h("div", { id: "test-out" })))));
}
async function saveConnection(clearKeys) {
  const body = {};
  for (const [k] of CONN_FIELDS) body[k] = $("#conn-" + k).value;
  if (clearKeys) body.clear = CONN_FIELDS.filter(([, , t]) => t === "password").map(([k]) => k);
  try {
    S.config.connection = await api("POST", "/api/connection", body);
    for (const [k, , t] of CONN_FIELDS) if (t === "password") { const el = $("#conn-" + k); el.value = ""; el.placeholder = S.config.connection[k].set ? "•••••• set (leave blank to keep)" : "not set"; }
    toast(clearKeys ? "Keys cleared" : "Connection settings saved for this session");
  } catch (e) { toast(e.message, true); }
}
async function testConnection() {
  const btn = $("#test-run"); btn.disabled = true; fill($("#test-out"), h("p", { class: "small muted", text: "Testing…" }));
  try {
    const r = await api("POST", "/api/connection/test", { settings: { provider: $("#test-provider").value, model: $("#test-model").value.trim() } });
    fill($("#test-out"), r.ok
      ? h("div", { class: "callout small" }, `Connected to ${r.model} in ${r.latency_ms} ms (tokens in/out ${r.tokens_in}/${r.tokens_out}). Reply: `, h("code", { text: r.text }))
      : h("div", { class: "callout bad small", text: `Failed after ${r.latency_ms} ms: ${r.error}` }));
  } catch (e) { fill($("#test-out"), h("div", { class: "callout bad small", text: e.message })); }
  finally { btn.disabled = false; }
}

// ------------------------------------------------------------------ polling + top bar
let polling = false;
async function poll() {
  if (!S.runId || polling) return;
  polling = true;
  try {
    const run = await api("GET", `/api/runs/${S.runId}`);
    S.run = run;
    let fresh = [];
    for (let k = 0; k < 10; k++) {          // drain the trace in pages
      const ev = await api("GET", `/api/runs/${S.runId}/events?after=${S.evNext}`);
      fresh = fresh.concat(ev.events); S.evNext = ev.next;
      if (ev.events.length < 500) break;
    }
    S.events = S.events.concat(fresh).slice(-3000);
    renderRunChip();
    if (!$("#view-control").hidden) renderControl(fresh);
    if (!$("#view-results").hidden) renderResults();
  } catch (e) {
    if (/not active|no run|bad run/.test(e.message)) { setRun(null); renderRunChip(); }
  } finally { polling = false; }
}
function renderRunChip() {
  const chip = $("#runchip"), r = S.run;
  if (!r) { fill(chip); return; }
  fill(chip, h("a", { href: "#control", class: "mono small", text: r.run_id }), statusPill(r.status),
    r.control && r.control.pending ? h("a", { href: "#control", text: "answer now" }) : null);
  document.title = (r.control && r.control.pending ? "● " : "") + "SoWScout Console";
}

async function init() {
  try { S.config = await api("GET", "/api/config"); }
  catch (e) { fill(document.body, h("div", { class: "wrap", style: "padding:40px" }, h("h2", { text: "Cannot reach the SoWScout server" }), h("p", { text: e.message }))); return; }
  if (S.config.active_run) setRun(S.config.active_run);
  window.addEventListener("hashchange", route);
  if (!location.hash) location.hash = S.config.active_run ? "#control" : "#new";
  route();
  await poll();
  setInterval(() => { if (!S.run || S.run.active || S.run.status === "starting") poll(); }, 1000);
}
init();

function buildAsk() {
  fill($("#view-ask"), h("iframe", { id: "ask-frame", src: "/ask/", title: "Ask: free questions to the selected model" }));
  window.addEventListener("resize", sizeAsk);
}
function sizeAsk() {
  const f = $("#ask-frame");
  if (f) f.style.height = Math.max(420, window.innerHeight - $(".topbar").offsetHeight) + "px";
}
function askAboutRun(runId) {
  if (!S.built.ask) { buildAsk(); S.built.ask = true; }
  $("#ask-frame").src = "/ask/#attach-run=" + runId;   // the chat attaches the run's memo.md
  location.hash = "#ask";
}


const fmtPrice = (m) => (m.local ? "free (local)" : `$${Number(m.price_in).toFixed(2)} / $${Number(m.price_out).toFixed(2)}`);
const TIER = ["local", "cheap API", "premium API"];
function buildModels() {
  fill($("#view-models"),
    h("div", { class: "panel" },
      h("header", {}, h("div", {}, h("h2", { text: "Models" }),
        h("p", { class: "small muted" }, "From ", h("code", { text: "config/models.json" }), " (edit it on the ", h("a", { href: "#files", text: "Prompts & skills" }),
          " tab). Prices are per 1M tokens (input / output) and refresh from OpenRouter's model list. The OpenRouter key goes on the ",
          h("a", { href: "#connection", text: "Model connection" }), " tab.")),
        h("button", { type: "button", on: { click: () => refreshModels(true) } }, "Refresh prices & status")),
      h("div", { id: "models-info", class: "small muted" }), h("div", { id: "models-body" })),
    h("div", { class: "grid2" },
      h("div", { class: "panel" },
        h("header", {}, h("div", {}, h("h2", { text: "How Auto routing works" }))),
        h("div", { class: "small", id: "router-explain" }),
        h("h3", { style: "margin-top:14px", text: "Try the router" }),
        h("p", { class: "small muted", text: "Shows which model Ask's Auto mode would pick. Nothing is answered (rating the question uses the free local model)." }),
        h("div", { style: "display:grid;gap:8px" },
          h("textarea", { id: "route-q", rows: 3, placeholder: "e.g. Reconcile salary income, property proceeds and a third-party gift against a property purchase" }),
          h("div", { class: "row" }, check("route-private", "Chat has my files / database data", "", false), check("route-allow", "Cloud allowed", "", false)),
          h("div", { class: "row end" }, h("button", { type: "button", class: "primary", on: { click: previewRoute } }, "Which model?")),
          h("div", { id: "route-out" }))),
      h("div", { class: "panel" },
        h("header", {}, h("div", {}, h("h2", { text: "My database (SQLite)" }),
          h("p", { class: "small muted", text: "The AI can read it (SELECT only) in Ask and, if you tick it, in runs. Its data is private: it stays on local models unless you allow cloud." }))),
        h("div", { style: "display:grid;gap:10px" },
          field("Database file", h("input", { type: "text", id: "db-path", placeholder: "C:/Users/you/Documents/clients.sqlite" }), "Full path to a .sqlite / .db file on this computer. Empty = no database."),
          field("What is in it (helps the AI)", h("textarea", { id: "db-notes", rows: 3, placeholder: "e.g. clients = customer records; payments = dated transfers; amounts in HKD" })),
          h("div", { class: "row end" }, h("button", { type: "button", class: "primary", on: { click: saveDatabase } }, "Save & test")),
          h("div", { id: "db-out" })))));
  loadDatabase();
}
async function refreshModels(force) {
  const body = $("#models-body");
  if (!body) return;
  fill(body, h("p", { class: "small muted", text: "Checking Ollama and OpenRouter…" }));
  try {
    const r = await api("GET", "/api/models" + (force ? "?refresh=1" : ""));
    const missing = Object.entries(r.keys || {}).filter(([, ok]) => !ok).map(([p]) => p);
    fill($("#models-info"), r.info.map((x) => h("div", { text: x })), missing.length ? h("div", { class: "callout warn small", style: "margin:8px 0" },
      `No API key for: ${missing.join(", ")}. Their models are skipped (Auto uses the others, or local models). Add keys on `, h("a", { href: "#connection", text: "Model connection" }), ".") : null);
    fill(body, h("div", { class: "tbl" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Name", "Model", "Kind", "Price in / out", "Context", "Can do", "Status", ""].map((x) => h("th", { text: x })))),
      h("tbody", {}, r.models.map((m) => h("tr", {},
        h("td", {}, h("b", { text: m.alias })), h("td", {}, m.label, h("div", { class: "small muted mono", text: m.id })),
        h("td", {}, TIER[m.tier] || "tier " + m.tier, m.local ? null : h("div", { class: "small muted", text: "via " + m.provider })), h("td", { class: "small", text: fmtPrice(m) }),
        h("td", { class: "num small", text: fmtNum(m.context) }),
        h("td", { class: "small", text: [m.tools && "tools", m.vision && "images", m.thinking && "thinking", m.json_schema && "JSON schema"].filter(Boolean).join(", ") }),
        h("td", { class: "small" }, m.available ? h("span", { class: "pill done", text: "ready" }) : h("span", { class: "pill error", text: m.why }), m.notes.map((n) => h("div", { class: "muted", text: n }))),
        h("td", {}, h("button", { type: "button", class: "small", on: { click: (e) => testModel(m.alias, e.target) } }, "Test"))))))));
    const rt = r.router;
    fill($("#router-explain"),
      h("p", {}, "Ask: a free local model (", h("code", { text: rt.classifier }), ") rates each question, then the first model in its list that passes the checks answers:"),
      h("ul", {}, Object.entries(rt.ask || {}).map(([k, v]) => h("li", {}, h("b", { text: k }), ": " + v.join(" → ")))),
      h("p", {}, "Runs: each step has its own list; after a failed step (broken JSON, rejected verdict) that step moves up a tier:"),
      h("ul", {}, Object.entries(rt.run || {}).map(([k, v]) => h("li", {}, h("b", { text: k }), ": " + v.join(" → ")))),
      h("p", { class: "muted", text: "Checks, in order: private data stays local unless allowed · the model can do tools / images / long context · key set or model downloaded · the call fits the task's cost limit. Type @claude (or any name) in an Ask message to choose yourself." }));
  } catch (e) { fill(body, h("div", { class: "callout bad", text: e.message })); }
}
async function testModel(alias, btn) {
  btn.disabled = true; btn.textContent = "…";
  try {
    const r = await api("POST", "/api/models/test", { model: alias });
    toast(r.ok ? `${alias}: answered in ${r.latency_ms} ms, ${r.tokens_in}+${r.tokens_out} tokens, $${r.cost_usd.toFixed(5)}` : `${alias}: ${r.error}`, !r.ok);
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "Test"; }
}
async function previewRoute() {
  const out = $("#route-out");
  fill(out, h("p", { class: "small muted", text: "Asking the router…" }));
  try {
    const r = await api("POST", "/api/models/route", { question: $("#route-q").value, private: $("#route-private").checked, allow_cloud: $("#route-allow").checked });
    fill(out, r.ok ? h("div", { class: "callout small" }, h("b", { text: "→ " + r.label }), ` (${r.local ? "local, free" : TIER[r.tier]}) · ${r.reason}`)
      : h("div", { class: "callout bad small", text: r.error }));
  } catch (e) { fill(out, h("div", { class: "callout bad small", text: e.message })); }
}
function renderDatabase(d) {
  $("#db-path").value = d.database_path || ""; $("#db-notes").value = d.database_notes || "";
  $("#db-path").disabled = d.from_env;
  fill($("#db-out"), d.error ? h("div", { class: "callout bad small", text: d.error }) : !d.connected ? h("p", { class: "small muted", text: "No database connected." })
    : h("div", {}, h("p", { class: "small" }, h("b", { text: d.name }), ` · ${d.tables.length} tables (read-only)`, d.from_env ? " · set by SOWSCOUT_DATA_DB" : ""),
      h("div", { class: "tbl" }, h("table", {}, h("thead", {}, h("tr", {}, ["Table", "Rows", "Columns"].map((x) => h("th", { text: x })))),
        h("tbody", {}, d.tables.map((t) => h("tr", {}, h("td", { class: "mono", text: t.name }), h("td", { class: "num", text: fmtNum(t.rows) }), h("td", { class: "small", text: t.columns.join(", ") }))))))));
}
async function loadDatabase() { try { renderDatabase(await api("GET", "/api/database")); } catch (e) { toast(e.message, true); } }
async function saveDatabase() {
  try { renderDatabase(await api("POST", "/api/database", { database_path: $("#db-path").value.trim(), database_notes: $("#db-notes").value })); toast("Database settings saved"); S.config.database = !!$("#db-path").value.trim(); }
  catch (e) { fill($("#db-out"), h("div", { class: "callout bad small", text: e.message })); }
}

