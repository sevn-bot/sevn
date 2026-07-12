/** Inline fallback when ``GET /api/v1/dashboard/nav`` is unavailable (offline tests). */
const INLINE_GROUPS = [
  ["Core", ["Overview", "Chat", "Canvas (OpenUI)", "Sessions"]],
  ["Observability", ["Traces", "Audit & Analytics", "Providers & LLMs", "Budget & Cost", "Channels", "Sub-agents", "Alerts & Logs"]],
  ["Agent", ["Agent Config", "Model Params", "Tools & Permissions", "Skills", "MCP Servers", "Coding Agents"]],
  ["Knowledge", ["Memory", "Second Brain", "Workspace Files", "Code Understanding"]],
  ["Self-improve", ["Jobs", "Trajectories", "Feedback", "RLM Config", "Experiments & Metrics"]],
  ["Evolution", ["Issues", "Pipelines", "Approvals", "Spec-Kit", "Evolution Traces", "Stats"]],
  ["Ops", ["Cron", "Security", "Secrets", "Egress proxy", "Tunnels & Infra", "Backup & Snapshots", "Config", "Schema & Ontology", "sevn CLI", "Terminal"]],
  ["Surfaces", ["Telegram Menu", "Web Apps", "Onboarding", "Users & RBAC"]],
];

const INLINE_WIRED_SLUGS = [
  "overview",
  "chat",
  "canvas-openui",
  "sessions",
  "traces",
  "audit-analytics",
  "budget-cost",
  "providers-llms",
  "channels",
  "sub-agents",
  "alerts-logs",
  "jobs",
  "issues",
  "pipelines",
  "approvals",
  "evolution-traces",
  "stats",
  "spec-kit",
  "cron",
  "security",
  "secrets",
  "egress-proxy",
  "tunnels-infra",
  "backup-snapshots",
  "config",
  "schema-ontology",
  "sevn-cli",
  "terminal",
  "memory",
  "second-brain",
  "workspace-files",
  "code-understanding",
  "agent-config",
  "model-params",
  "tools-permissions",
  "skills",
  "mcp-servers",
  "coding-agents",
  "trajectories",
  "feedback",
  "rlm-training",
  "experiments-metrics",
  "telegram-menu",
  "web-apps",
  "onboarding",
  "users-rbac",
];

const SLUG_OVERRIDES = {
  "RLM Config": "rlm-training",
};
const slug = (name) =>
  SLUG_OVERRIDES[name] ??
  name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

const OPS_CONFIRM_TOKEN = "confirm";

function opsConfirmBody() {
  return { confirm_token: OPS_CONFIRM_TOKEN };
}

let groups = INLINE_GROUPS;
let tabs = [];
let wiredSlugs = new Set(INLINE_WIRED_SLUGS);
let postV1Slugs = new Set([]);

function rebuildTabsFromGroups() {
  tabs = groups.flatMap(([group, names]) =>
    names.map((name) => ({ group, name, path: `/mission/${slug(name)}` })),
  );
}

function applyNavPayload(payload) {
  if (Array.isArray(payload?.groups) && payload.groups.length) {
    if (typeof payload.groups[0]?.name === "string") {
      groups = payload.groups.map((g) => [g.name, g.tabs.map((t) => t.name)]);
    } else {
      groups = payload.groups;
    }
  }
  if (Array.isArray(payload?.wired_slugs)) {
    wiredSlugs = new Set(payload.wired_slugs);
  }
  if (Array.isArray(payload?.post_v1_placeholder_slugs)) {
    postV1Slugs = new Set(payload.post_v1_placeholder_slugs);
  }
  rebuildTabsFromGroups();
}

rebuildTabsFromGroups();

const nav = document.querySelector("#tabs");
const content = document.querySelector("#content");
const searchInput = document.querySelector("#global-search");
const authBadge = document.querySelector("#auth-badge");
const loginPanel = document.querySelector("#login-panel");
const loginForm = document.querySelector("#login-form");
const loginPassword = document.querySelector("#login-password");
const loginError = document.querySelector("#login-error");
const proxyHealthBadge = document.querySelector("#proxy-health-badge");
const providerHealthBadge = document.querySelector("#provider-health-badge");
const approvalPendingBadge = document.querySelector("#approval-pending-badge");
const systemMenuToggle = document.querySelector("#system-menu-toggle");
const systemMenuPanel = document.querySelector("#system-menu-panel");
const commandPalette = document.querySelector("#command-palette");
const paletteQuery = document.querySelector("#palette-query");
const paletteResults = document.querySelector("#palette-results");
const logRetentionModal = document.querySelector("#log-retention-modal");
const logRetentionForm = document.querySelector("#log-retention-form");
const loggingRetentionDays = document.querySelector("#logging-retention-days");
const loggingArchiveMode = document.querySelector("#logging-archive-mode");
const loggingArchiveDestination = document.querySelector("#logging-archive-destination");
const logRetentionError = document.querySelector("#log-retention-error");

let authRequired = true;
let localOpen = false;
let dashboardAccessToken = null;
let dashboardWs = null;
let evolutionWsRefreshTimer = null;
let evolutionWsIssueIds = [];
let liveActivityEvents = [];
let budgetAlertBanner = null;
let chatSocket = null;
let chatSessionId = null;
let chatWebchatToken = null;
let pendingToolApprovals = [];
let chatStreamingBody = null;
let chatToolCardsHost = null;
let terminalSocket = null;
let terminalXterm = null;

function dashboardJwtFromCookie() {
  const match = document.cookie.match(/(?:^|;\s*)sevn_dashboard_session=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function terminalB64Encode(data) {
  const bytes = new TextEncoder().encode(data);
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary);
}

function terminalB64Decode(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

function csrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)sevn_dashboard_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function apiGet(path) {
  const resp = await fetch(path, { credentials: "include" });
  if (!resp.ok) {
    throw new Error(`${resp.status} ${path}`);
  }
  return resp.json();
}

function updateAuthChrome() {
  if (authBadge) {
    if (localOpen) {
      authBadge.hidden = false;
      authBadge.textContent = "Local session (no login)";
      authBadge.className = "badge badge-info";
    } else {
      authBadge.hidden = true;
      authBadge.textContent = "";
    }
  }
  if (loginPanel) {
    loginPanel.hidden = !authRequired;
  }
}

async function ensureAuthenticated() {
  const status = await apiGet("/api/v1/auth/status");
  authRequired = Boolean(status.auth_required);
  localOpen = Boolean(status.local_open);
  updateAuthChrome();
  if (!authRequired) {
    return;
  }
  const probe = await fetch("/api/v1/sessions?limit=1", { credentials: "include" });
  if (probe.ok) {
    authRequired = false;
    if (loginPanel) loginPanel.hidden = true;
    return;
  }
  if (loginPanel) loginPanel.hidden = false;
  throw new Error("authentication required");
}

async function apiPost(path, body = {}) {
  const resp = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(`${resp.status} ${path}`);
  }
  return resp.json();
}

async function apiDelete(path) {
  const resp = await fetch(path, {
    method: "DELETE",
    credentials: "include",
    headers: {
      "X-CSRF-Token": csrfToken(),
    },
  });
  if (!resp.ok) {
    throw new Error(`${resp.status} ${path}`);
  }
  if (resp.status === 204) {
    return null;
  }
  return resp.json();
}

const IDENTITY_SHORTCUTS = [
  { label: "SOUL.md", path: "SOUL.md" },
  { label: "USER.md", path: "USER.md" },
  { label: "AGENTS.md", path: "AGENTS.md" },
  { label: "MEMORY.md", path: "MEMORY.md" },
];

function missionEditorShell(opts = {}) {
  const {
    idPrefix = "file-editor",
    selectedPath = "",
    content = "",
    statusMsg = "",
    mode = "file",
    rows = 20,
  } = opts;
  const isFile = mode === "file";
  const shortcuts = isFile
    ? IDENTITY_SHORTCUTS.map(
        (s) =>
          `<button type="button" class="btn btn-secondary btn-sm file-open-btn" data-file-path="${escapeHtml(s.path)}">${escapeHtml(s.label)}</button>`,
      ).join(" ")
    : "";
  const toolbar = isFile
    ? `
      <div class="file-editor-toolbar">
        <label>File <input type="text" id="file-editor-path" class="field-input" value="${escapeHtml(selectedPath || "")}" placeholder="path/to/file.md" /></label>
        <button type="button" class="btn btn-primary" id="file-editor-save">Save</button>
        <button type="button" class="btn btn-secondary" id="file-editor-reload">Reload</button>
        <button type="button" class="btn btn-secondary" id="file-editor-new">New file</button>
        <button type="button" class="btn btn-secondary" id="file-editor-delete">Delete</button>
      </div>
      <p class="muted">Identity shortcuts: ${shortcuts}</p>`
    : "";
  const textareaId = isFile ? "file-editor-content" : idPrefix;
  const statusId = isFile ? "file-editor-status" : `${idPrefix}-status`;
  return `
    <div class="file-editor-panel mission-editor-panel" data-editor-mode="${escapeHtml(mode)}">
      ${toolbar}
      <textarea id="${escapeHtml(textareaId)}" class="file-editor mission-editor config-editor" rows="${rows}" spellcheck="false">${escapeHtml(content || "")}</textarea>
      <p id="${escapeHtml(statusId)}" class="muted">${escapeHtml(statusMsg)}</p>
    </div>
  `;
}

function fileEditorShell(selectedPath, content, statusMsg = "") {
  return missionEditorShell({ selectedPath, content, statusMsg, mode: "file" });
}

async function loadFileIntoEditor(path) {
  const data = await apiGet(`/api/v1/files/content?path=${encodeURIComponent(path)}`);
  const pathEl = document.querySelector("#file-editor-path");
  const contentEl = document.querySelector("#file-editor-content");
  const statusEl = document.querySelector("#file-editor-status");
  if (pathEl) pathEl.value = data.path || path;
  if (contentEl) contentEl.value = data.content || "";
  if (statusEl) {
    statusEl.textContent = data.redacted
      ? "Secret refs redacted in display — save carefully."
      : `Loaded ${data.size ?? 0} bytes`;
  }
}

function bindFileEditorHandlers() {
  document.querySelectorAll(".file-open-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const path = btn.getAttribute("data-file-path");
      if (path) loadFileIntoEditor(path).catch((err) => alert(err.message));
    });
  });
  document.querySelector("#file-editor-save")?.addEventListener("click", async () => {
    const path = document.querySelector("#file-editor-path")?.value?.trim();
    const content = document.querySelector("#file-editor-content")?.value ?? "";
    const statusEl = document.querySelector("#file-editor-status");
    if (!path) return;
    try {
      await apiPut("/api/v1/files/content", { path, content, create_parents: true });
      if (statusEl) statusEl.textContent = "Saved.";
    } catch (err) {
      if (statusEl) statusEl.textContent = err.message;
    }
  });
  document.querySelector("#file-editor-reload")?.addEventListener("click", () => {
    const path = document.querySelector("#file-editor-path")?.value?.trim();
    if (path) loadFileIntoEditor(path).catch((err) => alert(err.message));
  });
  document.querySelector("#file-editor-new")?.addEventListener("click", async () => {
    const path = window.prompt("New file path (workspace-relative):");
    if (!path) return;
    try {
      await apiPost("/api/v1/files", { path, content: "" });
      await loadFileIntoEditor(path);
    } catch (err) {
      alert(err.message);
    }
  });
  document.querySelector("#file-editor-delete")?.addEventListener("click", async () => {
    const path = document.querySelector("#file-editor-path")?.value?.trim();
    if (!path || !window.confirm(`Soft-delete ${path}?`)) return;
    try {
      await apiDelete(`/api/v1/files?path=${encodeURIComponent(path)}&soft=1`);
      const statusEl = document.querySelector("#file-editor-status");
      if (statusEl) statusEl.textContent = "Moved to .sevn/trash/";
    } catch (err) {
      alert(err.message);
    }
  });
}

async function apiPut(path, body = {}) {
  const resp = await fetch(path, {
    method: "PUT",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
    },
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = new Error(data?.error?.message || `${resp.status} ${path}`);
    err.status = resp.status;
    err.body = data;
    throw err;
  }
  return data;
}

let configDraft = null;
let configMeta = null;
let configEditorMode = "tree";

function setConfigAtPath(obj, path, value) {
  const parts = path.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i += 1) {
    const key = parts[i];
    const next = parts[i + 1];
    if (/^\d+$/.test(next)) {
      if (!Array.isArray(cur[key])) {
        cur[key] = [];
      }
      cur = cur[key];
      i += 1;
      const idx = Number(parts[i]);
      while (cur.length <= idx) {
        cur.push(null);
      }
      if (i === parts.length - 1) {
        cur[idx] = value;
        return;
      }
      if (cur[idx] === null || typeof cur[idx] !== "object") {
        cur[idx] = /^\d+$/.test(parts[i + 1]) ? [] : {};
      }
      cur = cur[idx];
      continue;
    }
    if (cur[key] === null || typeof cur[key] !== "object" || Array.isArray(cur[key])) {
      cur[key] = {};
    }
    cur = cur[key];
  }
  const last = parts[parts.length - 1];
  if (/^\d+$/.test(last) && Array.isArray(cur)) {
    cur[Number(last)] = value;
  } else {
    cur[last] = value;
  }
}

function configScalarInput(path, value) {
  if (typeof value === "boolean") {
    return `<label class="config-tree-bool"><input type="checkbox" data-config-path="${escapeHtml(path)}" ${value ? "checked" : ""} /></label>`;
  }
  if (typeof value === "number") {
    return `<input type="number" class="input config-tree-input" data-config-path="${escapeHtml(path)}" value="${escapeHtml(String(value))}" />`;
  }
  const text = value === null ? "null" : typeof value === "string" ? value : JSON.stringify(value);
  return `<input type="text" class="input config-tree-input" data-config-path="${escapeHtml(path)}" value="${escapeHtml(text)}" spellcheck="false" />`;
}

function renderConfigTreeNode(key, value, pathPrefix) {
  const nodePath = pathPrefix ? `${pathPrefix}.${key}` : key;
  if (Array.isArray(value)) {
    const inner = value
      .map((item, idx) => renderConfigTreeNode(String(idx), item, nodePath))
      .join("");
    return `<details open class="config-tree-node"><summary><code>${escapeHtml(key)}</code> <span class="muted">[${value.length}]</span></summary>${inner}</details>`;
  }
  if (value !== null && typeof value === "object") {
    const inner = Object.entries(value)
      .map(([childKey, childVal]) => renderConfigTreeNode(childKey, childVal, nodePath))
      .join("");
    return `<details open class="config-tree-node"><summary><code>${escapeHtml(key)}</code></summary>${inner}</details>`;
  }
  return `<div class="config-tree-row"><span class="config-tree-key"><code>${escapeHtml(key)}</code></span>${configScalarInput(nodePath, value)}</div>`;
}

function renderConfigTreeMarkup(doc) {
  if (!doc || typeof doc !== "object") {
    return `<p class="muted">Empty config document.</p>`;
  }
  return Object.entries(doc)
    .map(([key, value]) => renderConfigTreeNode(key, value, ""))
    .join("");
}

function syncConfigDraftFromTree(rootEl) {
  if (!configDraft || !(rootEl instanceof HTMLElement)) {
    return;
  }
  rootEl.querySelectorAll("[data-config-path]").forEach((el) => {
    if (!(el instanceof HTMLInputElement)) {
      return;
    }
    const path = el.dataset.configPath || "";
    let val;
    if (el.type === "checkbox") {
      val = el.checked;
    } else if (el.type === "number") {
      val = Number(el.value);
    } else if (el.value === "null") {
      val = null;
    } else {
      try {
        val = JSON.parse(el.value);
      } catch {
        val = el.value;
      }
    }
    setConfigAtPath(configDraft, path, val);
  });
}

function formatConfigErrors(body) {
  const rows = body?.errors;
  if (!Array.isArray(rows) || !rows.length) {
    return body?.error?.message || "Validation failed.";
  }
  return rows.map((row) => `${row.path}: ${row.message}`).join("\n");
}

function renderNav() {
  nav.innerHTML = "";
  const path = location.pathname;
  const activeSlug =
    path === "/mission" || path === "/mission/"
      ? "overview"
      : path.replace(/^\/mission\/?/, "").split("/")[0];

  for (const [groupName, names] of groups) {
    const group = document.createElement("div");
    group.className = "sidebar__group";
    const hasActive = names.some((name) => slug(name) === activeSlug);
    group.dataset.expanded = hasActive ? "true" : "false";

    const header = document.createElement("button");
    header.type = "button";
    header.className = "sidebar__group-header";
    header.innerHTML = `${groupName}<svg class="chev" viewBox="0 0 10 10" aria-hidden="true"><path d="M3 1l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
    header.addEventListener("click", () => {
      group.dataset.expanded = group.dataset.expanded === "true" ? "false" : "true";
    });

    const items = document.createElement("div");
    items.className = "sidebar__group-items";

    for (const name of names) {
      const tab = tabs.find((t) => t.group === groupName && t.name === name);
      if (!tab) continue;
      const link = document.createElement("a");
      link.href = tab.path;
      link.className = "sidebar__item";
      link.innerHTML = `<span class="sidebar__label">${name}</span>`;
      if (slug(name) === activeSlug || (activeSlug === "overview" && name === "Overview")) {
        link.setAttribute("aria-current", "page");
      }
      items.appendChild(link);
    }

    group.appendChild(header);
    group.appendChild(items);
    nav.appendChild(group);
  }
}

function executorBadge(issue) {
  const exec = issue.executor || issue.configured_executor || "local";
  const labelMap = { cursor_cloud: "Cursor Cloud", chat: "Chat", local: "Local" };
  const label = labelMap[exec] || exec;
  const clsMap = { cursor_cloud: "badge badge-info", chat: "badge badge-warning", local: "badge badge-muted" };
  const cls = clsMap[exec] || "badge badge-muted";
  const link = issue.external_url || issue.agent_url || issue.pr_url;
  const linkHtml = link
    ? ` <a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">Open</a>`
    : "";
  return `<span class="${cls}">${label}</span>${linkHtml}`;
}

/** Redact a filesystem path to its last two components for display in MC. */
function _redactPath(p) {
  if (!p) return "";
  const parts = String(p).replace(/\\/g, "/").split("/").filter(Boolean);
  const tail = parts.slice(-2).join("/");
  return tail ? `…/${tail}` : String(p);
}

function tableFromRows(rows, columns) {
  if (!rows.length) {
    return "<p class=\"muted\">No rows yet.</p>";
  }
  const head = columns.map((c) => `<th>${c.label}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns.map((c) => `<td>${row[c.key] ?? ""}</td>`).join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  return `<table class="table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

const SECRETS_MASK = "••••••••";
const SECRETS_REVEAL_FAILED = "<reveal failed>";

function secretsValueCell(kind, key) {
  return `<td class="secrets-value-cell" data-secret-kind="${escapeHtml(kind)}" data-secret-key="${escapeHtml(key)}">${SECRETS_MASK}</td>`;
}

function secretsAliasesTable(rows) {
  if (!rows.length) {
    return "<p class=\"muted\">No config aliases yet.</p>";
  }
  const body = rows
    .map(
      (row) => `<tr>
      <td>${escapeHtml(row.logical_key)}</td>
      <td>${escapeHtml(row.source)}</td>
      ${secretsValueCell("config-alias", row.logical_key)}
    </tr>`,
    )
    .join("");
  return `<table class="table secrets-aliases-table"><thead><tr><th>Alias</th><th>Source</th><th>Value</th></tr></thead><tbody>${body}</tbody></table>`;
}

function secretsStoreTable(rows) {
  if (!rows.length) {
    return "<p class=\"muted\">No store entries yet.</p>";
  }
  const body = rows
    .map(
      (row) => `<tr>
      <td>${escapeHtml(row.alias)}</td>
      <td>${escapeHtml(row.fingerprint)}</td>
      ${secretsValueCell("store-entry", row.alias)}
    </tr>`,
    )
    .join("");
  return `<table class="table secrets-store-table"><thead><tr><th>Alias</th><th>Fingerprint</th><th>Value</th></tr></thead><tbody>${body}</tbody></table>`;
}

function sessionApiCallsPath() {
  const parts = location.pathname.split("/").filter(Boolean);
  const idx = parts.indexOf("sessions");
  if (idx >= 0 && parts[idx + 1] && parts[idx + 2] === "api-calls") {
    return parts[idx + 1];
  }
  return null;
}

function resolveActiveTab() {
  const sessionId = sessionApiCallsPath();
  if (sessionId) {
    const sessionsTab = tabs.find((t) => slug(t.name) === "sessions");
    if (sessionsTab) return sessionsTab;
  }
  const path = location.pathname;
  const exact = tabs.find((item) => item.path === path);
  if (exact) return exact;
  const slugFromPath = path.replace(/^\/mission\/?/, "").split("/")[0];
  if (slugFromPath) {
    const bySlug = tabs.find((t) => slug(t.name) === slugFromPath);
    if (bySlug) return bySlug;
  }
  return tabs[0];
}

function renderLiveActivityHtml() {
  if (!liveActivityEvents.length) {
    return `<p class="muted empty-state">Mission events from <code>/ws/dashboard</code> appear here (file writes, ops, budget alerts).</p>`;
  }
  return `<ul class="mission-live-activity-list">${liveActivityEvents
    .slice(0, 12)
    .map(
      (ev) =>
        `<li><span class="muted">${escapeHtml(ev.label || ev.topic || "event")}</span> · ${escapeHtml(ev.detail || "")}</li>`,
    )
    .join("")}</ul>`;
}

function refreshLiveActivityDom() {
  const el = document.querySelector("#live-activity-feed");
  if (el) el.innerHTML = renderLiveActivityHtml();
}

function pushLiveActivity(topic, payload) {
  const kind = payload?.kind || payload?.event_type || topic;
  const detail =
    payload?.path || payload?.alias || payload?.message || (payload?.alerts?.[0]?.message ?? "") || JSON.stringify(payload).slice(0, 80);
  liveActivityEvents.unshift({
    topic,
    label: String(kind),
    detail: String(detail),
    ts: Date.now(),
  });
  liveActivityEvents = liveActivityEvents.slice(0, 20);
  refreshLiveActivityDom();
}

function paletteTabItems() {
  return tabs.map((t) => ({
    type: "tab",
    label: t.name,
    group: t.group,
    href: t.path,
  }));
}

function renderPaletteNavItems(matches) {
  if (!matches.length) return "";
  return `<p class="muted">Navigate</p>${matches
    .map(
      (item) =>
        `<button type="button" class="mission-palette-item" data-palette-href="${escapeHtml(item.href)}">${escapeHtml(item.label)} <span class="muted">· ${escapeHtml(item.group)}</span></button>`,
    )
    .join("")}`;
}

function overviewStatCard(label, value, deltaHtml = "") {
  const delta = deltaHtml ? `<span class="stat-card__delta">${deltaHtml}</span>` : "";
  return `
    <div class="stat-card">
      <span class="stat-card__label">${escapeHtml(label)}</span>
      <span class="stat-card__value">${escapeHtml(String(value))}</span>
      ${delta}
    </div>
  `;
}

function proxyStatusLabel(proxy) {
  if (!proxy?.configured) return "Proxy off";
  return proxy.ok ? "Proxy up" : "Proxy down";
}

function providerStatusLabel(health) {
  const providers = Array.isArray(health?.providers) ? health.providers : [];
  if (!providers.length && health?.id) {
    return health.ok ? "Providers ok" : "Provider degraded";
  }
  const degraded = providers.filter((row) => !row.ok).length;
  if (!providers.length) return "Providers …";
  if (degraded === 0) return "Providers ok";
  return `${degraded} degraded`;
}

async function renderOverview() {
  const [snapshots, budget, proxy, sessions, providers] = await Promise.all([
    apiGet("/api/v1/runs/snapshots?limit=10"),
    apiGet("/api/v1/budget/summary"),
    apiGet("/api/v1/proxy/status"),
    apiGet("/api/v1/sessions?limit=200"),
    apiGet("/api/v1/providers/health").catch(() => ({ providers: [] })),
  ]);
  updateProxyHealthBadge(proxy);
  updateProviderHealthBadge(providers);

  const sessionItems = sessions.items || [];
  const activeSessions = sessionItems.filter((s) => Number(s.active_runs || 0) > 0).length;
  const activeRuns = (snapshots.items || []).filter((r) => r.status === "active").length;
  const regimeRows = budget.by_regime || [];
  const windows = budget.subscription_windows || [];
  const proxyDeltaClass = proxy.ok ? "stat-card__delta--up" : "stat-card__delta--alert";
  const providerDeltaClass =
    providerStatusLabel(providers).includes("ok") || providerStatusLabel(providers).includes("…")
      ? "stat-card__delta--up"
      : "stat-card__delta--alert";

  return `
    <div class="mission-overview-badges" aria-live="polite">
      <span class="badge ${proxy.ok ? "badge-success" : proxy.configured ? "badge-warning" : "badge-muted"}">${escapeHtml(proxyStatusLabel(proxy))}</span>
      <span class="badge badge-info">${escapeHtml(providerStatusLabel(providers))}</span>
      <span class="muted">Live via WebSocket · <code>proxy.health</code> · <code>provider.health</code></span>
    </div>
    <div class="mission-overview-grid">
      ${overviewStatCard("Active sessions", activeSessions)}
      ${overviewStatCard("Active runs", activeRuns)}
      ${overviewStatCard("Sessions listed", sessionItems.length)}
      ${overviewStatCard("Proxy", proxyStatusLabel(proxy), `<span class="${proxyDeltaClass}">${proxy.configured ? (proxy.ok ? "healthz ok" : "healthz failed") : "not configured"}</span>`)}
      ${overviewStatCard("Providers", providerStatusLabel(providers), `<span class="${providerDeltaClass}">shell badges</span>`)}
    </div>
    <h3>Live activity</h3>
    <div id="live-activity-feed" class="mission-live-activity" aria-live="polite">
      ${renderLiveActivityHtml()}
    </div>
    <h3>Active run snapshots</h3>
    ${tableFromRows(snapshots.items || [], [
      { key: "run_id", label: "Run" },
      { key: "session_id", label: "Session" },
      { key: "tier", label: "Tier" },
      { key: "status", label: "Status" },
      { key: "excerpt", label: "Excerpt" },
    ])}
    <h3>Recent sessions</h3>
    ${tableFromRows(sessionItems.slice(0, 8), [
      { key: "session_id", label: "Session" },
      { key: "channel", label: "Channel" },
      { key: "active_runs", label: "Active runs" },
    ])}
    <h3>Budget by regime</h3>
    ${tableFromRows(regimeRows, [
      { key: "regime", label: "Regime" },
      { key: "call_count", label: "Calls" },
      { key: "tokens_in", label: "Tokens in" },
      { key: "tokens_out", label: "Tokens out" },
    ])}
    <h3>Subscription windows</h3>
    ${tableFromRows(windows, [
      { key: "model_id", label: "Model" },
      { key: "window_remaining", label: "Remaining" },
      { key: "subscription_window_id", label: "Window id" },
    ])}
  `;
}

function disconnectChatConsole() {
  chatStreamingBody = null;
  chatToolCardsHost = null;
  if (chatSocket) {
    chatSocket.close();
    chatSocket = null;
  }
}

function disconnectTerminal() {
  if (terminalSocket) {
    terminalSocket.close();
    terminalSocket = null;
  }
  if (terminalXterm) {
    terminalXterm.dispose();
    terminalXterm = null;
  }
}

function setTerminalStatus(state, label) {
  const el = document.querySelector("#terminal-status");
  if (!el) return;
  el.textContent = label || state;
  el.className = `badge ${state === "connected" ? "badge-success" : state === "connecting" ? "badge-info" : state === "error" ? "badge-warning" : "badge-muted"}`;
}

function terminalWrite(text) {
  if (terminalXterm) {
    terminalXterm.write(text);
    return;
  }
  const pre = document.querySelector("#terminal-fallback");
  if (pre) pre.textContent += text;
}

async function connectTerminalConsole() {
  disconnectTerminal();
  setTerminalStatus("connecting", "connecting…");
  const body = await apiPost("/api/v1/terminal/session", {});
  const mount = document.querySelector("#terminal-mount");
  if (mount && typeof Terminal !== "undefined") {
    terminalXterm = new Terminal({
      cursorBlink: true,
      fontFamily: "Geist Mono, ui-monospace, monospace",
      theme: { background: "transparent" },
    });
    terminalXterm.open(mount);
    terminalXterm.writeln("Connecting to sandbox shell…");
    terminalXterm.onData((data) => {
      if (!terminalSocket || terminalSocket.readyState !== 1) return;
      terminalSocket.send(JSON.stringify({ type: "stdin", data: terminalB64Encode(data) }));
    });
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const wsPath = body.ws_path || "/ws/dashboard/terminal";
  terminalSocket = new WebSocket(`${proto}://${location.host}${wsPath}`);
  terminalSocket.addEventListener("open", () => {
    if (!localOpen) {
      terminalSocket.send(
        JSON.stringify({
          type: "auth",
          token: dashboardJwtFromCookie(),
          csrf: csrfToken(),
          session_id: body.session_id,
        }),
      );
    }
  });
  terminalSocket.addEventListener("close", () => setTerminalStatus("error", "disconnected"));
  terminalSocket.addEventListener("error", () => setTerminalStatus("error", "error"));
  terminalSocket.addEventListener("message", (ev) => {
    let frame;
    try {
      frame = JSON.parse(ev.data);
    } catch (_err) {
      return;
    }
    if (!frame || typeof frame !== "object") return;
    switch (frame.type) {
      case "ready":
        setTerminalStatus("connected", `sandbox ${frame.driver || ""}`.trim());
        terminalWrite(`\r\n[session ${(frame.session_id || "").slice(0, 8)} · max ${frame.max_lifetime_s || "?"}s]\r\n`);
        break;
      case "stdout":
        if (frame.data) terminalWrite(terminalB64Decode(frame.data));
        break;
      case "error":
        terminalWrite(`\r\n[error: ${frame.code || ""} ${frame.message || ""}]\r\n`);
        if (frame.code === "self_preservation") setTerminalStatus("error", "blocked");
        break;
      case "close":
        terminalWrite(`\r\n[closed: ${frame.reason || "done"}]\r\n`);
        disconnectTerminal();
        break;
      default:
        break;
    }
  });
}

function bindTerminalHandlers() {
  document.querySelector("#terminal-connect-btn")?.addEventListener("click", () => {
    connectTerminalConsole().catch((err) => {
      setTerminalStatus("error", err.message);
    });
  });
  document.querySelector("#terminal-disconnect-btn")?.addEventListener("click", () => {
    disconnectTerminal();
    setTerminalStatus("muted", "idle");
  });
}

function setChatStatus(state, label) {
  const el = document.querySelector("#chat-status");
  if (!el) return;
  el.textContent = label || state;
  el.className = `badge ${state === "connected" ? "badge-success" : state === "connecting" ? "badge-info" : state === "error" ? "badge-warning" : "badge-muted"}`;
}

function appendChatBubble(text, role) {
  const log = document.querySelector("#chat-log");
  if (!log) return null;
  const who = role === "user" ? "user" : role === "error" ? "error" : "assistant";
  const msg = document.createElement("article");
  msg.className = `msg ${who === "user" ? "msg--user" : who === "error" ? "msg--error" : "msg--assistant"}`;
  const meta = document.createElement("div");
  meta.className = "msg__meta";
  const whoEl = document.createElement("span");
  whoEl.className = `who who--${who === "user" ? "user" : "assistant"}`;
  whoEl.textContent = who === "user" ? "You" : who === "error" ? "Error" : "sevn";
  meta.appendChild(whoEl);
  const body = document.createElement("div");
  body.className = "msg__body";
  body.textContent = text;
  msg.appendChild(meta);
  msg.appendChild(body);
  log.appendChild(msg);
  msg.scrollIntoView({ block: "end" });
  return body;
}

function ensureChatStreamingBubble() {
  if (!chatStreamingBody) {
    chatStreamingBody = appendChatBubble("", "assistant");
  }
  return chatStreamingBody;
}

function finishChatStreamingBubble() {
  chatStreamingBody = null;
}

function appendChatToolCard(frame) {
  const host = chatToolCardsHost || document.querySelector("#chat-tool-cards");
  if (!host) return;
  const card = document.createElement("div");
  card.className = "mission-chat-tool-card card";
  const title = frame.type === "tool_result" ? "Tool result" : "Tool call";
  const name = frame.tool_name || frame.name || "tool";
  const summary = frame.summary || frame.text || JSON.stringify(frame.args || frame.result || {});
  card.innerHTML = `<strong>${escapeHtml(title)}:</strong> <code>${escapeHtml(String(name))}</code><pre class="mission-chat-tool-pre">${escapeHtml(String(summary).slice(0, 2000))}</pre>`;
  host.appendChild(card);
  card.scrollIntoView({ block: "end" });
}

function chatSendFrame(frame) {
  if (!chatSocket || chatSocket.readyState !== 1) return false;
  chatSocket.send(JSON.stringify(frame));
  return true;
}

async function fetchChatWebchatToken() {
  const body = await apiPost("/api/v1/chat/token", {});
  chatWebchatToken = body.token;
  return body;
}

function connectChatConsole() {
  disconnectChatConsole();
  setChatStatus("connecting", "connecting…");
  fetchChatWebchatToken()
    .then((body) => {
      const hint = document.querySelector("#chat-session-id");
      if (hint) {
        hint.textContent = body.session_id_hint ? `Session ${body.session_id_hint.slice(0, 8)}…` : "";
      }
      const proto = location.protocol === "https:" ? "wss" : "ws";
      chatSocket = new WebSocket(`${proto}://${location.host}/ws/webchat`);
      chatSocket.addEventListener("open", () => {
        chatSendFrame({ type: "auth", token: body.token });
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (tz) chatSendFrame({ type: "client_meta", timezone: tz });
      });
      chatSocket.addEventListener("close", () => {
        setChatStatus("error", "disconnected");
        finishChatStreamingBubble();
      });
      chatSocket.addEventListener("error", () => {
        setChatStatus("error", "error");
      });
      chatSocket.addEventListener("message", (ev) => {
        let frame;
        try {
          frame = JSON.parse(ev.data);
        } catch (_err) {
          return;
        }
        if (!frame || typeof frame !== "object") return;
        switch (frame.type) {
          case "ready":
            chatSessionId = frame.session_id;
            setChatStatus("connected", "connected");
            if (hint) hint.textContent = chatSessionId ? `Session ${chatSessionId.slice(0, 8)}…` : "";
            break;
          case "message":
            finishChatStreamingBubble();
            appendChatBubble(frame.text || "", "assistant");
            break;
          case "chunk":
            ensureChatStreamingBubble().textContent += frame.text || "";
            break;
          case "tool_call":
          case "tool_result":
            appendChatToolCard(frame);
            break;
          case "cancelled":
            finishChatStreamingBubble();
            appendChatBubble(frame.ok ? "Turn stopped." : "Nothing to stop.", "assistant");
            break;
          case "error":
            finishChatStreamingBubble();
            appendChatBubble(`error: ${frame.code || ""} ${frame.message || ""}`.trim(), "error");
            break;
          default:
            break;
        }
      });
    })
    .catch((err) => {
      setChatStatus("error", err.message || "token failed");
    });
}

async function renderChat() {
  return `
    <p class="muted">Talk to sevn as the dashboard owner via <code>/ws/webchat</code>. Token is server-minted — no client-controlled identity.</p>
    <div class="mission-chat-toolbar">
      <span id="chat-status" class="badge badge-muted">disconnected</span>
      <span id="chat-session-id" class="muted"></span>
      <button type="button" class="btn btn-sm btn-ghost" id="chat-reconnect-btn">Reconnect</button>
      <button type="button" class="btn btn-sm btn-ghost" id="chat-fork-btn">New session</button>
      <button type="button" class="btn btn-sm btn-muted" id="chat-stop-btn">Stop</button>
    </div>
    <div id="chat-tool-cards" class="mission-chat-tool-cards"></div>
    <div id="chat-log" class="chat mission-chat-log" aria-live="polite"></div>
    <form id="chat-composer" class="mission-chat-composer">
      <label class="field mission-chat-input-wrap">
        <span class="label">Message</span>
        <textarea id="chat-input" class="input" rows="3" placeholder="Message sevn…"></textarea>
      </label>
      <button type="submit" class="btn">Send</button>
    </form>
  `;
}

function bindChatHandlers() {
  chatToolCardsHost = document.querySelector("#chat-tool-cards");
  connectChatConsole();
  document.querySelector("#chat-composer")?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const input = document.querySelector("#chat-input");
    const value = (input?.value || "").trim();
    if (!value || !chatSessionId) return;
    if (chatSendFrame({ type: "message", text: value, session_id: chatSessionId })) {
      appendChatBubble(value, "user");
      if (input) input.value = "";
    }
  });
  document.querySelector("#chat-stop-btn")?.addEventListener("click", () => {
    if (!chatSessionId) return;
    chatSendFrame({ type: "cancel", session_id: chatSessionId });
  });
  document.querySelector("#chat-reconnect-btn")?.addEventListener("click", () => {
    connectChatConsole();
  });
  document.querySelector("#chat-fork-btn")?.addEventListener("click", async () => {
    try {
      const body = await apiPost("/api/v1/chat/fork", {});
      chatSessionId = body.session_id;
      const hint = document.querySelector("#chat-session-id");
      if (hint) hint.textContent = `Session ${chatSessionId.slice(0, 8)}…`;
      const log = document.querySelector("#chat-log");
      if (log) log.innerHTML = "";
      finishChatStreamingBubble();
      appendChatBubble("Started a new session.", "assistant");
      connectChatConsole();
    } catch (err) {
      alert(err.message);
    }
  });
}

async function renderCanvas() {
  const panel = await apiGet("/api/v1/dashboard/canvas");
  if (!panel.configured) {
    return `<p class="muted">OpenUI is not configured on this gateway.</p>`;
  }
  if (panel.empty || !panel.iframe_src) {
    return `
      <p class="muted">No live OpenUI canvas yet. Ask the agent to render a layout with <code>openui_render</code> or the bundled <code>canvas</code> skill.</p>
      <p class="muted">When a render exists, this tab embeds <code>GET /openui/&lt;token&gt;</code> in a sandboxed iframe (no scripts).</p>
    `;
  }
  const title = panel.title || "OpenUI canvas";
  const src = escapeHtml(panel.iframe_src);
  const safeOrigin = escapeHtml(panel.safe_origin || "");
  return `
    <p class="muted">Sandboxed OpenUI surface · channel <strong>${escapeHtml(panel.channel || "—")}</strong> · record <code>${escapeHtml(panel.record_id || "")}</code></p>
    <div class="mission-canvas-frame">
      <iframe
        class="mission-canvas-iframe"
        title="${escapeHtml(title)}"
        src="${src}"
        sandbox="allow-forms allow-same-origin"
        referrerpolicy="no-referrer"
        data-safe-origin="${safeOrigin}"
      ></iframe>
    </div>
  `;
}

async function renderSessions() {
  const page = await apiGet("/api/v1/sessions?limit=50");
  const rows = (page.items || []).map((s) => ({
    ...s,
    updated: s.updated_at || "",
    link: `<a href="/mission/sessions/${encodeURIComponent(s.session_id)}/api-calls">API calls</a>`,
  }));
  return `
    <p class="muted">Session delete is disabled in Mission Control to preserve self-improve evidence.</p>
    ${tableFromRows(rows, [
      { key: "session_id", label: "Session" },
      { key: "channel", label: "Channel" },
      { key: "user_id", label: "User" },
      { key: "active_runs", label: "Active runs" },
      { key: "updated", label: "Updated" },
      { key: "link", label: "Detail" },
    ])}
  `;
}

async function renderSessionApiCalls(sessionId) {
  const page = await apiGet(`/api/v1/sessions/${encodeURIComponent(sessionId)}/api-calls?limit=100`);
  const rows = (page.items || []).map((row) => ({
    ts_start_ns: row.ts_start_ns,
    span_id: row.span_id,
    tier: row.tier,
    model_id: row.attrs?.["model.id"] || row.attrs?.model_id || "",
    regime: row.attrs?.regime || "",
    tokens_in: row.attrs?.["cost.tokens_in"] ?? "",
    tokens_out: row.attrs?.["cost.tokens_out"] ?? "",
  }));
  return `
    <p><a href="/mission/sessions">← Sessions</a></p>
    <h3>Session ${sessionId} API calls</h3>
    ${tableFromRows(rows, [
      { key: "ts_start_ns", label: "ts (ns)" },
      { key: "tier", label: "Tier" },
      { key: "model_id", label: "Model" },
      { key: "regime", label: "Regime" },
      { key: "tokens_in", label: "In" },
      { key: "tokens_out", label: "Out" },
    ])}
  `;
}

const traceFilters = {
  kind: "",
  status: "",
  tsFrom: "",
  tsTo: "",
  budgetRegime: "",
  modelId: "",
  tier: "",
  jobId: "",
};

function readTraceFiltersFromUrl() {
  const params = new URLSearchParams(location.search);
  traceFilters.jobId = String(params.get("job_id") || "").trim();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderTraceTimelineRows(items) {
  if (!items.length) {
    return "<p class=\"muted\">No spans match the current filters.</p>";
  }
  const minTs = Math.min(...items.map((row) => Number(row.ts_start_ns)));
  const maxTs = Math.max(
    ...items.map((row) => Number(row.ts_end_ns || row.ts_start_ns)),
  );
  const span = Math.max(maxTs - minTs, 1);
  const rows = items
    .map((row) => {
      const start = Number(row.ts_start_ns);
      const end = Number(row.ts_end_ns || start);
      const left = ((start - minTs) / span) * 100;
      const width = Math.max(((end - start) / span) * 100, 1.5);
      const statusClass = row.status === "error" ? "trace-bar--error" : "trace-bar--ok";
      return `
        <button type="button" class="trace-row" data-span-id="${escapeHtml(row.span_id)}">
          <div class="trace-row__meta">
            <span class="trace-row__kind">${escapeHtml(row.kind)}</span>
            <span class="trace-row__status">${escapeHtml(row.status)}</span>
            <span class="trace-row__session muted">${escapeHtml(row.session_id)}</span>
          </div>
          <div class="trace-row__track" aria-hidden="true">
            <span class="trace-bar ${statusClass}" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%"></span>
          </div>
          <div class="trace-row__ts muted">${escapeHtml(row.ts_start_ns)}</div>
        </button>
      `;
    })
    .join("");
  return `<div class="trace-timeline">${rows}</div>`;
}

function renderTraceTreeNode(node, depth = 0) {
  const pad = depth * 16;
  const children = (node.children || [])
    .map((child) => renderTraceTreeNode(child, depth + 1))
    .join("");
  return `
    <div class="trace-tree-node" style="padding-left:${pad}px">
      <div class="trace-tree-node__label">
        <button type="button" class="trace-tree-select" data-span-id="${escapeHtml(node.span_id)}">
          ${escapeHtml(node.kind)} · ${escapeHtml(node.status)}
        </button>
      </div>
      ${children}
    </div>
  `;
}

function renderTraceDetailPanel(detail) {
  if (!detail) {
    return "<p class=\"muted\">Select a span to inspect attrs and child tree.</p>";
  }
  const span = detail.span || detail;
  const turnId = String(span.turn_id || "").trim();
  const sessionId = String(span.session_id || "").trim();
  const canReplay = Boolean(turnId && sessionId);
  const replayBtn = canReplay
    ? `<button type="button" class="btn" id="trace-replay-turn" data-session-id="${escapeHtml(sessionId)}" data-turn-id="${escapeHtml(turnId)}">Re-run this turn</button>`
    : "<p class=\"muted\">Replay requires a session and turn id on the span.</p>";
  return `
    <h3>Span ${escapeHtml(span.span_id)}</h3>
    <p class="muted">${escapeHtml(span.kind)} · ${escapeHtml(span.status)} · session ${escapeHtml(sessionId)} · turn ${escapeHtml(turnId || "—")}</p>
    <p>${replayBtn}</p>
    <p id="trace-replay-status" class="muted" hidden></p>
    <h4>Span tree</h4>
    <div class="trace-tree">${renderTraceTreeNode(span)}</div>
    <h4>Attributes</h4>
    <pre class="trace-attrs">${escapeHtml(JSON.stringify(span.attrs || {}, null, 2))}</pre>
  `;
}

async function loadTraceDetail(spanId) {
  const panel = document.querySelector("#trace-detail");
  if (!panel) return;
  panel.innerHTML = "<p class=\"muted\">Loading span…</p>";
  try {
    const detail = await apiGet(`/api/v1/traces/${encodeURIComponent(spanId)}`);
    panel.innerHTML = renderTraceDetailPanel(detail);
    bindTraceDetailHandlers(panel);
  } catch (err) {
    panel.innerHTML = `<p class="error">Failed to load span: ${escapeHtml(err.message)}</p>`;
  }
}

function bindTraceDetailHandlers(root) {
  root.querySelectorAll("[data-span-id]").forEach((el) => {
    el.addEventListener("click", () => {
      const spanId = el.getAttribute("data-span-id");
      if (spanId) loadTraceDetail(spanId);
    });
  });
  const replayBtn = root.querySelector("#trace-replay-turn");
  replayBtn?.addEventListener("click", async () => {
    const sessionId = replayBtn.getAttribute("data-session-id");
    const turnId = replayBtn.getAttribute("data-turn-id");
    const statusEl = root.querySelector("#trace-replay-status");
    if (!sessionId || !turnId) return;
    if (!window.confirm(`Re-run turn ${turnId} for session ${sessionId}?`)) return;
    if (statusEl) {
      statusEl.hidden = false;
      statusEl.textContent = "Queueing replay…";
      statusEl.className = "muted";
    }
    try {
      const resp = await apiPost(
        `/api/v1/sessions/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}/replay`,
        { confirmed: true },
      );
      if (statusEl) {
        statusEl.textContent = `Replay queued (${resp.replay_job_id || "ok"}).`;
        statusEl.className = "muted";
      }
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = `Replay failed: ${err.message}`;
        statusEl.className = "error";
      }
    }
  });
}

function bindTraceTabHandlers() {
  const form = document.querySelector("#trace-filters");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    traceFilters.kind = String(data.get("kind") || "").trim();
    traceFilters.status = String(data.get("status") || "").trim();
    traceFilters.tsFrom = String(data.get("ts_from") || "").trim();
    traceFilters.tsTo = String(data.get("ts_to") || "").trim();
    traceFilters.budgetRegime = String(data.get("budget_regime") || "").trim();
    traceFilters.modelId = String(data.get("model_id") || "").trim();
    traceFilters.tier = String(data.get("tier") || "").trim();
    renderContent();
  });
  document.querySelectorAll(".trace-row[data-span-id]").forEach((el) => {
    el.addEventListener("click", () => {
      const spanId = el.getAttribute("data-span-id");
      if (spanId) loadTraceDetail(spanId);
    });
  });
}

async function renderTraces() {
  readTraceFiltersFromUrl();
  const params = new URLSearchParams({ limit: "50" });
  if (traceFilters.kind) params.set("kind", traceFilters.kind);
  if (traceFilters.status) params.set("status", traceFilters.status);
  if (traceFilters.tsFrom) params.set("ts_from", traceFilters.tsFrom);
  if (traceFilters.tsTo) params.set("ts_to", traceFilters.tsTo);
  if (traceFilters.budgetRegime) params.set("budget_regime", traceFilters.budgetRegime);
  if (traceFilters.modelId) params.set("model_id", traceFilters.modelId);
  if (traceFilters.tier) params.set("tier", traceFilters.tier);
  if (traceFilters.jobId) params.set("job_id", traceFilters.jobId);
  const page = await apiGet(`/api/v1/traces?${params.toString()}`);
  const items = page.items || [];
  const regimeOptions = ["", "SUBSCRIPTION", "PER_TOKEN", "FREE_LOCAL"]
    .map(
      (value) =>
        `<option value="${escapeHtml(value)}"${traceFilters.budgetRegime === value ? " selected" : ""}>${value || "Any regime"}</option>`,
    )
    .join("");
  const tierOptions = ["", "A", "B", "C", "D"]
    .map(
      (value) =>
        `<option value="${escapeHtml(value)}"${traceFilters.tier === value ? " selected" : ""}>${value || "Any tier"}</option>`,
    )
    .join("");
  return `
    ${traceFilters.jobId ? `<p class="muted">Filtered by improve job <code>${escapeHtml(traceFilters.jobId)}</code> · <a href="/mission/traces">Clear</a></p>` : ""}
    <form id="trace-filters" class="trace-filters">
      <label>Kind <input name="kind" value="${escapeHtml(traceFilters.kind)}" placeholder="b_turn"></label>
      <label>Status <input name="status" value="${escapeHtml(traceFilters.status)}" placeholder="ok"></label>
      <label>Regime <select name="budget_regime">${regimeOptions}</select></label>
      <label>Model <input name="model_id" value="${escapeHtml(traceFilters.modelId)}" placeholder="anthropic/claude-sonnet-4-6"></label>
      <label>Tier <select name="tier">${tierOptions}</select></label>
      <label>From (ns) <input name="ts_from" value="${escapeHtml(traceFilters.tsFrom)}"></label>
      <label>To (ns) <input name="ts_to" value="${escapeHtml(traceFilters.tsTo)}"></label>
      <button type="submit" class="btn">Apply filters</button>
    </form>
    <h3>Timeline</h3>
    ${renderTraceTimelineRows(items)}
    <h3>Span detail</h3>
    <div id="trace-detail"><p class="muted">Select a span to inspect attrs and child tree.</p></div>
  `;
}

async function renderBudget() {
  const budget = await apiGet("/api/v1/budget/summary");
  const regimes = budget.by_regime || [];
  const totalCalls = regimes.reduce((sum, row) => sum + Number(row.call_count || 0), 0);
  const totalTokensIn = regimes.reduce((sum, row) => sum + Number(row.tokens_in || 0), 0);
  const totalTokensOut = regimes.reduce((sum, row) => sum + Number(row.tokens_out || 0), 0);
  const projections = budget.projections || {};
  const burn = projections.burn_rate || {};
  const projected = projections.projected || {};
  const alerts = budget.alerts || [];
  const alertHtml = alerts.length
    ? `<div class="mission-alert-banner">${alerts
        .map(
          (a) =>
            `<p class="error"><strong>${escapeHtml(a.severity || "warning")}</strong>: ${escapeHtml(a.message || "")}</p>`,
        )
        .join("")}</div>`
    : totalCalls === 0
      ? `<p class="muted empty-state">No provider calls in the recent trace window — projections appear after LLM usage is traced.</p>`
      : "";
  return `
    ${alertHtml}
    <p class="muted">Provider calls (recent trace window): ${totalCalls} · tokens in ${totalTokensIn} · out ${totalTokensOut}</p>
    <h3>Burn rate &amp; projections</h3>
    ${
      projections.burn_rate
        ? `<div class="mission-overview-grid">
      ${overviewStatCard("Calls / day", burn.calls_per_day ?? 0)}
      ${overviewStatCard("Tokens in / day", burn.tokens_in_per_day ?? 0)}
      ${overviewStatCard("Projected monthly calls", projected.monthly_calls ?? 0)}
      ${overviewStatCard("Projected monthly tokens in", projected.monthly_tokens_in ?? 0)}
    </div>`
        : `<p class="muted empty-state">Insufficient provider-call history for burn-rate projection.</p>`
    }
    <h3>Hourly rollups</h3>
    ${
      (budget.hourly_rollups || []).length
        ? tableFromRows(budget.hourly_rollups || [], [
            { key: "hour_bucket_ns", label: "Hour (ns)" },
            { key: "kind", label: "Kind" },
            { key: "event_count", label: "Events" },
            { key: "error_count", label: "Errors" },
          ])
        : `<p class="muted empty-state">No hourly rollups yet — trace maintenance fills <code>trace_rollups_hourly</code>.</p>`
    }
    <h3>By regime</h3>
    ${
      regimes.length
        ? tableFromRows(regimes, [
            { key: "regime", label: "Regime" },
            { key: "call_count", label: "Calls" },
            { key: "tokens_in", label: "Tokens in" },
            { key: "tokens_out", label: "Tokens out" },
          ])
        : `<p class="muted empty-state">No provider-call regimes recorded yet.</p>`
    }
    <h3>Subscription windows</h3>
    ${
      (budget.subscription_windows || []).length
        ? tableFromRows(budget.subscription_windows || [], [
            { key: "model_id", label: "Model" },
            { key: "window_remaining", label: "Remaining" },
            { key: "subscription_window_id", label: "Window id" },
          ])
        : `<p class="muted empty-state">No subscription-window telemetry in traces.</p>`
    }
  `;
}

function formatAuditTs(ns) {
  if (!ns) return "—";
  try {
    return new Date(Number(ns) / 1_000_000).toLocaleString();
  } catch (_err) {
    return String(ns);
  }
}

function renderSimpleBarChart(rows, labelKey, valueKey, maxBars = 12) {
  const slice = rows.slice(0, maxBars);
  if (!slice.length) {
    return `<p class="muted empty-state">No data for this window.</p>`;
  }
  const maxVal = Math.max(...slice.map((r) => Number(r[valueKey] || 0)), 1);
  return `<div class="mission-bar-chart">${slice
    .map((row) => {
      const val = Number(row[valueKey] || 0);
      const pct = Math.round((val / maxVal) * 100);
      const label = row[labelKey] ?? "—";
      return `<div class="mission-bar-row"><span class="mission-bar-label">${escapeHtml(String(label))}</span><div class="mission-bar-track"><div class="mission-bar-fill" style="width:${pct}%"></div></div><span class="mission-bar-value">${val}</span></div>`;
    })
    .join("")}</div>`;
}

async function renderAuditAnalytics() {
  const [timeline, tools, volume, approvals] = await Promise.all([
    apiGet("/api/v1/audit/timeline?limit=50"),
    apiGet("/api/v1/analytics/tool-frequency?days=30"),
    apiGet("/api/v1/analytics/daily-volume?days=30"),
    apiGet("/api/v1/analytics/approvals?limit=20"),
  ]);
  const auditRows = (timeline.items || []).map((row) => ({
    ts: formatAuditTs(row.ts_start_ns),
    kind: row.kind,
    session: row.session_id,
    status: row.status,
    summary: row.attrs?.name || row.attrs?.path || row.attrs?.tool_name || "",
  }));
  const approvalRows = (approvals.items || []).map((row) => ({
    ts: formatAuditTs(row.ts_start_ns),
    kind: row.kind,
    tool: row.attrs?.tool_name || "",
    status: row.status,
  }));
  return `
    <p class="muted">Read-only audit trail and aggregates from <code>traces.db</code> — tool calls, mission ops, and approvals.</p>
    <h3>Audit timeline</h3>
    ${
      auditRows.length
        ? tableFromRows(auditRows, [
            { key: "ts", label: "Time" },
            { key: "kind", label: "Kind" },
            { key: "session", label: "Session" },
            { key: "status", label: "Status" },
            { key: "summary", label: "Summary" },
          ])
        : `<p class="muted empty-state">No audit events yet — tool calls and mission actions appear here as they are traced.</p>`
    }
    <h3>Tool frequency (30d)</h3>
    ${renderSimpleBarChart(tools.tools || [], "name", "count")}
    <h3>Daily volume (30d)</h3>
    ${renderSimpleBarChart(
      (volume.days || []).map((d) => ({
        day: formatAuditTs(d.day_start_ns),
        event_count: d.event_count,
      })),
      "day",
      "event_count",
    )}
    <h3>Approval timeline</h3>
    ${
      approvalRows.length
        ? tableFromRows(approvalRows, [
            { key: "ts", label: "Time" },
            { key: "kind", label: "Kind" },
            { key: "tool", label: "Tool" },
            { key: "status", label: "Status" },
          ])
        : `<p class="muted empty-state">No approval audit rows yet — live tier-B approvals appear in Tools &amp; Permissions and in this timeline after decisions.</p>`
    }
  `;
}

function providerReauthCell(row) {
  if (row.ok) return "";
  const id = String(row.id || "");
  if (id === "openai") {
    return `<button type="button" class="btn btn-sm btn-secondary provider-oauth-reauth-btn" data-provider-id="openai">Sign in / Re-auth</button>`;
  }
  return `<span class="muted">sevn providers oauth login --provider ${escapeHtml(id)}</span>`;
}

async function renderProviders() {
  const health = await apiGet("/api/v1/providers/health");
  const providers = health.providers || [];
  const degraded = providers.filter((row) => !row.ok).length;
  const rows = providers.map((row) => ({
    id: row.id,
    ok: row.ok ? "ok" : "degraded",
    severity: row.severity,
    detail: row.detail,
    reauth: providerReauthCell(row),
  }));
  return `
    <p class="muted">Generated ${health.generated_at_ns ?? "n/a"} · ${degraded} degraded of ${providers.length}</p>
    ${tableFromRows(rows, [
      { key: "id", label: "Provider" },
      { key: "ok", label: "Status" },
      { key: "severity", label: "Severity" },
      { key: "detail", label: "Detail" },
      { key: "reauth", label: "Re-auth" },
    ])}
  `;
}

function bindProvidersHandlers() {
  content.querySelectorAll(".provider-oauth-reauth-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const providerId = btn.getAttribute("data-provider-id");
      if (!providerId) return;
      try {
        const body = await apiPost(`/api/v1/providers/${encodeURIComponent(providerId)}/oauth/reauth`);
        if (body.authorize_url) {
          window.open(body.authorize_url, "_blank", "noopener,noreferrer");
        }
        const hint = body.cli_hint || `sevn providers oauth login --provider ${providerId}`;
        alert(
          body.authorize_url
            ? `Browser opened for ChatGPT sign-in. If it did not open, run:\n${hint}`
            : `Run on the gateway host:\n${hint}`,
        );
        await renderContent();
      } catch (err) {
        alert(err.message);
      }
    });
  });
}

async function renderChannels() {
  const status = await apiGet("/api/v1/channels/status");
  const config = await apiGet("/api/v1/channels/config");
  const tg = config.channels?.telegram || {};
  const wc = config.channels?.webchat || {};
  const rows = (status.channels || []).map((row) => ({
    name: row.name,
    enabled: row.enabled ? "yes" : "no",
    connected: row.connected ? "yes" : "no",
    connection_state: row.connection_state,
    session_count: row.session_count,
    messages: row.messages,
    errors: row.errors,
    last_error: row.last_error || "",
  }));
  return `
    <p class="muted">Runtime health from gateway mission state · session counts from <code>sevn.db</code>. Secret rotation lives under Ops → Secrets.</p>
    ${tableFromRows(rows, [
      { key: "name", label: "Channel" },
      { key: "enabled", label: "Enabled" },
      { key: "connected", label: "Connected" },
      { key: "connection_state", label: "State" },
      { key: "session_count", label: "Sessions" },
      { key: "messages", label: "Messages" },
      { key: "errors", label: "Errors" },
      { key: "last_error", label: "Last error" },
    ])}
    <h3>Channel settings</h3>
    <p class="muted">Writes <code>channels.*</code> in <code>sevn.json</code>. Gateway restart may be required.</p>
    <form id="channels-config-form" class="form-grid">
      <label class="checkbox-row">
        <input type="checkbox" data-channels-path="telegram.enabled" ${tg.enabled ? "checked" : ""} />
        <span>telegram.enabled</span>
      </label>
      <label class="checkbox-row">
        <input type="checkbox" data-channels-path="webchat.enabled" ${wc.enabled ? "checked" : ""} />
        <span>webchat.enabled</span>
      </label>
      <label class="checkbox-row">
        <input type="checkbox" data-channels-path="webchat.public" ${wc.public ? "checked" : ""} />
        <span>webchat.public</span>
      </label>
      <button type="submit" class="btn">Save channel settings</button>
    </form>
  `;
}

async function renderSubagents() {
  const data = await apiGet("/api/v1/mission/subagents");
  const counts = data.counts || {};
  const limits = data.limits || {};
  const l1 = counts.level1_total ?? 0;
  const l2 = counts.level2_total ?? 0;
  const chips = `
    <div class="subagents-count-chips mission-overview-badges">
      <span class="badge badge-info">L1 running: ${l1}</span>
      <span class="badge badge-info">L2 running: ${l2}</span>
    </div>`;
  const runningRows = (data.running || []).map((row) => ({
    id: row.id,
    level: row.level,
    role: row.role,
    specialist: row.specialist || "",
    task: row.task_summary || "",
    status: row.status,
    age_s: row.age_s,
    actions: `<button type="button" class="btn btn-sm btn-secondary subagent-kill-btn" data-subagent-id="${escapeHtml(row.id)}">Kill</button>`,
  }));
  const recentRows = (data.recent || []).map((row) => ({
    id: row.id,
    level: row.level,
    role: row.role,
    specialist: row.specialist || "",
    task: row.task_summary || "",
    status: row.status,
  }));
  const limitsByRole = limits.by_role || {};
  const roleRows = Object.entries(limitsByRole).map(([role, caps]) => ({
    role,
    max_level1: caps.max_level1,
    max_level2: caps.max_level2,
  }));
  return `
    <p class="muted">Live registry + mission telemetry · kill routes through the gateway supervisor (owner-only).</p>
    ${chips}
    <h3>Running</h3>
    <div id="subagents-running-table">
      ${tableFromRows(runningRows, [
        { key: "id", label: "ID" },
        { key: "level", label: "Level" },
        { key: "role", label: "Role" },
        { key: "specialist", label: "Specialist" },
        { key: "task", label: "Task" },
        { key: "status", label: "Status" },
        { key: "age_s", label: "Age (s)" },
        { key: "actions", label: "Actions" },
      ])}
    </div>
    <div class="form-actions">
      <button type="button" class="btn btn-secondary subagent-kill-all-btn" data-role="">Kill all L1</button>
      <button type="button" class="btn btn-secondary subagent-kill-all-btn" data-role="tier_b">Kill all tier B</button>
    </div>
    <h3>Recent history</h3>
    <div id="subagents-recent-table">
      ${tableFromRows(recentRows, [
        { key: "id", label: "ID" },
        { key: "level", label: "Level" },
        { key: "role", label: "Role" },
        { key: "specialist", label: "Specialist" },
        { key: "task", label: "Task" },
        { key: "status", label: "Status" },
      ])}
    </div>
    <h3>Limits (read-only)</h3>
    <div id="subagents-limits-panel" class="ops-panel">
      <p class="muted">Edit limits in <a href="/mission/config">Ops → Config</a> under <code>subagents.*</code>.</p>
      <p>enabled: <strong>${limits.enabled ? "yes" : "no"}</strong> · defaults L1/L2: <strong>${limits.max_level1_default}/${limits.max_level2_default}</strong> · override: <strong>${limits.max_override ?? "—"}</strong></p>
      ${tableFromRows(roleRows, [
        { key: "role", label: "Role" },
        { key: "max_level1", label: "Max L1" },
        { key: "max_level2", label: "Max L2" },
      ])}
    </div>
  `;
}

function bindSubagentsHandlers() {
  document.querySelectorAll(".subagent-kill-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.subagentId;
      if (!id) return;
      try {
        await apiPost(`/api/v1/mission/subagents/${encodeURIComponent(id)}/kill`, {});
        await renderContent();
      } catch (err) {
        alert(`Kill failed: ${err.message}`);
      }
    });
  });
  document.querySelectorAll(".subagent-kill-all-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const role = btn.dataset.role || "";
      const url = role
        ? `/api/v1/mission/subagents/kill_all?role=${encodeURIComponent(role)}`
        : "/api/v1/mission/subagents/kill_all";
      try {
        await apiPost(url, {});
        await renderContent();
      } catch (err) {
        alert(`Kill all failed: ${err.message}`);
      }
    });
  });
}

async function renderCron() {
  const data = await apiGet("/api/v1/cron/jobs");
  const rows = (data.jobs || []).map((job) => ({
    job_id: job.job_id,
    enabled: job.enabled ? "yes" : "no",
    cron_expr: job.cron_expr,
    timezone: job.timezone,
    next_fire_at_ns: job.next_fire_at_ns,
    last_status: job.last_status || "",
    actions: `
      <button type="button" class="btn btn-sm cron-run-btn" data-job-id="${escapeHtml(job.job_id)}">Run now</button>
      <button type="button" class="btn btn-sm btn-secondary cron-toggle-btn" data-job-id="${escapeHtml(job.job_id)}" data-enabled="${job.enabled ? "0" : "1"}">${job.enabled ? "Pause" : "Resume"}</button>
      <button type="button" class="btn btn-sm btn-secondary cron-delete-btn" data-job-id="${escapeHtml(job.job_id)}">Delete</button>`,
  }));
  return `
    <p class="muted">Scheduler ${data.triggers_paused ? "paused" : "active"} · ${data.count ?? 0} job(s)</p>
    ${tableFromRows(rows, [
      { key: "job_id", label: "Job" },
      { key: "enabled", label: "Enabled" },
      { key: "cron_expr", label: "Cron" },
      { key: "timezone", label: "TZ" },
      { key: "next_fire_at_ns", label: "Next fire (ns)" },
      { key: "last_status", label: "Last status" },
      { key: "actions", label: "Actions" },
    ])}
    <h3>Scheduler</h3>
    <p class="muted">Writes <code>triggers.paused</code> in <code>sevn.json</code>.</p>
    <form id="cron-config-form" class="form-grid">
      <label class="checkbox-row">
        <input type="checkbox" id="cron-paused-input" ${data.triggers_paused ? "checked" : ""} />
        <span>Pause all scheduled triggers</span>
      </label>
      <button type="submit" class="btn">Save scheduler state</button>
    </form>
    <h3>Add cron job</h3>
    <form id="cron-create-form" class="form-grid ops-panel">
      <label>Job id <input type="text" id="cron-new-id" class="field-input" placeholder="my_job" required /></label>
      <label>Cron expr <input type="text" id="cron-new-expr" class="field-input" placeholder="0 9 * * *" required /></label>
      <label>Timezone <input type="text" id="cron-new-tz" class="field-input" value="UTC" /></label>
      <label>Payload <input type="text" id="cron-new-payload" class="field-input" placeholder="optional prompt" /></label>
      <button type="submit" class="btn btn-primary">Create job</button>
    </form>
  `;
}

async function renderSecurity() {
  const data = await apiGet("/api/v1/security");
  const sec = data.security || {};
  const scanner = sec.scanner || {};
  const toggles = [
    ["heuristic_only", scanner.heuristic_only],
    ["bypass_owner", scanner.bypass_owner],
    ["image_ocr", scanner.image_ocr],
    ["scan_voice", scanner.scan_voice],
  ];
  const rows = toggles.map(([key, val]) => ({
    key,
    value: val === undefined ? "default" : val ? "on" : "off",
  }));
  return `
    <p class="muted">Toggle scanner flags below; writes <code>security.*</code> in <code>sevn.json</code>.</p>
    ${tableFromRows(rows, [
      { key: "key", label: "Scanner flag" },
      { key: "value", label: "Value" },
    ])}
    <form id="security-toggles-form" class="form-grid">
      ${toggles
        .map(
          ([key]) => `
        <label class="checkbox-row">
          <input type="checkbox" name="${escapeHtml(key)}" data-security-key="${escapeHtml(key)}" ${scanner[key] ? "checked" : ""} />
          <span>${escapeHtml(key)}</span>
        </label>`,
        )
        .join("")}
      <button type="submit" class="btn">Save security toggles</button>
    </form>
    <pre class="trace-attrs">${escapeHtml(JSON.stringify(sec, null, 2))}</pre>
  `;
}

async function renderSecrets() {
  const [aliases, store, entries] = await Promise.all([
    apiGet("/api/v1/secrets/aliases"),
    apiGet("/api/v1/secrets/store"),
    apiGet("/api/v1/secrets/store/entries"),
  ]);
  const aliasRows = (aliases.aliases || []).map((row) => ({
    logical_key: row.logical_key,
    source: row.source,
  }));
  const storeRows = (entries.entries || []).map((row) => ({
    alias: row.alias,
    fingerprint: row.fingerprint_sha256_hex,
  }));
  return `
    <div id="secrets-exposed-banner" class="secrets-exposed-banner" hidden role="alert">
      Secret values are visible — audited.
    </div>
    <div class="form-actions secrets-toggle-row">
      <label class="checkbox-row">
        <input type="checkbox" id="secrets-show-values" />
        <span>Show values</span>
      </label>
    </div>
    <p class="muted">Store: <code>${escapeHtml(store.store_path || "")}</code> · healthy=${store.healthy ? "yes" : "no"} · ${store.entry_count ?? 0} entr(y/ies)</p>
    <h3>Config aliases (\${SECRET:…})</h3>
    ${secretsAliasesTable(aliasRows)}
    <h3>Encrypted store entries</h3>
    ${secretsStoreTable(storeRows)}
    <div class="form-grid">
      <label>Alias <input type="text" id="secrets-alias" class="field-input" placeholder="logical.key" /></label>
      <label>Value <input type="password" id="secrets-value" class="field-input" autocomplete="off" /></label>
      <label>Fingerprint confirm <input type="text" id="secrets-fingerprint" class="field-input" placeholder="overwrite only" /></label>
      <div class="form-actions">
        <button type="button" class="btn" id="secrets-reveal-btn">Reveal</button>
        <button type="button" class="btn btn-primary" id="secrets-save-btn">Save</button>
        <button type="button" class="btn btn-secondary" id="secrets-delete-btn">Delete</button>
      </div>
    </div>
    <pre id="secrets-output" class="trace-attrs"></pre>
  `;
}

async function renderEgressProxy() {
  const [status, logs] = await Promise.all([
    apiGet("/api/v1/proxy/status"),
    apiGet("/api/v1/proxy/logs"),
  ]);
  const logLines = (logs.lines || []).map((line) => escapeHtml(line)).join("\n");
  return `
    <p>Configured: <strong>${status.configured ? "yes" : "no"}</strong> ·
      Health: <strong>${status.ok ? "up" : "down"}</strong>
      ${status.origin ? ` · <code>${escapeHtml(status.origin)}</code>` : ""}</p>
    <button type="button" class="btn" id="proxy-restart-btn">Restart proxy</button>
    <button type="button" class="btn btn-secondary" id="proxy-refresh-logs-btn">Refresh logs</button>
    <h3>Proxy log tail</h3>
    <pre class="trace-attrs log-tail" id="proxy-log-tail">${logLines || "(no proxy log lines yet)"}</pre>
    <p class="muted">Log path: <code>${escapeHtml(logs.path || "")}</code></p>
  `;
}

async function renderTunnelsInfra() {
  const [data, daemons] = await Promise.all([
    apiGet("/api/v1/tunnels/status"),
    apiGet("/api/v1/ops/daemons"),
  ]);
  const probes = (data.probes || []).map((row) => ({
    check_id: row.check_id,
    ok: row.ok ? "ok" : "fail",
    severity: row.severity,
    detail: row.detail,
  }));
  const gw = daemons.gateway || {};
  const px = daemons.proxy || {};
  const proc = data.process || {};
  const isCloudflare = (data.tunnel_mode || "none") === "cloudflare";
  const procHealthLabel = proc.healthy
    ? `<span style="color:var(--color-ok,green)">running (pid ${proc.pid})</span>`
    : `<span style="color:var(--color-error,red)">${escapeHtml(proc.error || "stopped")}</span>`;
  const publicUrlHtml = proc.public_url
    ? `<a href="${escapeHtml(proc.public_url)}" target="_blank" rel="noopener">${escapeHtml(proc.public_url)}</a>`
    : "—";
  return `
    <div class="ops-panel form-actions">
      <button type="button" class="btn btn-primary" id="ops-reload-config-btn">Reload sevn.json</button>
      <button type="button" class="btn" id="ops-dreaming-run-btn">Run dreaming cycle</button>
    </div>
    <h3>Daemons</h3>
    <p>Gateway listen: <strong>${escapeHtml(gw.listen_state || "?")}</strong> · unit installed: <strong>${gw.unit_installed ? "yes" : "no"}</strong> · active: <strong>${gw.unit_active ? "yes" : "no"}</strong></p>
    <p>Proxy listen: <strong>${escapeHtml(px.listen_state || "?")}</strong> · unit installed: <strong>${px.unit_installed ? "yes" : "no"}</strong> · active: <strong>${px.unit_active ? "yes" : "no"}</strong></p>
    <div class="form-actions">
      <button type="button" class="btn btn-sm daemon-action-btn" data-service="gateway" data-action="install">Install gateway unit</button>
      <button type="button" class="btn btn-sm daemon-action-btn" data-service="gateway" data-action="enable">Start gateway</button>
      <button type="button" class="btn btn-sm btn-secondary daemon-action-btn" data-service="gateway" data-action="disable">Stop gateway</button>
      <button type="button" class="btn btn-sm daemon-action-btn" data-service="proxy" data-action="enable">Start proxy</button>
      <button type="button" class="btn btn-sm btn-secondary daemon-action-btn" data-service="proxy" data-action="disable">Stop proxy</button>
    </div>
    <h3>Tunnel</h3>
    <p>Mode: <strong>${escapeHtml(data.tunnel_mode || "none")}</strong> ·
      config active: <strong>${data.tunnel_active ? "yes" : "no"}</strong></p>
    <p>Process health: ${procHealthLabel}</p>
    <p>Public URL: ${publicUrlHtml}</p>
    ${isCloudflare ? `
    <div class="form-actions" id="tunnel-control-actions">
      <button type="button" class="btn btn-sm${proc.healthy ? " btn-secondary" : " btn-primary"}" id="tunnel-start-btn"${proc.healthy ? " disabled" : ""}>Start cloudflared</button>
      <button type="button" class="btn btn-sm btn-secondary" id="tunnel-stop-btn"${proc.healthy ? "" : " disabled"}>Stop cloudflared</button>
    </div>` : ""}
    <p>Gateway: <code>${escapeHtml(data.gateway_host || "")}:${escapeHtml(String(data.gateway_port ?? ""))}</code></p>
    <h3>Doctor probes</h3>
    ${tableFromRows(probes, [
      { key: "check_id", label: "Probe" },
      { key: "ok", label: "Status" },
      { key: "severity", label: "Severity" },
      { key: "detail", label: "Detail" },
    ])}
    <pre class="trace-attrs">${escapeHtml(JSON.stringify({ infrastructure: data.infrastructure, tunnel: data.tunnel }, null, 2))}</pre>
  `;
}

async function renderBackupSnapshots() {
  const data = await apiGet("/api/v1/backup/manifest");
  const backups = data.config_backups || [];
  const tarballs = data.snapshot_tarballs || [];
  const tarballRows = tarballs.map((row) => ({
    ...row,
    restore: `<button type="button" class="btn btn-sm snapshot-restore-btn" data-snapshot-id="${escapeHtml(row.name)}">Restore</button>`,
  }));
  return `
    <div class="ops-panel form-actions">
      <button type="button" class="btn" id="backup-export-btn">Export config backup</button>
      <button type="button" class="btn btn-primary" id="snapshot-create-btn">Create snapshot</button>
      <label class="btn btn-secondary">
        Import backup
        <input type="file" id="backup-import-input" accept=".tar.gz,.tgz,application/gzip" hidden />
      </label>
    </div>
    <p class="muted">${escapeHtml(data.restore_hint || "")}</p>
    <h3>Config backups (sevn.json.v*)</h3>
    ${tableFromRows(backups, [
      { key: "name", label: "File" },
      { key: "size_bytes", label: "Bytes" },
      { key: "modified_unix_s", label: "Modified (unix)" },
    ])}
    <h3>Sandbox snapshots</h3>
    <p class="muted">Dir: <code>${escapeHtml(data.snapshots_dir || "")}</code></p>
    ${tableFromRows(tarballRows, [
      { key: "name", label: "Archive" },
      { key: "size_bytes", label: "Bytes" },
      { key: "modified_unix_s", label: "Modified (unix)" },
      { key: "restore", label: "Restore" },
    ])}
    <p class="muted">Destructive restore requires confirm. Reload config after import via Tunnels &amp; Infra.</p>
  `;
}

async function renderConfig() {
  const data = await apiGet("/api/v1/config/full");
  configDraft = structuredClone(data.config || {});
  configMeta = data;
  configEditorMode = "tree";
  const treeHtml = renderConfigTreeMarkup(configDraft);
  const text = JSON.stringify(configDraft, null, 2);
  return `
    <p class="muted">Path: <code>${escapeHtml(data.sevn_json_path || data.sevn_json || "")}</code> · schema v${escapeHtml(String(data.schema_version ?? "?"))}</p>
    <div class="config-full-toolbar">
      <div class="config-mode-toggle" role="tablist" aria-label="Config editor mode">
        <button type="button" class="btn btn-sm btn-primary" id="config-mode-tree" data-mode="tree">Tree</button>
        <button type="button" class="btn btn-sm btn-secondary" id="config-mode-text" data-mode="text">Text</button>
      </div>
      <div class="form-actions">
        <button type="button" class="btn" id="config-validate-btn">Validate</button>
        <button type="button" class="btn btn-primary" id="config-save-btn">Save sevn.json</button>
      </div>
    </div>
    <div id="config-tree-panel" class="config-tree-panel">${treeHtml}</div>
    <textarea id="config-editor" class="config-editor mission-editor file-editor" rows="24" spellcheck="false" hidden>${escapeHtml(text)}</textarea>
    <pre id="config-error-panel" class="config-error-panel muted" hidden></pre>
    <p id="config-editor-status" class="muted"></p>
  `;
}

async function renderMemory() {
  const data = await apiGet("/api/v1/knowledge/memory?limit=50");
  const rows = (data.sqlite_rows || []).map((row) => ({
    key: row.key,
    session_id: row.session_id,
    created_at: row.created_at,
    content_preview: row.content_preview,
  }));
  const md = data.memory_md || {};
  const um = data.user_model || {};
  const cfg = data.config || {};
  return `
    <p class="muted">Short-term rows from <code>sevn.db</code> · long-term <code>MEMORY.md</code> · inferred profile in <code>.sevn/user_model.json</code>.</p>
    <p><strong>Config:</strong> memory section ${cfg.section_present ? "present" : "absent"}
      ${cfg.dreaming_enabled != null ? ` · dreaming ${cfg.dreaming_enabled ? "on" : "off"}` : ""}
      ${cfg.user_model_enabled != null ? ` · user model ${cfg.user_model_enabled ? "on" : "off"}` : ""}
      ${cfg.lcm_enabled != null ? ` · LCM ${cfg.lcm_enabled ? "on" : "off"}` : ""}</p>
    <h3>SQLite memory (${data.sqlite_count ?? 0})</h3>
    ${tableFromRows(rows, [
      { key: "key", label: "Key" },
      { key: "session_id", label: "Session" },
      { key: "created_at", label: "Created" },
      { key: "content_preview", label: "Preview" },
    ])}
    <h3>MEMORY.md</h3>
    ${
      md.present
        ? `<p class="muted">${escapeHtml(md.path)} · ${md.size_bytes} bytes · ${md.line_count} lines</p><pre class="trace-attrs">${escapeHtml(md.preview || "")}</pre>`
        : `<p class="muted">No MEMORY.md in workspace root.</p>`
    }
    <h3>User model</h3>
    <p class="muted">${um.fact_count ?? 0} active fact(s)${um.topics?.length ? ` · topics: ${escapeHtml(um.topics.join(", "))}` : ""}</p>
    <h3>Edit MEMORY.md</h3>
    ${fileEditorShell("MEMORY.md", md.preview || "", md.present ? "Preview loaded — save writes full file." : "No MEMORY.md yet — save creates it.")}
  `;
}

async function renderSecondBrain() {
  const data = await apiGet("/api/v1/knowledge/second-brain");
  const pages = (data.wiki_pages || []).map((p) => ({
    path: p.path,
    size_bytes: p.size_bytes,
    modified_unix_s: p.modified_unix_s,
  }));
  const scopes = (data.scopes || []).join(", ") || "—";
  return `
    <p class="muted">Vault at <code>${escapeHtml(data.vault_path || "")}</code> · scope <code>${escapeHtml(data.scope || "owner")}</code>
      · ${data.enabled ? "enabled" : "disabled"} · ingest via <code>POST ${escapeHtml(data.gateway_fetch || "/api/second_brain/fetch")}</code></p>
    <p><strong>Scopes:</strong> ${escapeHtml(scopes)}</p>
    <h3>Wiki pages (${data.wiki_page_count ?? 0})</h3>
    ${tableFromRows(pages, [
      { key: "path", label: "Page" },
      { key: "size_bytes", label: "Bytes" },
      { key: "modified_unix_s", label: "Modified (unix)" },
    ])}
    ${
      data.index_excerpt
        ? `<h3>index.md excerpt</h3><pre class="trace-attrs">${escapeHtml(data.index_excerpt)}</pre>`
        : ""
    }
    <h3>Wiki editor</h3>
    ${fileEditorShell("", "", "Open a wiki page path under second_brain/… or pick from the list above.")}
  `;
}

async function renderWorkspaceFiles() {
  const path = new URLSearchParams(window.location.search).get("path") || ".";
  const [listData, treeData] = await Promise.all([
    apiGet(`/api/v1/knowledge/workspace-files?path=${encodeURIComponent(path)}&limit=200`),
    apiGet(`/api/v1/files/tree?root=workspace&path=${encodeURIComponent(path)}`),
  ]);
  const openPath = new URLSearchParams(window.location.search).get("file") || "";
  let editorHtml = fileEditorShell(openPath, "", openPath ? "Loading…" : "Pick a file or use Identity shortcuts.");
  if (openPath) {
    try {
      const fileData = await apiGet(`/api/v1/files/content?path=${encodeURIComponent(openPath)}`);
      editorHtml = fileEditorShell(fileData.path, fileData.content, `Loaded ${fileData.size ?? 0} bytes`);
    } catch (_err) {
      editorHtml = fileEditorShell(openPath, "", "Could not load file.");
    }
  }
  const rows = (listData.entries || []).map((e) => ({
    name: e.redacted ? "<redacted>" : e.name,
    type: e.type,
    size: e.redacted ? "—" : e.size,
    path: e.path,
    mtime: e.mtime || "",
  }));
  const parent =
    path !== "." && path.includes("/")
      ? path.replace(/\/[^/]+$/, "") || "."
      : path === "."
        ? null
        : ".";
  const nav =
    parent != null
      ? `<p><a href="/mission/workspace-files?path=${encodeURIComponent(parent)}">↑ ${escapeHtml(parent)}</a></p>`
      : "";
  const fileLinks = (treeData.entries || [])
    .filter((e) => e.kind === "file")
    .slice(0, 40)
    .map(
      (e) =>
        `<a href="/mission/workspace-files?path=${encodeURIComponent(path)}&file=${encodeURIComponent(e.name === e.path ? e.name : `${path === "." ? "" : path + "/"}${e.name}`.replace(/^\.\//, ""))}">${escapeHtml(e.name)}</a>`,
    )
    .join(" · ");
  return `
    <p class="muted">Listing <code>${escapeHtml(listData.path || path)}</code> (${listData.count ?? 0} entries). Use the editor below — saves via <code>PUT /api/v1/files/content</code>.</p>
    ${nav}
    ${fileLinks ? `<p class="muted">${fileLinks}</p>` : ""}
    ${tableFromRows(rows, [
      { key: "name", label: "Name" },
      { key: "type", label: "Type" },
      { key: "size", label: "Size" },
      { key: "path", label: "Path" },
      { key: "mtime", label: "Modified" },
    ])}
    <h3>Editor</h3>
    ${editorHtml}
  `;
}

async function renderCodeUnderstanding() {
  const [data, graph] = await Promise.all([
    apiGet("/api/v1/knowledge/code-understanding"),
    apiGet("/api/v1/knowledge/graph"),
  ]);
  const warnings = (data.warnings || []).map((w) => `<li>${escapeHtml(w)}</li>`).join("");
  const profiles = (data.graphify?.profiles || []).map((p) => ({
    id: p.id,
    graph_report: p.graph_report_present ? "yes" : "no",
    graph_json: p.graph_json_present ? "yes" : "no",
    output_dir: p.output_dir,
  }));
  const mycode = data.mycode || {};
  const nodeRows = (graph.nodes || []).slice(0, 50).map((n) => ({
    id: n.id || n.name || JSON.stringify(n).slice(0, 40),
    label: n.label || n.title || n.id || "—",
  }));
  const graphSection = graph.present
    ? `<p class="muted">${graph.node_count ?? 0} nodes · ${graph.edge_count ?? 0} edges · <code>${escapeHtml(graph.path || "")}</code></p>
       ${tableFromRows(nodeRows, [
         { key: "label", label: "Node" },
         { key: "id", label: "Id" },
       ])}
       <p class="muted">Click a node id to open its file in Workspace Files when mapped to a path.</p>`
    : `<p class="muted">${escapeHtml(graph.hint || "graphify-out/graph.json not found.")}</p>`;
  return `
    <p class="muted">Checkout: <code>${escapeHtml(data.checkout || "not resolved")}</code></p>
    ${warnings ? `<ul class="muted">${warnings}</ul>` : "<p class=\"muted\">No doctor warnings.</p>"}
    <h3>Knowledge graph</h3>
    ${graphSection}
    <h3>MYCODE</h3>
    <p>enabled=${mycode.enabled ?? "—"} · present=${mycode.present ? "yes" : "no"} · needs_refresh=${mycode.needs_refresh ?? "—"}</p>
    <p class="muted">${escapeHtml(mycode.path || "")}</p>
    <h3>Graphify</h3>
    <p>enabled=${data.graphify?.enabled ?? false}</p>
    ${tableFromRows(profiles, [
      { key: "id", label: "Profile" },
      { key: "graph_report", label: "GRAPH_REPORT" },
      { key: "graph_json", label: "graph.json" },
      { key: "output_dir", label: "Output" },
    ])}
    <p class="muted">CGR ${data.code_graph_rag?.enabled ?? "—"} · roam ${data.roam_code?.enabled ?? "—"} · code-review-graph ${data.code_review_graph?.enabled ?? "—"}</p>
  `;
}

async function renderSevnCli() {
  const shortcuts = await apiGet("/api/v1/cli/shortcuts");
  const buttons = (shortcuts.shortcuts || [])
    .map(
      (s) =>
        `<button type="button" class="btn btn-secondary cli-shortcut-btn" data-cli-argv="${escapeHtml(JSON.stringify(s.argv || []))}">${escapeHtml(s.label || "Run")}</button>`,
    )
    .join(" ");
  return `
    <p class="muted">Runs <code>uv run sevn …</code> in the workspace content root. Destructive subcommands require confirm.</p>
    <div class="form-grid">
      <label>Args (space-separated) <input type="text" id="cli-args" class="field-input" placeholder="doctor --json" /></label>
      <label class="checkbox-row"><input type="checkbox" id="cli-confirm" /> Confirm destructive command</label>
      <button type="button" class="btn btn-primary" id="cli-run-btn">Run</button>
    </div>
    <p class="muted">Shortcuts: ${buttons || "—"}</p>
    <pre id="cli-output" class="trace-attrs log-tail">(no output yet)</pre>
  `;
}

async function renderTerminal() {
  return `
    <p class="muted">Sandbox-confined interactive shell at workspace <code>content_root</code>. Owner JWT + CSRF upgrade via <code>POST /api/v1/terminal/session</code>; PTY over <code>/ws/dashboard/terminal</code>.</p>
    <div class="terminal-toolbar">
      <span id="terminal-status" class="badge badge-muted">idle</span>
      <button type="button" class="btn btn-primary btn-sm" id="terminal-connect-btn">Connect</button>
      <button type="button" class="btn btn-secondary btn-sm" id="terminal-disconnect-btn">Disconnect</button>
    </div>
    <div id="terminal-mount" class="terminal-mount card" aria-label="Web terminal"></div>
    <pre id="terminal-fallback" class="terminal-fallback trace-attrs log-tail" hidden>(xterm.js required)</pre>
  `;
}

async function renderTelegramMenu() {
  const data = await apiGet("/api/v1/surfaces/telegram-menu");
  const sectionRows = (data.sections || []).map((s) => ({
    section_id: s.section_id,
    tile_label: s.tile_label,
    actions: (s.buttons || []).length,
  }));
  const docsLink = data.docs_url
    ? `<p><a href="${escapeHtml(data.docs_url)}" target="_blank" rel="noopener">Open telegram-menu catalog (about-sevn.bot)</a></p>`
    : "";
  const edit = data.editable || {};
  const qa = edit.quick_actions || {};
  const qaChecks = Object.entries(qa)
    .map(
      ([key, val]) => `
      <label class="checkbox-row">
        <input type="checkbox" data-telegram-qa="${escapeHtml(key)}" ${val ? "checked" : ""} />
        <span>quick_actions.${escapeHtml(key)}</span>
      </label>`,
    )
    .join("");
  return `
    ${docsLink}
    <p class="muted">Live snapshot of <code>/config</code> section keyboards (${data.section_count ?? 0} sections).</p>
    ${tableFromRows(sectionRows, [
      { key: "tile_label", label: "Section" },
      { key: "section_id", label: "Id" },
      { key: "actions", label: "Actions" },
    ])}
    <details>
      <summary>Section detail</summary>
      <pre class="muted">${escapeHtml(JSON.stringify(data.sections || [], null, 2))}</pre>
    </details>
    <h3>Menu display toggles</h3>
    <p class="muted">Writes <code>channels.telegram</code> in <code>sevn.json</code>.</p>
    <form id="telegram-menu-form" class="form-grid">
      <label class="checkbox-row">
        <input type="checkbox" data-telegram-key="reply_keyboard_enabled" ${edit.reply_keyboard_enabled ? "checked" : ""} />
        <span>Persistent reply keyboard</span>
      </label>
      <label class="checkbox-row">
        <input type="checkbox" data-telegram-key="show_routing" ${edit.show_routing ? "checked" : ""} />
        <span>Show routing badges</span>
      </label>
      ${qaChecks}
      <button type="submit" class="btn">Save menu toggles</button>
    </form>
  `;
}

async function renderWebApps() {
  const data = await apiGet("/api/v1/surfaces/web-apps");
  const rows = (data.routes || []).map((r) => ({
    method: r.method,
    path: r.path,
    status: r.status,
    description: r.description,
  }));
  const edit = data.editable || {};
  const origins = Array.isArray(edit.allowed_origins) ? edit.allowed_origins.join(", ") : "";
  return `
    <p>Public base: <code>${escapeHtml(data.public_base || "—")}</code></p>
    <p>Inline Share/Feedback buttons: <strong>${data.inline_buttons_allowed ? "allowed (HTTPS)" : "blocked (need HTTPS origin)"}</strong></p>
    ${tableFromRows(rows, [
      { key: "method", label: "Method" },
      { key: "path", label: "Path" },
      { key: "status", label: "Status" },
      { key: "description", label: "Description" },
    ])}
    <h3>Webchat settings</h3>
    <p class="muted">Gates the Web App surface · writes <code>channels.webchat</code> in <code>sevn.json</code>.</p>
    <form id="web-apps-form" class="form-grid">
      <label class="checkbox-row">
        <input type="checkbox" data-webchat-key="public" ${edit.public ? "checked" : ""} />
        <span>webchat.public</span>
      </label>
      <label class="checkbox-row">
        <input type="checkbox" data-webchat-key="tts_inline" ${edit.tts_inline ? "checked" : ""} />
        <span>webchat.tts_inline</span>
      </label>
      <label>allowed_origins (comma-separated)
        <input type="text" id="web-apps-origins" value="${escapeHtml(origins)}" />
      </label>
      <button type="submit" class="btn">Save webchat settings</button>
    </form>
  `;
}

async function renderOnboarding() {
  const data = await apiGet("/api/v1/surfaces/onboarding");
  const log = data.last_log;
  const logLine = log
    ? `<p>Last log: <code>${escapeHtml(log.filename)}</code> (${log.size_bytes} bytes, ${escapeHtml(log.modified_at)})</p>`
    : "<p class=\"muted\">No onboard-*.log in workspace logs yet.</p>";
  const wizard = data.gateway_wizard_url
    ? `<p><a href="${escapeHtml(data.gateway_wizard_url)}" target="_blank" rel="noopener">Open gateway onboarding wizard</a></p>`
    : "<p class=\"muted\">Gateway wizard token not available on this process — use CLI below.</p>";
  return `
    <p>CLI: <code>${escapeHtml(data.cli_command || "sevn onboard --web")}</code></p>
    ${wizard}
    <p>Applied profile: <strong>${escapeHtml(data.applied_profile || "—")}</strong></p>
    <p>Draft present: <strong>${data.draft_present ? "yes" : "no"}</strong>${data.draft_top_level_keys?.length ? ` · keys: ${escapeHtml(data.draft_top_level_keys.join(", "))}` : ""}</p>
    ${logLine}
  `;
}

async function renderUsersRbac() {
  const data = await apiGet("/api/v1/surfaces/users-rbac");
  const caps = (data.capabilities || []).map((c) => `<li>${escapeHtml(c)}</li>`).join("");
  const notV1 = (data.not_in_v1 || []).map((c) => `<li>${escapeHtml(c)}</li>`).join("");
  return `
    <p><strong>v1 model:</strong> ${escapeHtml(data.model || "owner_only_v1")}</p>
    <p>Local-open effective: <strong>${data.local_open_effective ? "yes" : "no"}</strong> · tunnel: <code>${escapeHtml(data.tunnel_mode || "none")}</code></p>
    <p>Remote auth required: <strong>${data.auth_required_remote ? "yes" : "no"}</strong></p>
    <h3>What v1 provides</h3>
    <ul>${caps}</ul>
    <h3>Not in v1</h3>
    <ul class="muted">${notV1}</ul>
    <p class="muted">See ${(data.spec_refs || []).map((r) => `<code>${escapeHtml(r)}</code>`).join(" · ")}</p>
  `;
}

async function refreshPendingToolApprovals() {
  try {
    const page = await apiGet("/api/v1/agent/approvals/pending");
    pendingToolApprovals = Array.isArray(page.items) ? page.items : [];
  } catch (_err) {
    pendingToolApprovals = [];
  }
  updateApprovalPendingBadge();
}

function updateApprovalPendingBadge() {
  if (!approvalPendingBadge) return;
  const count = pendingToolApprovals.length;
  if (count <= 0) {
    approvalPendingBadge.hidden = true;
    approvalPendingBadge.textContent = "Approvals 0";
    approvalPendingBadge.className = "badge badge-muted";
    return;
  }
  approvalPendingBadge.hidden = false;
  approvalPendingBadge.textContent = `Approvals ${count}`;
  approvalPendingBadge.className = "badge badge-warning";
}

function renderToolApprovalCards() {
  if (!pendingToolApprovals.length) {
    return `<section class="ops-panel"><h3>Live tool approvals</h3><p class="muted empty-state">No pending tool executions — dangerous tools pause here when a turn needs operator approval.</p></section>`;
  }
  const cards = pendingToolApprovals
    .map(
      (row) => `
    <article class="card approval-card" data-decision-id="${escapeHtml(row.decision_id || "")}">
      <h4><code>${escapeHtml(row.tool_name || "?")}</code></h4>
      <p class="muted">Session <code>${escapeHtml(row.session_id || "—")}</code> · turn <code>${escapeHtml(row.turn_id || "—")}</code></p>
      <pre class="mission-editor approval-args">${escapeHtml(row.args_summary || "{}")}</pre>
      <div class="approval-actions">
        <button type="button" class="btn btn-sm btn-primary tool-approval-btn" data-verdict="once" data-decision-id="${escapeHtml(row.decision_id || "")}">Once</button>
        <button type="button" class="btn btn-sm btn-secondary tool-approval-btn" data-verdict="session" data-decision-id="${escapeHtml(row.decision_id || "")}">This session</button>
        <button type="button" class="btn btn-sm btn-secondary tool-approval-btn" data-verdict="always" data-decision-id="${escapeHtml(row.decision_id || "")}">Always</button>
        <button type="button" class="btn btn-sm btn-ghost tool-approval-btn" data-verdict="deny" data-decision-id="${escapeHtml(row.decision_id || "")}">Deny</button>
      </div>
    </article>`,
    )
    .join("");
  return `<section class="ops-panel"><h3>Live tool approvals</h3><p class="muted">${pendingToolApprovals.length} pending — approve dangerous tool calls blocked by tier-B <code>requires_human</code>.</p>${cards}</section>`;
}

async function submitToolApproval(decisionId, verdict) {
  await apiPost(`/api/v1/agent/approvals/${encodeURIComponent(decisionId)}`, { verdict });
  pendingToolApprovals = pendingToolApprovals.filter((row) => row.decision_id !== decisionId);
  updateApprovalPendingBadge();
}

async function renderToolsPermissions() {
  await refreshPendingToolApprovals();
  const data = await apiGet("/api/v1/agent/tools-health");
  const perms = await apiGet("/api/v1/agent/permissions");
  const rows = (data.rows || []).map((row) => ({
    health_row_id: row.health_row_id,
    layer: row.layer,
    name: row.name,
    failure_count: row.failure_count,
    window_days: row.window_days,
    last_failure_at: row.last_failure_at || "—",
    chronic: row.chronic ? "yes" : "no",
    rewrite_candidate: row.rewrite_candidate ? "yes" : "no",
  }));
  const toolNote = data.tools_table_wired
    ? ""
    : "<p class=\"muted\">Tool-layer chronic rows ship when the tools health table is wired.</p>";
  return `
    ${renderToolApprovalCards()}
    <p class="muted">Shared <code>ToolSkillHealthService</code> — same data as Telegram Tools &amp; Skills → Health.</p>
    ${toolNote}
    ${tableFromRows(rows, [
      { key: "layer", label: "Layer" },
      { key: "name", label: "Name" },
      { key: "failure_count", label: "Failures" },
      { key: "window_days", label: "Window (d)" },
      { key: "last_failure_at", label: "Last failure" },
      { key: "chronic", label: "Chronic" },
      { key: "rewrite_candidate", label: "Rewrite?" },
    ])}
    <p class="muted">${data.count ?? 0} row(s) · threshold ≥ ${data.threshold ?? 3} in ${data.window_days ?? 14} d</p>
    <h3>Permissions &amp; tools config</h3>
    <p class="muted">Edits <code>permissions</code> and <code>tools</code> in <code>sevn.json</code> (JSON objects).</p>
    <form id="permissions-form" class="form-grid">
      <label>permissions
        <textarea id="permissions-editor" class="config-editor" rows="8">${escapeHtml(JSON.stringify(perms.permissions || {}, null, 2))}</textarea>
      </label>
      <label>tools
        <textarea id="tools-editor" class="config-editor" rows="6">${escapeHtml(JSON.stringify(perms.tools || {}, null, 2))}</textarea>
      </label>
      <div><button type="submit" class="btn">Save permissions &amp; tools</button></div>
      <p id="permissions-status" class="muted"></p>
    </form>
  `;
}

async function renderSkills() {
  const [data, bundled] = await Promise.all([
    apiGet("/api/v1/agent/skills"),
    apiGet("/api/v1/agent/skills/bundled"),
  ]);
  const rows = (data.skills || []).map((row) => ({
    id: row.id,
    provenance: row.provenance,
    quarantine: row.quarantine ? "yes" : "no",
    version: row.version,
    actions: `
      ${row.can_promote ? `<button type="button" class="btn btn-sm skill-promote-btn" data-skill="${escapeHtml(row.id)}">Graduate</button>` : ""}
      ${row.provenance === "user" ? `<button type="button" class="btn btn-sm btn-secondary skill-toggle-btn" data-skill="${escapeHtml(row.id)}" data-enabled="${row.quarantine ? "1" : "0"}">${row.quarantine ? "Enable" : "Disable"}</button>` : ""}
      ${row.provenance === "user" ? `<button type="button" class="btn btn-sm btn-secondary skill-uninstall-btn" data-skill="${escapeHtml(row.id)}">Uninstall</button>` : ""}`,
  }));
  const bundledOptions = (bundled.skills || [])
    .map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
    .join("");
  return `
    <p class="muted">Registry v<code>${escapeHtml(data.registry_version || "?")}</code> · install bundled skills under <code>skills/user/</code> only.</p>
    <form id="skill-install-form" class="form-grid ops-panel">
      <label>Bundled skill
        <select id="skill-install-select" class="field-input">${bundledOptions}</select>
      </label>
      <button type="submit" class="btn btn-primary">Install to skills/user/</button>
    </form>
    ${tableFromRows(rows, [
      { key: "id", label: "Skill" },
      { key: "provenance", label: "Provenance" },
      { key: "quarantine", label: "Quarantine" },
      { key: "version", label: "Version" },
      { key: "actions", label: "Actions" },
    ])}
    <p class="muted">${data.count ?? 0} skill(s)</p>
  `;
}

function bindSkillsHandlers() {
  document.querySelector("#skill-install-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = document.querySelector("#skill-install-select")?.value;
    if (!name || !window.confirm(`Install bundled skill ${name} to skills/user/?`)) return;
    try {
      await apiPost("/api/v1/agent/skills/install", { skill_name: name, ...opsConfirmBody() });
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
  content.querySelectorAll(".skill-promote-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.getAttribute("data-skill");
      if (!name) return;
      if (!confirm(`Promote generated skill "${name}" to user/?`)) return;
      try {
        await apiPost(`/api/v1/agent/skills/${encodeURIComponent(name)}/promote`, {});
        await renderContent();
      } catch (err) {
        alert(err.message);
      }
    });
  });
  content.querySelectorAll(".skill-uninstall-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.getAttribute("data-skill");
      if (!name || !window.confirm(`Uninstall user skill ${name}?`)) return;
      try {
        await fetch(`/api/v1/agent/skills/${encodeURIComponent(name)}`, {
          method: "DELETE",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken(),
          },
          body: JSON.stringify(opsConfirmBody()),
        }).then(async (resp) => {
          if (!resp.ok) {
            const data = await resp.json();
            throw new Error(data?.error?.message || resp.statusText);
          }
        });
        await renderContent();
      } catch (err) {
        alert(err.message);
      }
    });
  });
  content.querySelectorAll(".skill-toggle-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.getAttribute("data-skill");
      const enabled = btn.getAttribute("data-enabled") === "1";
      if (!name) return;
      try {
        await apiPost(`/api/v1/agent/skills/${encodeURIComponent(name)}/toggle`, {
          enabled,
          ...opsConfirmBody(),
        });
        await renderContent();
      } catch (err) {
        alert(err.message);
      }
    });
  });
}

async function renderMcpServers() {
  const data = await apiGet("/api/v1/agent/mcp-servers");
  const rows = (data.servers || []).map((row) => ({
    server_id: row.server_id,
    command: row.command,
    args: (row.args || []).join(" "),
    workspace_enabled: row.workspace_enabled ? "yes" : "no",
    synthetic: row.synthetic ? "yes" : "no",
  }));
  const serverChecks = (data.servers || [])
    .map(
      (row) => `
      <label class="checkbox-row">
        <input type="checkbox" data-mcp-server="${escapeHtml(row.server_id)}" ${row.workspace_enabled ? "checked" : ""} />
        <span><code>${escapeHtml(row.server_id)}</code>${row.synthetic ? " <em class=\"muted\">(synthetic)</em>" : ""}</span>
      </label>`,
    )
    .join("");
  return `
    <p class="muted">Effective MCP stdio descriptor registry (operator <code>mcp_servers</code> + synthetic gateways).</p>
    <p>Workspace <code>mcp_enabled</code>: <code>${escapeHtml(JSON.stringify(data.mcp_enabled || []))}</code></p>
    ${tableFromRows(rows, [
      { key: "server_id", label: "Server" },
      { key: "command", label: "Command" },
      { key: "args", label: "Args" },
      { key: "workspace_enabled", label: "Enabled" },
      { key: "synthetic", label: "Synthetic" },
    ])}
    <p class="muted">${data.count ?? 0} server(s)</p>
    <h3>Enablement</h3>
    <p class="muted">Toggle which servers are in workspace <code>mcp_enabled</code> (writes <code>sevn.json</code>).</p>
    <form id="mcp-servers-form" class="form-grid">
      ${serverChecks || "<p class=\"muted\">No MCP servers discovered.</p>"}
      <button type="submit" class="btn">Save enabled servers</button>
    </form>
  `;
}

async function renderCodingAgents() {
  const data = await apiGet("/api/v1/coding-agents");
  const agents = data.agents || [];
  const cards = agents
    .map((agent, index) => {
      const bindings = (agent.bindings || [])
        .map((b) => {
          const topics =
            b.topic_ids == null ? "whole chat" : (b.topic_ids || []).join(", ");
          return `${escapeHtml(b.chat_id)} · ${escapeHtml(String(topics))}`;
        })
        .join("<br/>");
      const executorField =
        agent.type === "alrca"
          ? `<label>Executor
        <select class="field-input coding-agent-executor" data-index="${index}">
          ${["claude_code", "cursor", "codex"]
            .map(
              (ex) =>
                `<option value="${ex}" ${agent.executor === ex ? "selected" : ""}>${ex}</option>`,
            )
            .join("")}
        </select>
      </label>`
          : `<p class="muted">LAP bridge · base URL <code>${escapeHtml(agent.base_url || "(unset)")}</code></p>`;
      return `
      <article class="card coding-agent-card" data-index="${index}">
        <h3><code>${escapeHtml(agent.id)}</code> · ${escapeHtml(agent.type)}</h3>
        <label class="checkbox-row">
          <input type="checkbox" class="coding-agent-enabled" data-index="${index}" ${agent.enabled ? "checked" : ""} />
          <span>Enabled</span>
        </label>
        ${executorField}
        <label>Bindings (chat_id · topics)
          <textarea class="field-input coding-agent-bindings" data-index="${index}" rows="3" placeholder="-1001234567890:42,77">${escapeHtml(
            (agent.bindings || [])
              .map((b) => {
                const topics =
                  b.topic_ids == null ? "*" : (b.topic_ids || []).join(",");
                return `${b.chat_id}:${topics}`;
              })
              .join("\n"),
          )}</textarea>
        </label>
        <p class="muted">${bindings || "No Telegram bindings yet."}</p>
        <p class="muted">Last run: <code>${escapeHtml((agent.last_run && agent.last_run.state) || "idle")}</code></p>
      </article>`;
    })
    .join("");
  return `
    <div id="coding-agents-panel">
      <p class="muted">Hub master toggle: <strong>${data.enabled ? "enabled" : "disabled"}</strong> · ${data.count ?? 0} agent(s)</p>
      <div id="coding-agents-list">${cards || "<p class=\"muted\">No coding agents configured in sevn.json yet.</p>"}</div>
      <form id="coding-agents-form" class="form-grid ops-panel">
        <label class="checkbox-row">
          <input type="checkbox" id="coding-agents-enabled" ${data.enabled ? "checked" : ""} />
          <span>Enable Coding Agents hub</span>
        </label>
        <button type="submit" id="coding-agents-save" class="btn btn-primary">Save coding agents</button>
      </form>
      <p class="muted">Bound Telegram topics bypass Triager and talk directly to the matched agent.</p>
    </div>
  `;
}

function bindCodingAgentsHandlers() {
  document.querySelector("#coding-agents-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const cards = [...document.querySelectorAll(".coding-agent-card")];
    const agents = {};
    cards.forEach((card) => {
      const index = card.getAttribute("data-index");
      const idEl = card.querySelector("h3 code");
      const agentId = idEl ? idEl.textContent : `agent-${index}`;
      const enabled = card.querySelector(".coding-agent-enabled")?.checked ?? false;
      const executor = card.querySelector(".coding-agent-executor")?.value || "cursor";
      const bindingsRaw = card.querySelector(".coding-agent-bindings")?.value || "";
      const typeLabel = card.querySelector("h3")?.textContent || "";
      const type = typeLabel.includes("litellm_lap") ? "litellm_lap" : "alrca";
      const telegram_bindings = bindingsRaw
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const [chatPart, topicPart] = line.split(":");
          const chat_id = (chatPart || "").trim();
          const topicRaw = (topicPart || "*").trim();
          if (topicRaw === "*" || !topicRaw) {
            return { chat_id, topic_ids: null };
          }
          return {
            chat_id,
            topic_ids: topicRaw
              .split(",")
              .map((t) => parseInt(t.trim(), 10))
              .filter((n) => Number.isFinite(n)),
          };
        });
      agents[agentId] =
        type === "litellm_lap"
          ? { type, enabled, telegram_bindings }
          : { type: "alrca", enabled, executor, telegram_bindings };
    });
    const payload = {
      coding_agents: {
        enabled: document.querySelector("#coding-agents-enabled")?.checked ?? true,
        agents,
      },
    };
    try {
      await apiPut("/api/v1/coding-agents", payload);
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
}

async function renderAgentConfig() {
  const data = await apiGet("/api/v1/agent/config");
  const unified = Boolean(data.use_main_model_for_all);
  const slotRows = (data.slots || []).map((row) => ({
    slot: row.slot,
    resolved: row.resolved,
    editable: row.editable ? "yes" : "no",
  }));
  const warnRows = (data.warnings || []).map((w) => ({
    code: w.code,
    message: w.message,
  }));
  return `
    <p>Main model: <strong><code>${escapeHtml(data.main_model || "")}</code></strong></p>
    <label class="checkbox-row">
      <input type="checkbox" id="agent-unified-model" ${unified ? "checked" : ""} />
      <span><code>providers.use_main_model_for_all</code> — one model for all slots</span>
    </label>
    <div id="agent-slot-editor" class="form-grid" ${unified ? "hidden" : ""}>
      <p class="muted">Per-slot overrides (saved to <code>sevn.json</code>).</p>
      ${(data.slots || [])
        .filter((row) => row.slot !== "triager")
        .map(
          (row) => `
        <label>${escapeHtml(row.slot)}
          <input type="text" class="input agent-slot-input" data-slot="${escapeHtml(row.slot)}" value="${escapeHtml(row.resolved || "")}" />
        </label>`,
        )
        .join("")}
    </div>
    <div class="form-actions">
      <button type="button" class="btn" id="agent-reset-suggestions-btn">Reset all to suggestions</button>
      <button type="button" class="btn btn-primary" id="agent-config-save-btn">Save model config</button>
    </div>
    <h3>Resolved slots</h3>
    ${tableFromRows(slotRows, [
      { key: "slot", label: "Slot" },
      { key: "resolved", label: "Model" },
      { key: "editable", label: "Editable" },
    ])}
    <h3>Warnings</h3>
    ${warnRows.length ? tableFromRows(warnRows, [{ key: "code", label: "Code" }, { key: "message", label: "Message" }]) : "<p class=\"muted\">No live warnings.</p>"}
    <p id="agent-config-status" class="muted"></p>
  `;
}

function bindAgentConfigHandlers() {
  const unifiedEl = document.getElementById("agent-unified-model");
  const slotPanel = document.getElementById("agent-slot-editor");
  unifiedEl?.addEventListener("change", () => {
    if (slotPanel) slotPanel.hidden = unifiedEl.checked;
  });
  document.getElementById("agent-config-save-btn")?.addEventListener("click", async () => {
    const status = document.getElementById("agent-config-status");
    try {
      const body = { use_main_model_for_all: Boolean(unifiedEl?.checked) };
      if (!body.use_main_model_for_all) {
        const tierDefault = {};
        content.querySelectorAll(".agent-slot-input").forEach((input) => {
          const slot = input.getAttribute("data-slot");
          const val = (input.value || "").trim();
          if (!slot || !val) return;
          if (slot === "tier_b") tierDefault.B = val;
          else if (slot === "tier_c") tierDefault.C = val;
          else if (slot === "tier_d") tierDefault.D = val;
          else if (slot === "c_sub_lm") tierDefault["C.sub_lm"] = val;
          else if (slot === "d_sub_lm") tierDefault["D.sub_lm"] = val;
          else if (slot === "c_lambda_leaf") tierDefault["C.lambda_leaf"] = val;
          else if (slot === "d_lambda_leaf") tierDefault["D.lambda_leaf"] = val;
        });
        body.providers = { tier_default: tierDefault };
      }
      await apiPut("/api/v1/agent/config", body);
      if (status) status.textContent = "Saved.";
      await renderContent();
    } catch (err) {
      if (status) status.textContent = err.message;
    }
  });
  document.getElementById("agent-reset-suggestions-btn")?.addEventListener("click", async () => {
    try {
      const data = await apiGet("/api/v1/agent/config");
      const suggestions = data.suggestions || {};
      content.querySelectorAll(".agent-slot-input").forEach((input) => {
        const slot = input.getAttribute("data-slot");
        if (slot && suggestions[slot]) input.value = suggestions[slot];
      });
      if (unifiedEl) unifiedEl.checked = false;
      if (slotPanel) slotPanel.hidden = false;
    } catch (err) {
      alert(err.message);
    }
  });
}

const MODEL_PARAMS_AGENTS = [
  "triager",
  "tier_b",
  "tier_cd",
  "guard",
  "lcm",
  "dreaming",
  "user_model",
];

const MODEL_PARAMS_FIELDS = [
  { key: "temperature", label: "temperature", step: "0.05" },
  { key: "top_p", label: "top_p", step: "0.05" },
  { key: "top_k", label: "top_k", step: "1" },
  { key: "seed", label: "seed", step: "1" },
];

function modelParamsNumber(value) {
  return value == null || value === "" ? "" : escapeHtml(String(value));
}

function modelParamsAgentBlock(agent, block) {
  const b = block || {};
  const ov = (b.model_overrides && b.model_overrides["minimax/*"]) || {};
  const fields = MODEL_PARAMS_FIELDS.map(
    (f) => `
      <label>${escapeHtml(f.key)}
        <input type="number" step="${f.step}" class="input mp-input"
          data-agent="${escapeHtml(agent)}" data-scope="base" data-field="${escapeHtml(f.key)}"
          value="${modelParamsNumber(b[f.key])}" />
      </label>`,
  ).join("");
  const ovFields = MODEL_PARAMS_FIELDS.map(
    (f) => `
      <label>${escapeHtml(f.key)}
        <input type="number" step="${f.step}" class="input mp-input"
          data-agent="${escapeHtml(agent)}" data-scope="minimax" data-field="${escapeHtml(f.key)}"
          value="${modelParamsNumber(ov[f.key])}" />
      </label>`,
  ).join("");
  return `
    <fieldset class="mp-agent" data-agent="${escapeHtml(agent)}">
      <legend><code>${escapeHtml(agent)}</code></legend>
      <div class="form-grid">${fields}</div>
      <p class="muted"><code>minimax/*</code> model override</p>
      <div class="form-grid">${ovFields}</div>
    </fieldset>`;
}

async function renderModelParams() {
  const data = await apiGet("/api/v1/agent/llm-params");
  const doc = data.doc || {};
  const blocks = MODEL_PARAMS_AGENTS.map((agent) => modelParamsAgentBlock(agent, doc[agent])).join("");
  return `
    <p>Per-agent sampling parameters, saved to <code>${escapeHtml(data.path || "LLM_params_config.json")}</code>.</p>
    <p class="muted">Source: <strong>${escapeHtml(data.source || "builtin")}</strong>.
      Blank fields are left unset (built-in default applies). A gateway <strong>restart</strong> is required for changes to take effect.</p>
    <form id="model-params-form">${blocks}</form>
    <div class="form-actions">
      <button type="button" class="btn btn-primary" id="model-params-save-btn">Save model params</button>
    </div>
    <p id="model-params-status" class="muted"></p>
  `;
}

function bindModelParamsHandlers() {
  document.getElementById("model-params-save-btn")?.addEventListener("click", async () => {
    const status = document.getElementById("model-params-status");
    const doc = { schema_version: 1 };
    MODEL_PARAMS_AGENTS.forEach((agent) => {
      doc[agent] = { model_overrides: { "minimax/*": {} } };
    });
    let parseError = "";
    content.querySelectorAll(".mp-input").forEach((input) => {
      const raw = (input.value || "").trim();
      if (raw === "") return;
      const num = Number(raw);
      if (!Number.isFinite(num)) {
        parseError = `Invalid number for ${input.getAttribute("data-agent")}.${input.getAttribute("data-field")}`;
        return;
      }
      const agent = input.getAttribute("data-agent");
      const field = input.getAttribute("data-field");
      const value = field === "top_k" || field === "seed" ? Math.trunc(num) : num;
      if (input.getAttribute("data-scope") === "minimax") {
        doc[agent].model_overrides["minimax/*"][field] = value;
      } else {
        doc[agent][field] = value;
      }
    });
    if (parseError) {
      if (status) status.textContent = parseError;
      return;
    }
    MODEL_PARAMS_AGENTS.forEach((agent) => {
      if (!Object.keys(doc[agent].model_overrides["minimax/*"]).length) {
        delete doc[agent].model_overrides;
      }
    });
    try {
      await apiPut("/api/v1/agent/llm-params", { doc });
      if (status) status.textContent = "Saved. Restart the gateway to apply.";
    } catch (err) {
      if (status) status.textContent = err.message;
    }
  });
}

async function renderSchemaOntology() {
  const data = await apiGet("/api/v1/schema/ontology");
  const entries = data.ontology?.entries || [];
  return `
    <p>Schema: <strong>${data.schema_available ? "loaded" : "unavailable"}</strong>
      ${data.schema_title ? ` · ${escapeHtml(data.schema_title)}` : ""}
      ${data.property_count != null ? ` · ${data.property_count} top-level keys` : ""}</p>
    <p class="muted">Export: <code>${escapeHtml(data.schema_export_hint || "infra/sevn.schema.json")}</code></p>
    <h3>Ontology index</h3>
    <p class="muted">${escapeHtml(data.ontology?.path || "")}</p>
    ${tableFromRows(entries.slice(0, 40), [
      { key: "id", label: "#" },
      { key: "file", label: "Spec" },
      { key: "scope", label: "Scope" },
      { key: "parent_prd", label: "PRD" },
    ])}
    ${entries.length > 40 ? `<p class="muted">Showing 40 of ${entries.length} entries.</p>` : ""}
  `;
}

function bindSecurityHandlers() {
  document.querySelector("#security-toggles-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const scanner = {};
    form.querySelectorAll("input[data-security-key]").forEach((el) => {
      if (el instanceof HTMLInputElement) {
        scanner[el.dataset.securityKey || ""] = el.checked;
      }
    });
    try {
      await apiPut("/api/v1/security", { security: { scanner } });
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
}

function setNested(target, path, value) {
  const parts = path.split(".");
  let node = target;
  for (let i = 0; i < parts.length - 1; i += 1) {
    node[parts[i]] = node[parts[i]] || {};
    node = node[parts[i]];
  }
  node[parts[parts.length - 1]] = value;
}

function bindChannelsHandlers() {
  document.querySelector("#channels-config-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const channels = {};
    document.querySelectorAll("#channels-config-form input[data-channels-path]").forEach((el) => {
      if (el instanceof HTMLInputElement) {
        setNested(channels, el.dataset.channelsPath || "", el.checked);
      }
    });
    try {
      await apiPut("/api/v1/channels/config", { channels });
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
}

function bindTunnelsInfraHandlers() {
  document.querySelector("#ops-reload-config-btn")?.addEventListener("click", async () => {
    try {
      const resp = await apiPost("/api/v1/ops/reload-config", {});
      alert(resp.detail || resp.status || "Reloaded");
    } catch (err) {
      alert(err.message);
    }
  });
  document.querySelector("#ops-dreaming-run-btn")?.addEventListener("click", async () => {
    if (!window.confirm("Run one dreaming cycle now?")) return;
    try {
      await apiPost("/api/v1/ops/dreaming/run", opsConfirmBody());
      alert("Dreaming cycle triggered");
    } catch (err) {
      alert(err.message);
    }
  });
  document.querySelector("#tunnel-start-btn")?.addEventListener("click", async () => {
    if (!window.confirm("Start cloudflared tunnel? This spawns a child process.")) return;
    try {
      const resp = await apiPost("/api/v1/tunnels/start", { confirm: true });
      alert(resp.error ? `Error: ${resp.error.message}` : `cloudflared started (pid ${resp.pid})`);
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
  document.querySelector("#tunnel-stop-btn")?.addEventListener("click", async () => {
    if (!window.confirm("Stop cloudflared tunnel?")) return;
    try {
      await apiPost("/api/v1/tunnels/stop", { confirm: true });
      alert("cloudflared stopped");
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
  content.querySelectorAll(".daemon-action-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const service = btn.getAttribute("data-service");
      const action = btn.getAttribute("data-action");
      if (!service || !action || !window.confirm(`${action} ${service} daemon?`)) return;
      try {
        const resp = await apiPost(
          `/api/v1/ops/daemons/${encodeURIComponent(service)}/${encodeURIComponent(action)}`,
          opsConfirmBody(),
        );
        alert(resp.detail || "Done");
        await renderContent();
      } catch (err) {
        alert(err.message);
      }
    });
  });
}

function bindBackupSnapshotsHandlers() {
  document.querySelector("#backup-export-btn")?.addEventListener("click", () => {
    window.location.href = "/api/v1/ops/backup/export";
  });
  document.querySelector("#snapshot-create-btn")?.addEventListener("click", async () => {
    if (!window.confirm("Create a new workspace snapshot?")) return;
    try {
      const resp = await apiPost("/api/v1/ops/snapshots", opsConfirmBody());
      alert(`Snapshot created: ${resp.snapshot_id || "ok"}`);
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
  content.querySelectorAll(".snapshot-restore-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const snapshotId = btn.getAttribute("data-snapshot-id");
      if (!snapshotId || !window.confirm(`Restore snapshot ${snapshotId}? This overwrites workspace files.`)) return;
      try {
        await apiPost(
          `/api/v1/ops/snapshots/${encodeURIComponent(snapshotId)}/restore`,
          opsConfirmBody(),
        );
        alert("Snapshot restored — reload config if needed");
        await renderContent();
      } catch (err) {
        alert(err.message);
      }
    });
  });
  document.querySelector("#backup-import-input")?.addEventListener("change", async (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || !input.files?.length) return;
    if (!window.confirm("Import config backup archive? This overwrites sevn.json backups.")) return;
    const form = new FormData();
    form.append("archive", input.files[0]);
    form.append("confirm_token", OPS_CONFIRM_TOKEN);
    try {
      const resp = await fetch("/api/v1/ops/backup/import", {
        method: "POST",
        credentials: "include",
        headers: { "X-CSRF-Token": csrfToken() },
        body: form,
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data?.error?.message || resp.statusText);
      alert(`Imported: ${(data.imported || []).join(", ")}`);
      input.value = "";
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
}

function bindCronHandlers() {
  document.querySelector("#cron-config-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.querySelector("#cron-paused-input");
    if (!(input instanceof HTMLInputElement)) return;
    try {
      await apiPut("/api/v1/cron/config", { paused: input.checked });
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
  document.querySelector("#cron-create-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const jobId = document.querySelector("#cron-new-id")?.value?.trim();
    const cronExpr = document.querySelector("#cron-new-expr")?.value?.trim();
    const timezone = document.querySelector("#cron-new-tz")?.value?.trim() || "UTC";
    const payload = document.querySelector("#cron-new-payload")?.value?.trim() || null;
    if (!jobId || !cronExpr) return;
    try {
      await apiPost("/api/v1/cron/jobs", {
        job_id: jobId,
        cron_expr: cronExpr,
        timezone,
        payload_template: payload,
      });
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
  content.querySelectorAll(".cron-run-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const jobId = btn.getAttribute("data-job-id");
      if (!jobId || !window.confirm(`Run cron job ${jobId} now?`)) return;
      try {
        await apiPost(`/api/v1/cron/jobs/${encodeURIComponent(jobId)}/run`, opsConfirmBody());
        alert(`Triggered ${jobId}`);
      } catch (err) {
        alert(err.message);
      }
    });
  });
  content.querySelectorAll(".cron-toggle-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const jobId = btn.getAttribute("data-job-id");
      const enabled = btn.getAttribute("data-enabled") === "1";
      if (!jobId) return;
      try {
        const jobs = await apiGet("/api/v1/cron/jobs");
        const job = (jobs.jobs || []).find((row) => row.job_id === jobId);
        if (!job) return;
        await apiPut(`/api/v1/cron/jobs/${encodeURIComponent(jobId)}`, {
          ...job,
          enabled,
        });
        await renderContent();
      } catch (err) {
        alert(err.message);
      }
    });
  });
  content.querySelectorAll(".cron-delete-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const jobId = btn.getAttribute("data-job-id");
      if (!jobId || !window.confirm(`Delete cron job ${jobId}?`)) return;
      try {
        await fetch(`/api/v1/cron/jobs/${encodeURIComponent(jobId)}`, {
          method: "DELETE",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken(),
          },
          body: JSON.stringify(opsConfirmBody()),
        }).then(async (resp) => {
          if (!resp.ok) {
            const data = await resp.json();
            throw new Error(data?.error?.message || resp.statusText);
          }
        });
        await renderContent();
      } catch (err) {
        alert(err.message);
      }
    });
  });
}

function bindToolsPermissionsHandlers() {
  document.querySelectorAll(".tool-approval-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const decisionId = btn.getAttribute("data-decision-id") || "";
      const verdict = btn.getAttribute("data-verdict") || "deny";
      if (!decisionId) return;
      try {
        await submitToolApproval(decisionId, verdict);
        await renderContent();
      } catch (err) {
        alert(err.message);
      }
    });
  });
  document.querySelector("#permissions-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const permsEl = document.querySelector("#permissions-editor");
    const toolsEl = document.querySelector("#tools-editor");
    const statusEl = document.querySelector("#permissions-status");
    if (!(permsEl instanceof HTMLTextAreaElement) || !(toolsEl instanceof HTMLTextAreaElement)) return;
    let body;
    try {
      body = { permissions: JSON.parse(permsEl.value), tools: JSON.parse(toolsEl.value) };
    } catch (err) {
      if (statusEl) statusEl.textContent = `Invalid JSON: ${err.message}`;
      return;
    }
    try {
      await apiPut("/api/v1/agent/permissions", body);
      if (statusEl) statusEl.textContent = "Saved.";
      await renderContent();
    } catch (err) {
      if (statusEl) statusEl.textContent = `Save failed: ${err.message}`;
    }
  });
}

function bindMcpServersHandlers() {
  document.querySelector("#mcp-servers-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const enabled = [];
    document.querySelectorAll("#mcp-servers-form input[data-mcp-server]").forEach((el) => {
      if (el instanceof HTMLInputElement && el.checked) {
        enabled.push(el.dataset.mcpServer || "");
      }
    });
    try {
      await apiPut("/api/v1/agent/mcp-servers", { mcp_enabled: enabled });
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
}

function bindTelegramMenuHandlers() {
  document.querySelector("#telegram-menu-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const telegram = {};
    const replyEl = document.querySelector("#telegram-menu-form input[data-telegram-key='reply_keyboard_enabled']");
    if (replyEl instanceof HTMLInputElement) {
      telegram.reply_keyboard = { enabled: replyEl.checked };
    }
    const routingEl = document.querySelector("#telegram-menu-form input[data-telegram-key='show_routing']");
    if (routingEl instanceof HTMLInputElement) {
      telegram.show_routing = routingEl.checked;
    }
    const quick = {};
    document.querySelectorAll("#telegram-menu-form input[data-telegram-qa]").forEach((el) => {
      if (el instanceof HTMLInputElement) {
        quick[el.dataset.telegramQa || ""] = el.checked;
      }
    });
    if (Object.keys(quick).length) {
      telegram.quick_actions = quick;
    }
    try {
      await apiPut("/api/v1/surfaces/telegram-menu", { telegram });
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
}

function bindWebAppsHandlers() {
  document.querySelector("#web-apps-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const webchat = {};
    document.querySelectorAll("#web-apps-form input[data-webchat-key]").forEach((el) => {
      if (el instanceof HTMLInputElement) {
        webchat[el.dataset.webchatKey || ""] = el.checked;
      }
    });
    const originsEl = document.querySelector("#web-apps-origins");
    if (originsEl instanceof HTMLInputElement) {
      webchat.allowed_origins = originsEl.value
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
    }
    try {
      await apiPut("/api/v1/surfaces/web-apps", { webchat });
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
}

function bindSecretsHandlers() {
  const output = document.querySelector("#secrets-output");
  const setSecretsShowValues = async (show) => {
    const banner = document.querySelector("#secrets-exposed-banner");
    if (banner) banner.hidden = !show;
    const cells = document.querySelectorAll(".secrets-value-cell");
    await Promise.all(
      Array.from(cells).map(async (cell) => {
        if (!show) {
          cell.textContent = SECRETS_MASK;
          delete cell.dataset.revealed;
          return;
        }
        if (cell.dataset.revealed === "1") return;
        const kind = cell.dataset.secretKind;
        const key = cell.dataset.secretKey;
        if (!kind || !key) return;
        cell.textContent = "…";
        try {
          let plaintext;
          if (kind === "config-alias") {
            const resp = await fetch(
              `/api/v1/secrets/aliases/${encodeURIComponent(key)}/reveal`,
              {
                credentials: "include",
                headers: { "X-CSRF-Token": csrfToken() },
              },
            );
            if (!resp.ok) throw new Error(String(resp.status));
            const data = await resp.json();
            plaintext = data.plaintext;
          } else if (kind === "store-entry") {
            const data = await apiGet(`/api/v1/secrets/store/entries/${encodeURIComponent(key)}`);
            plaintext = data.plaintext;
          } else {
            throw new Error("unknown secret kind");
          }
          cell.textContent = plaintext;
          cell.dataset.revealed = "1";
        } catch (_err) {
          cell.textContent = SECRETS_REVEAL_FAILED;
        }
      }),
    );
  };
  document.querySelector("#secrets-show-values")?.addEventListener("change", (ev) => {
    setSecretsShowValues(ev.target.checked).catch(() => {});
  });
  document.querySelector("#secrets-reveal-btn")?.addEventListener("click", async () => {
    const alias = document.querySelector("#secrets-alias")?.value?.trim();
    if (!alias) return;
    try {
      const data = await apiGet(`/api/v1/secrets/store/entries/${encodeURIComponent(alias)}`);
      if (output) output.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      if (output) output.textContent = err.message;
    }
  });
  document.querySelector("#secrets-save-btn")?.addEventListener("click", async () => {
    const alias = document.querySelector("#secrets-alias")?.value?.trim();
    const plaintext = document.querySelector("#secrets-value")?.value ?? "";
    const confirmFp = document.querySelector("#secrets-fingerprint")?.value?.trim();
    if (!alias || !plaintext) return;
    const body = { plaintext };
    if (confirmFp) body.confirm_fingerprint = confirmFp;
    try {
      const data = await apiPut(`/api/v1/secrets/store/entries/${encodeURIComponent(alias)}`, body);
      if (output) output.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      if (output) output.textContent = err.message;
    }
  });
  document.querySelector("#secrets-delete-btn")?.addEventListener("click", async () => {
    const alias = document.querySelector("#secrets-alias")?.value?.trim();
    const confirmFp = document.querySelector("#secrets-fingerprint")?.value?.trim();
    if (!alias || !confirmFp || !window.confirm(`Delete secret ${alias}?`)) return;
    try {
      const resp = await fetch(`/api/v1/secrets/store/entries/${encodeURIComponent(alias)}`, {
        method: "DELETE",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken(),
        },
        body: JSON.stringify({ confirm_alias: alias, confirm_fingerprint: confirmFp }),
      });
      const data = await resp.json();
      if (output) output.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      if (output) output.textContent = err.message;
    }
  });
}

function bindSevnCliHandlers() {
  const output = document.querySelector("#cli-output");
  const run = async (argv) => {
    const confirm = document.querySelector("#cli-confirm")?.checked;
    const body = { argv };
    if (confirm) body.confirm_token = "confirm";
    try {
      const data = await apiPost("/api/v1/cli/run", body);
      if (output) {
        output.textContent = [
          `exit=${data.exit_code} (${data.duration_ms}ms)`,
          data.stdout || "",
          data.stderr ? `stderr:\n${data.stderr}` : "",
        ]
          .filter(Boolean)
          .join("\n");
      }
    } catch (err) {
      if (output) output.textContent = err.message;
    }
  };
  document.querySelector("#cli-run-btn")?.addEventListener("click", () => {
    const raw = document.querySelector("#cli-args")?.value?.trim();
    if (!raw) return;
    run(raw.split(/\s+/));
  });
  document.querySelectorAll(".cli-shortcut-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const raw = btn.getAttribute("data-cli-argv");
      if (!raw) return;
      try {
        run(JSON.parse(raw));
      } catch (_err) {
        /* ignore */
      }
    });
  });
}

function bindEgressProxyHandlers() {
  document.querySelector("#proxy-restart-btn")?.addEventListener("click", async () => {
    if (!confirm("Restart the egress proxy service unit?")) return;
    try {
      await apiPost("/api/v1/proxy/restart");
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
  document.querySelector("#proxy-refresh-logs-btn")?.addEventListener("click", () => {
    renderContent().catch((err) => {
      content.innerHTML = `<article class="card"><p class="error">${escapeHtml(err.message)}</p></article>`;
    });
  });
}

function bindConfigHandlers() {
  const statusEl = document.querySelector("#config-editor-status");
  const editor = document.querySelector("#config-editor");
  const treePanel = document.querySelector("#config-tree-panel");
  const errorPanel = document.querySelector("#config-error-panel");
  const treeBtn = document.querySelector("#config-mode-tree");
  const textBtn = document.querySelector("#config-mode-text");

  const showErrors = (message) => {
    if (!(errorPanel instanceof HTMLElement)) {
      return;
    }
    if (!message) {
      errorPanel.hidden = true;
      errorPanel.textContent = "";
      return;
    }
    errorPanel.hidden = false;
    errorPanel.textContent = message;
  };

  const setMode = (mode) => {
    configEditorMode = mode;
    if (treePanel instanceof HTMLElement) {
      treePanel.hidden = mode !== "tree";
    }
    if (editor instanceof HTMLTextAreaElement) {
      editor.hidden = mode !== "text";
      if (mode === "text" && configDraft) {
        syncConfigDraftFromTree(treePanel);
        editor.value = JSON.stringify(configDraft, null, 2);
      }
    }
    treeBtn?.classList.toggle("btn-primary", mode === "tree");
    treeBtn?.classList.toggle("btn-secondary", mode !== "tree");
    textBtn?.classList.toggle("btn-primary", mode === "text");
    textBtn?.classList.toggle("btn-secondary", mode !== "text");
  };

  treeBtn?.addEventListener("click", () => {
    if (editor instanceof HTMLTextAreaElement) {
      try {
        configDraft = JSON.parse(editor.value);
      } catch (err) {
        if (statusEl) statusEl.textContent = `Invalid JSON: ${err.message}`;
        return;
      }
    }
    if (treePanel instanceof HTMLElement && configDraft) {
      treePanel.innerHTML = renderConfigTreeMarkup(configDraft);
    }
    setMode("tree");
    showErrors("");
  });

  textBtn?.addEventListener("click", () => {
    syncConfigDraftFromTree(treePanel);
    setMode("text");
    showErrors("");
  });

  setMode("tree");

  const currentDoc = () => {
    if (configEditorMode === "text" && editor instanceof HTMLTextAreaElement) {
      return JSON.parse(editor.value);
    }
    syncConfigDraftFromTree(treePanel);
    return structuredClone(configDraft || {});
  };

  document.querySelector("#config-validate-btn")?.addEventListener("click", async () => {
    try {
      const doc = currentDoc();
      await apiPut("/api/v1/config/full?dry_run=1", doc);
      if (statusEl) statusEl.textContent = "Validation passed.";
      showErrors("");
    } catch (err) {
      const msg = formatConfigErrors(err.body) || err.message;
      if (statusEl) statusEl.textContent = "Validation failed.";
      showErrors(msg);
    }
  });

  document.querySelector("#config-save-btn")?.addEventListener("click", async () => {
    if (!confirm("Write sevn.json on disk? Gateway may need restart for some keys.")) return;
    try {
      const doc = currentDoc();
      await apiPut("/api/v1/config/full", doc);
      if (statusEl) statusEl.textContent = "Saved.";
      showErrors("");
      await renderContent();
    } catch (err) {
      const msg = formatConfigErrors(err.body) || err.message;
      if (statusEl) statusEl.textContent = "Save failed.";
      showErrors(msg);
    }
  });
}

async function renderAlertsLogs() {
  const [rollup, proxyLogs] = await Promise.all([
    apiGet("/api/v1/alerts/rollup?limit=30"),
    apiGet("/api/v1/proxy/logs"),
  ]);
  const missionAlerts = rollup.mission_alerts || [];
  const traceErrors = rollup.trace_errors || [];
  const logsDir = rollup.logs_dir || "";
  const proxyPath = rollup.proxy_log || proxyLogs.path || "";
  const logLines = (proxyLogs.lines || []).map((line) => escapeHtml(line)).join("\n");
  return `
    <p class="muted">Workspace logs: <code>${escapeHtml(logsDir)}</code> · proxy log <code>${escapeHtml(proxyPath)}</code></p>
    <h3>Mission alerts</h3>
    ${tableFromRows(missionAlerts, [
      { key: "severity", label: "Severity" },
      { key: "rule", label: "Rule" },
      { key: "message", label: "Message" },
      { key: "timestamp", label: "Time" },
      { key: "acknowledged", label: "Ack" },
    ])}
    <h3>Recent error traces</h3>
    ${tableFromRows(traceErrors, [
      { key: "kind", label: "Kind" },
      { key: "session_id", label: "Session" },
      { key: "turn_id", label: "Turn" },
      { key: "status", label: "Status" },
      { key: "ts_start_ns", label: "ts (ns)" },
    ])}
    <h3>Proxy log tail</h3>
    <pre class="trace-attrs log-tail">${logLines || "(no proxy log lines yet)"}</pre>
    <button type="button" class="btn" id="alerts-refresh-logs">Refresh proxy log</button>
  `;
}

function bindAlertsLogsHandlers() {
  document.querySelector("#alerts-refresh-logs")?.addEventListener("click", () => {
    renderContent().catch((err) => {
      content.innerHTML = `<article class="card"><p class="error">${escapeHtml(err.message)}</p></article>`;
    });
  });
}

async function evalReportSection(selectedJobId, heading = "Eval report") {
  if (!selectedJobId) return "";
  try {
    const payload = await apiGet(
      `/api/v1/self_improve/jobs/${encodeURIComponent(selectedJobId)}/eval_report`,
    );
    const report = payload.report || {};
    const segments = (report.segments || []).map((seg) => ({
      name: seg.name,
      status: seg.status,
      detail: seg.detail || "",
    }));
    return `
      <h3>${heading} — ${escapeHtml(selectedJobId)}</h3>
      <p>Overall: <strong>${report.passed ? "passed" : "failed"}</strong> · schema v${escapeHtml(report.schema_version ?? "?")}</p>
      ${tableFromRows(segments, [
        { key: "name", label: "Segment" },
        { key: "status", label: "Status" },
        { key: "detail", label: "Detail" },
      ])}
      <p><a href="/mission/traces?job_id=${encodeURIComponent(selectedJobId)}">View traces for this job</a></p>
    `;
  } catch (err) {
    return `<p class="error">Eval report unavailable: ${escapeHtml(err.message)}</p>`;
  }
}

function bindJobsHandlers() {
  const btn = document.querySelector("#si-enqueue-job");
  btn?.addEventListener("click", async () => {
    try {
      const resp = await apiPost("/api/v1/self_improve/jobs", { experiment_id: "default" });
      const jobId = resp.job_id || "";
      if (jobId) {
        const url = new URL(location.href);
        url.searchParams.set("job_id", jobId);
        history.pushState({}, "", url);
      }
      await renderContent();
    } catch (err) {
      alert(`Enqueue failed: ${err.message}`);
    }
  });
  document.querySelector("#si-cycle-btn")?.addEventListener("click", async () => {
    if (!window.confirm("Trigger one self-improve cycle (confirm-gated)?")) return;
    try {
      const resp = await apiPost("/api/v1/self_improve/cycle", opsConfirmBody());
      alert(`Cycle enqueued: ${resp.job_id || "ok"}`);
      await renderContent();
    } catch (err) {
      alert(`Cycle failed: ${err.message}`);
    }
  });
}

async function renderJobs() {
  const selectedJobId = new URLSearchParams(location.search).get("job_id") || "";
  const page = await apiGet("/api/v1/self_improve/jobs?limit=50");
  const jobs = page.items || [];
  const jobRows = jobs.map((job) => ({
    job_id: job.job_id,
    state: job.state,
    preset: job.preset,
    detail: `<a href="/mission/jobs?job_id=${encodeURIComponent(job.job_id)}">Eval report</a>`,
  }));
  const planLink = selectedJobId
    ? `<p><a href="${escapeHtml(specKitRunsHref({ jobId: selectedJobId }))}">Open in Spec-Kit runs</a> · spec-kit plan: <code>.sevn/improve/${escapeHtml(selectedJobId)}/spec-kit/plan.md</code></p>`
    : "";
  const evalSection = await evalReportSection(selectedJobId, "Eval report");
  return `
    <h3>Improve jobs</h3>
    <p>
      <button type="button" class="btn btn-primary btn-sm" id="si-enqueue-job">Run improve job</button>
      <button type="button" class="btn btn-sm btn-secondary" id="si-cycle-btn">Trigger cycle (confirm)</button>
    </p>
    ${planLink}
    ${tableFromRows(jobRows, [
      { key: "job_id", label: "Job" },
      { key: "state", label: "State" },
      { key: "preset", label: "Preset" },
      { key: "detail", label: "Drill-down" },
    ])}
    ${evalSection}
  `;
}

async function renderTrajectories() {
  const selectedJobId = new URLSearchParams(location.search).get("job_id") || "";
  const page = await apiGet("/api/v1/self_improve/trajectories?limit=50");
  const rows = (page.items || []).map((row) => ({
    turn_id: escapeHtml(row.turn_id || ""),
    session_id: escapeHtml(row.session_id || ""),
    tier: escapeHtml(row.tier || ""),
    model_id: escapeHtml(row.model_id || ""),
    channel: escapeHtml(row.channel || ""),
    created_at: escapeHtml(row.created_at || ""),
  }));
  const evalSection = await evalReportSection(selectedJobId, "Job eval report");
  const jobHint = selectedJobId
    ? `<p class="muted">Context job <code>${escapeHtml(selectedJobId)}</code> — <a href="/mission/jobs?job_id=${encodeURIComponent(selectedJobId)}">Jobs tab</a></p>`
    : "";
  return `
    <p class="muted">Sampler-facing <code>trajectory_fact</code> rows ingested from persisted traces.</p>
    ${jobHint}
    ${tableFromRows(rows, [
      { key: "turn_id", label: "Turn" },
      { key: "session_id", label: "Session" },
      { key: "tier", label: "Tier" },
      { key: "model_id", label: "Model" },
      { key: "channel", label: "Channel" },
      { key: "created_at", label: "Created" },
    ])}
    ${evalSection}
  `;
}

async function renderFeedback() {
  const page = await apiGet("/api/v1/self_improve/feedback?limit=50");
  const eventRows = (page.events || []).map((row) => ({
    kind: escapeHtml(row.kind || ""),
    target_turn_id: escapeHtml(row.target_turn_id || ""),
    created_at: escapeHtml(row.created_at || ""),
    payload: `<code>${escapeHtml(JSON.stringify(row.payload || {})).slice(0, 120)}</code>`,
  }));
  const structuredRows = (page.structured || []).map((row) => ({
    channel: escapeHtml(row.channel || ""),
    user_id: escapeHtml(row.user_id || ""),
    target_turn_id: escapeHtml(row.target_turn_id || ""),
    body_preview: escapeHtml(row.body_preview || ""),
    created_at: escapeHtml(row.created_at || ""),
  }));
  return `
    <p class="muted">Operator thumbs and structured free-text feedback (<code>feedback_events</code> + <code>structured_feedback</code>).</p>
    <h3>Feedback events</h3>
    ${tableFromRows(eventRows, [
      { key: "kind", label: "Kind" },
      { key: "target_turn_id", label: "Turn" },
      { key: "created_at", label: "Created" },
      { key: "payload", label: "Payload" },
    ])}
    <h3>Structured feedback</h3>
    ${tableFromRows(structuredRows, [
      { key: "channel", label: "Channel" },
      { key: "user_id", label: "User" },
      { key: "target_turn_id", label: "Turn" },
      { key: "body_preview", label: "Body" },
      { key: "created_at", label: "Created" },
    ])}
  `;
}

async function renderRlmConfig() {
  const page = await apiGet("/api/v1/self_improve/rlm-training");
  const rlm = page.rlm || {};
  const si = page.self_improve || {};
  const jobs = page.jobs || {};
  const byState = jobs.by_state || {};
  const stateList = Object.entries(byState)
    .map(([state, count]) => `<li><code>${escapeHtml(state)}</code>: <strong>${count}</strong></li>`)
    .join("");
  const recentRows = (jobs.recent || []).map((job) => ({
    job_id: escapeHtml(job.job_id || ""),
    state: escapeHtml(job.state || ""),
    preset: escapeHtml(job.preset || ""),
    detail: `<a href="/mission/jobs?job_id=${encodeURIComponent(job.job_id || "")}">Open</a>`,
  }));
  const tierCounts = page.trajectory_tier_counts || {};
  const tierList = Object.entries(tierCounts)
    .map(([tier, count]) => `<li><code>${escapeHtml(tier)}</code>: <strong>${count}</strong></li>`)
    .join("");
  const lambdaGate = rlm.tier_cd_lambda_rlm
    ? `<li>λ-RLM gate: <code>${escapeHtml(JSON.stringify(rlm.tier_cd_lambda_rlm))}</code></li>`
    : "";
  return `
    <p class="muted">Read-only tier C/D RLM posture and improve-job queue summary (no config writes).</p>
    <h3>RLM config</h3>
    <ul>
      <li><code>rlm.c_d_backend</code>: <strong>${escapeHtml(rlm.c_d_backend || "")}</strong></li>
      <li><code>rlm.repl_lifetime</code>: <strong>${escapeHtml(rlm.repl_lifetime || "")}</strong></li>
      <li>λ tool allowlist: <code>${escapeHtml((rlm.lambda_tool_allowlist || []).join(", ") || "(empty)")}</code></li>
      ${lambdaGate}
    </ul>
    <h3>Self-improve</h3>
    <ul>
      <li>Enabled: <strong>${si.enabled ? "yes" : "no"}</strong></li>
      <li>Preset: <code>${escapeHtml(si.preset || "n/a")}</code></li>
      <li>Eval docker required: <strong>${si.eval_docker_required == null ? "default" : si.eval_docker_required ? "yes" : "no"}</strong></li>
    </ul>
    <h3>Job states</h3>
    <ul>${stateList || "<li class=\"muted\">(no jobs yet)</li>"}</ul>
    <h3>Trajectory tiers</h3>
    <ul>${tierList || "<li class=\"muted\">(no trajectory facts yet)</li>"}</ul>
    <h3>Recent jobs</h3>
    ${tableFromRows(recentRows, [
      { key: "job_id", label: "Job" },
      { key: "state", label: "State" },
      { key: "preset", label: "Preset" },
      { key: "detail", label: "Drill-down" },
    ])}
  `;
}

async function renderExperimentsMetrics() {
  const selectedJobId = new URLSearchParams(location.search).get("job_id") || "";
  const page = await apiGet("/api/v1/self_improve/experiments?limit=50");
  const rows = (page.experiments || []).map((exp) => {
    const passLabel =
      exp.eval_passed == null ? "n/a" : exp.eval_passed ? "passed" : "failed";
    return {
      experiment_id: escapeHtml(exp.experiment_id || ""),
      job_count: String(exp.job_count ?? 0),
      latest_state: escapeHtml(exp.latest_state || ""),
      eval: escapeHtml(passLabel),
      detail: exp.latest_job_id
        ? `<a href="/mission/jobs?job_id=${encodeURIComponent(exp.latest_job_id)}">Latest job</a>`
        : "",
    };
  });
  const evalSection = await evalReportSection(selectedJobId, "Job eval report");
  return `
    <p class="muted">Experiment aggregates from <code>self_improve_jobs.experiment_snapshot_json</code> with eval pass/fail rollups.</p>
    ${tableFromRows(rows, [
      { key: "experiment_id", label: "Experiment" },
      { key: "job_count", label: "Jobs" },
      { key: "latest_state", label: "Latest state" },
      { key: "eval", label: "Latest eval" },
      { key: "detail", label: "Drill-down" },
    ])}
    ${evalSection}
  `;
}

function evolutionIssueTopic(issueId) {
  return issueId ? `evolution.issue.${issueId}` : "";
}

function specKitRunsHref({ jobId = "", issueId = "" } = {}) {
  const params = new URLSearchParams();
  if (jobId) params.set("job_id", jobId);
  if (issueId) params.set("issue_id", issueId);
  const qs = params.toString();
  return qs ? `/mission/spec-kit?${qs}` : "/mission/spec-kit";
}

async function renderEvolutionIssues() {
  const page = await apiGet("/api/v1/evolution/issues?limit=50");
  const rows = (page.items || []).map((issue) => {
    const issueId = issue.id || "";
    const prLink = issue.pr_url
      ? `<a href="${escapeHtml(issue.pr_url)}" target="_blank" rel="noopener noreferrer">PR</a>`
      : "";
    const agentLink = issue.agent_url
      ? `<a href="${escapeHtml(issue.agent_url)}" target="_blank" rel="noopener noreferrer">Agent</a>`
      : "";
    const worktree = issue.worktree_path ? `<code title="${escapeHtml(String(issue.worktree_path))}">${escapeHtml(_redactPath(issue.worktree_path))}</code>` : "";
    return {
      id: `<code>${escapeHtml(issueId)}</code>`,
      kind: escapeHtml(issue.kind || ""),
      title: escapeHtml(issue.title || ""),
      state: escapeHtml(issue.state || ""),
      executor: executorBadge(issue),
      pr_agent: [prLink, agentLink, worktree].filter(Boolean).join(" · "),
      actions: issueId ? `
        <button type="button" class="btn btn-sm btn-primary issue-run-pipeline" data-issue-id="${escapeHtml(issueId)}">Run</button>
        <a href="${escapeHtml(specKitRunsHref({ issueId }))}" class="btn btn-sm btn-muted">Spec-kit</a>
      ` : "",
    };
  });
  return `
    <p class="muted">Local evolution issues under <code>.sevn/issues/</code>. Executor routing uses <code>my_sevn.executors.*</code>.</p>
    <div class="form-grid" style="margin-bottom:1rem">
      <label>Import GitHub issue by number
        <input id="gh-import-number" type="number" min="1" placeholder="42" style="width:8rem">
      </label>
      <button type="button" class="btn btn-primary" id="gh-import-btn">Import</button>
      <button type="button" class="btn btn-muted" id="gh-sync-btn">Sync now</button>
    </div>
    <div id="issues-run-form" class="form-grid" style="margin-bottom:1rem;display:none">
      <strong id="issues-run-form-title">Run pipeline</strong>
      <label>Stage
        <select id="run-stage">
          <option value="auto">auto</option>
          <option value="plan">plan</option>
          <option value="implement">implement</option>
          <option value="ci">ci</option>
          <option value="promote">promote</option>
        </select>
      </label>
      <label>Executor
        <select id="run-executor">
          <option value="">auto (config)</option>
          <option value="local">local</option>
          <option value="cursor_cloud">cursor_cloud</option>
          <option value="chat">chat</option>
        </select>
      </label>
      <label style="display:flex;gap:.5rem;align-items:center">
        <input type="checkbox" id="run-live"> Live (all dry-runs off)
      </label>
      <button type="button" class="btn btn-primary" id="run-submit-btn">Run</button>
      <button type="button" class="btn btn-muted" id="run-cancel-btn">Cancel</button>
    </div>
    ${tableFromRows(rows, [
      { key: "id", label: "ID" },
      { key: "kind", label: "Kind" },
      { key: "title", label: "Title" },
      { key: "state", label: "State" },
      { key: "executor", label: "Executor" },
      { key: "pr_agent", label: "PR / Agent / Worktree" },
      { key: "actions", label: "Actions" },
    ])}
  `;
}

/** Build a compact stage stepper HTML from a ``stages`` list (from /pipelines/{id}). */
function _renderStageStepper(stages) {
  if (!stages || !stages.length) return "";
  const pills = stages.map((s) => {
    const cls = s.status === "done" ? "badge badge-success" : s.status === "active" ? "badge badge-info" : "badge badge-muted";
    return `<span class="${cls}" title="${escapeHtml(s.id)}">${escapeHtml(s.label)}</span>`;
  }).join(" › ");
  return `<div class="pipeline-stepper">${pills}</div>`;
}

async function renderEvolutionPipelines() {
  const page = await apiGet("/api/v1/evolution/pipelines?limit=50");
  evolutionWsIssueIds = (page.items || [])
    .map((issue) => issue.issue_id || issue.id || "")
    .filter(Boolean);
  const rows = (page.items || []).map((issue) => {
    const issueId = issue.issue_id || issue.id || "";
    const stepper = _renderStageStepper(issue.stages || []);
    const prLink = issue.pr_url
      ? `<a href="${escapeHtml(issue.pr_url)}" target="_blank" rel="noopener noreferrer">PR</a>`
      : "";
    return {
      id: `<code>${escapeHtml(issueId)}</code>`,
      stage: stepper || escapeHtml(issue.pipeline_stage || issue.state || ""),
      executor: executorBadge(issue),
      pr: prLink,
      spec_kit: issueId
        ? `<a href="${escapeHtml(specKitRunsHref({ issueId }))}">Runs</a>`
        : "",
      actions: issueId ? `
        <button type="button" class="btn btn-sm btn-primary pipeline-run" data-issue-id="${escapeHtml(issueId)}">Run</button>
        <button type="button" class="btn btn-sm btn-muted pipeline-poll" data-issue-id="${escapeHtml(issueId)}">Poll</button>
        <button type="button" class="btn btn-sm btn-danger pipeline-kill" data-issue-id="${escapeHtml(issueId)}">Kill</button>
      ` : "",
    };
  });
  return `
    <p class="muted">Active pipeline runs. Log lines publish on WebSocket topic <code>evolution.issue.{id}</code>.</p>
    ${tableFromRows(rows, [
      { key: "id", label: "Issue" },
      { key: "stage", label: "Stage stepper" },
      { key: "executor", label: "Executor" },
      { key: "pr", label: "PR" },
      { key: "spec_kit", label: "Spec-kit" },
      { key: "actions", label: "Actions" },
    ])}
  `;
}

async function renderEvolutionApprovals() {
  const page = await apiGet("/api/v1/evolution/approvals?pending_only=true&limit=50");
  evolutionWsIssueIds = (page.items || []).map((row) => row.issue_id || "").filter(Boolean);
  const rows = (page.items || []).map((row) => {
    const issueId = row.issue_id || "";
    return {
      id: `<code>${escapeHtml(row.id)}</code>`,
      kind: escapeHtml(row.kind || ""),
      title: escapeHtml(row.title || ""),
      issue: issueId
        ? `<a href="/mission/pipelines"><code>${escapeHtml(issueId)}</code></a>`
        : "",
      spec_kit: issueId
        ? `<a href="${escapeHtml(specKitRunsHref({ issueId }))}">Runs</a>`
        : "",
      actions: `<button type="button" class="btn btn-sm btn-primary approval-approve" data-id="${escapeHtml(row.id)}">Approve</button>
      <button type="button" class="btn btn-sm btn-danger approval-reject" data-id="${escapeHtml(row.id)}">Reject</button>`,
    };
  });
  return `
    <p class="muted">Feature plan/tasks HITL queue. Approve unblocks the linked pipeline.</p>
    ${tableFromRows(rows, [
      { key: "id", label: "Approval" },
      { key: "kind", label: "Kind" },
      { key: "title", label: "Title" },
      { key: "issue", label: "Issue" },
      { key: "spec_kit", label: "Spec-kit" },
      { key: "actions", label: "Actions" },
    ])}
  `;
}

async function renderEvolutionTraces() {
  const page = await apiGet("/api/v1/evolution/traces?limit=50");
  const rows = (page.items || []).map((row) => ({
    kind: escapeHtml(row.kind || ""),
    status: escapeHtml(row.status || ""),
    session: escapeHtml(row.session_id || ""),
    link: row.issue_link
      ? `<a href="${escapeHtml(row.issue_link)}">Issue</a>`
      : row.job_link
        ? `<a href="${escapeHtml(row.job_link)}">Job</a>`
        : "",
  }));
  return `
    <p class="muted">Filtered to trace kinds <code>evolution.*</code> and <code>self_improve.*</code>.</p>
    ${tableFromRows(rows, [
      { key: "kind", label: "Kind" },
      { key: "status", label: "Status" },
      { key: "session", label: "Session" },
      { key: "link", label: "Link" },
    ])}
  `;
}

async function renderEvolutionStats() {
  const stats = await apiGet("/api/v1/evolution/stats");
  const evalStats = stats.eval || {};
  const passRate =
    evalStats.pass_rate == null ? "n/a" : `${Math.round(evalStats.pass_rate * 100)}%`;
  const lastSync = stats.last_sync
    ? escapeHtml(stats.last_sync.completed_at || stats.last_sync.status || "unknown")
    : "never";
  return `
    <ul>
      <li>Issues open: <strong>${stats.issues_open ?? 0}</strong></li>
      <li>Issues closed: <strong>${stats.issues_closed ?? 0}</strong></li>
      <li>PRs linked: <strong>${stats.prs ?? 0}</strong></li>
      <li>Eval pass rate: <strong>${passRate}</strong> (${evalStats.passed ?? 0}/${evalStats.total ?? 0})</li>
      <li>Last <code>sevn sync</code>: <strong>${lastSync}</strong></li>
    </ul>
  `;
}

let specKitSavedText = "";

function specKitMarkDirty() {
  const textarea = document.querySelector("#spec-kit-constitution");
  const dirty = document.querySelector("#spec-kit-dirty");
  if (!textarea || !dirty) return;
  const isDirty = textarea.value !== specKitSavedText;
  dirty.hidden = !isDirty;
  dirty.textContent = isDirty ? "Unsaved changes" : "";
}

async function renderSpecKit() {
  const search = new URLSearchParams(location.search);
  const filterJobId = search.get("job_id") || "";
  const filterIssueId = search.get("issue_id") || "";
  const runsQuery = new URLSearchParams({ limit: "50" });
  if (filterJobId) runsQuery.set("job_id", filterJobId);
  if (filterIssueId) runsQuery.set("issue_id", filterIssueId);
  const [constitution, options, runsPage] = await Promise.all([
    apiGet("/api/v1/spec-kit/constitution"),
    apiGet("/api/v1/spec-kit/options"),
    apiGet(`/api/v1/spec-kit/runs?${runsQuery.toString()}`),
  ]);
  specKitSavedText = constitution.text || "";
  const banner = constitution.banner
    ? `<p class="muted">${escapeHtml(constitution.banner)}</p>`
    : "";
  const runRows = (runsPage.items || []).map((row) => ({
    run_id: escapeHtml(row.run_id || ""),
    command: escapeHtml(row.command || ""),
    status: escapeHtml(row.status || ""),
    issue_id: escapeHtml(row.issue_id || ""),
    improve_job_id: escapeHtml(row.improve_job_id || row.job_id || ""),
    started_at: escapeHtml(row.started_at || ""),
  }));
  const integration = options.integration || "copilot";
  return `
    <p class="muted">Constitution canonical path <code>evolution/spec-kit/CONSTITUTION.md</code>; runtime may mirror under <code>.sevn/spec-kit/</code>.</p>
    <h3>Constitution</h3>
    ${banner}
    <p class="muted">Source: <code>${escapeHtml(constitution.source || "")}</code> · path: <code>${escapeHtml(constitution.path || "")}</code></p>
    <p id="spec-kit-dirty" class="muted" hidden></p>
    <textarea id="spec-kit-constitution" rows="14" style="width:100%;font-family:monospace;">${escapeHtml(specKitSavedText)}</textarea>
    <p>
      <button type="button" class="btn btn-primary btn-sm" id="spec-kit-save">Save</button>
      <button type="button" class="btn btn-sm" id="spec-kit-reset">Reset to template</button>
    </p>
    <h3>Options</h3>
    <form id="spec-kit-options" class="form-grid">
      <label><input type="checkbox" name="spec_kit_enabled" ${options.spec_kit_enabled ? "checked" : ""}> spec_kit.enabled</label>
      <label><input type="checkbox" name="my_sevn_bugs_use_spec_kit" ${options.my_sevn_bugs_use_spec_kit ? "checked" : ""}> my_sevn.bugs.use_spec_kit</label>
      <label><input type="checkbox" name="self_improve_spec_kit_enabled" ${options.self_improve_spec_kit_enabled ? "checked" : ""}> self_improve.spec_kit.enabled</label>
      <label><input type="checkbox" name="self_improve_spec_kit_require_plan_before_patch" ${options.self_improve_spec_kit_require_plan_before_patch ? "checked" : ""}> self_improve.spec_kit.require_plan_before_patch</label>
      <label><input type="checkbox" name="self_improve_spec_kit_require_hitl_for_plan" ${options.self_improve_spec_kit_require_hitl_for_plan ? "checked" : ""}> self_improve.spec_kit.require_hitl_for_plan</label>
      <label><input type="checkbox" name="dry_run_default" ${options.dry_run_default ? "checked" : ""}> spec_kit.options.dry_run_default</label>
      <label>integration
        <select name="integration">
          <option value="copilot" ${integration === "copilot" ? "selected" : ""}>copilot</option>
          <option value="claude" ${integration === "claude" ? "selected" : ""}>claude</option>
        </select>
      </label>
      <p><button type="button" class="btn btn-primary btn-sm" id="spec-kit-options-save">Save options</button></p>
    </form>
    <h3>Runs</h3>
    ${filterJobId || filterIssueId
      ? `<p class="muted">Filtered runs${filterJobId ? ` · job <code>${escapeHtml(filterJobId)}</code>` : ""}${filterIssueId ? ` · issue <code>${escapeHtml(filterIssueId)}</code>` : ""} · <a href="/mission/spec-kit">Show all</a></p>`
      : ""}
    ${tableFromRows(runRows, [
      { key: "run_id", label: "Run" },
      { key: "command", label: "Command" },
      { key: "status", label: "Status" },
      { key: "issue_id", label: "Issue" },
      { key: "improve_job_id", label: "Job" },
      { key: "started_at", label: "Started" },
    ])}
    <h3>Test invoke</h3>
    <p class="muted">Dry-run <code>speckit.plan</code> (allowlisted subprocess only).</p>
    <p>
      <button type="button" class="btn btn-sm" id="spec-kit-test-plan">Dry-run plan</button>
      <span id="spec-kit-test-result" class="muted"></span>
    </p>
  `;
}

function bindSpecKitHandlers() {
  const textarea = document.querySelector("#spec-kit-constitution");
  textarea?.addEventListener("input", specKitMarkDirty);
  document.querySelector("#spec-kit-save")?.addEventListener("click", async () => {
    const body = document.querySelector("#spec-kit-constitution")?.value ?? "";
    try {
      const saved = await apiPut("/api/v1/spec-kit/constitution", { text: body });
      specKitSavedText = saved.text || body;
      specKitMarkDirty();
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
  document.querySelector("#spec-kit-reset")?.addEventListener("click", async () => {
    try {
      const tpl = await apiGet("/api/v1/spec-kit/constitution/template");
      const textareaEl = document.querySelector("#spec-kit-constitution");
      if (textareaEl) textareaEl.value = tpl.text || "";
      specKitMarkDirty();
    } catch (err) {
      alert(err.message);
    }
  });
  document.querySelector("#spec-kit-options-save")?.addEventListener("click", async () => {
    const form = document.querySelector("#spec-kit-options");
    if (!form) return;
    const patch = {
      spec_kit_enabled: form.querySelector('[name="spec_kit_enabled"]')?.checked ?? false,
      my_sevn_bugs_use_spec_kit: form.querySelector('[name="my_sevn_bugs_use_spec_kit"]')?.checked ?? false,
      self_improve_spec_kit_enabled: form.querySelector('[name="self_improve_spec_kit_enabled"]')?.checked ?? false,
      self_improve_spec_kit_require_plan_before_patch:
        form.querySelector('[name="self_improve_spec_kit_require_plan_before_patch"]')?.checked ?? false,
      self_improve_spec_kit_require_hitl_for_plan:
        form.querySelector('[name="self_improve_spec_kit_require_hitl_for_plan"]')?.checked ?? false,
      dry_run_default: form.querySelector('[name="dry_run_default"]')?.checked ?? false,
      integration: form.querySelector('[name="integration"]')?.value || "copilot",
    };
    try {
      await apiPut("/api/v1/spec-kit/options", patch);
      await renderContent();
    } catch (err) {
      alert(err.message);
    }
  });
  document.querySelector("#spec-kit-test-plan")?.addEventListener("click", async () => {
    const resultEl = document.querySelector("#spec-kit-test-result");
    const jobId = new URLSearchParams(location.search).get("job_id") || null;
    try {
      const resp = await apiPost("/api/v1/spec-kit/test-invoke", {
        command: "plan",
        argv: [],
        job_id: jobId,
        dry_run: true,
      });
      if (resultEl) {
        resultEl.textContent = `${resp.status} · ${resp.detail || resp.stdout || ""}`.slice(0, 200);
      }
      await renderContent();
    } catch (err) {
      if (resultEl) resultEl.textContent = err.message;
    }
  });
  specKitMarkDirty();
}

function bindEvolutionHandlers(tabSlug) {
  if (tabSlug === "issues") {
    // Import-from-GitHub by number
    const importBtn = content.querySelector("#gh-import-btn");
    if (importBtn) {
      importBtn.addEventListener("click", async () => {
        const numEl = content.querySelector("#gh-import-number");
        const num = numEl ? parseInt(numEl.value, 10) : NaN;
        if (!num || isNaN(num)) { alert("Enter a GitHub issue number."); return; }
        try {
          await apiPost("/api/v1/evolution/issues/import", { number: num });
          await renderContent();
        } catch (err) {
          alert(err.message);
        }
      });
    }
    // Sync now
    const syncBtn = content.querySelector("#gh-sync-btn");
    if (syncBtn) {
      syncBtn.addEventListener("click", async () => {
        try {
          await apiPost("/api/v1/evolution/issues/sync", { state: "open" });
          await renderContent();
        } catch (err) {
          alert(err.message);
        }
      });
    }
    // Run pipeline form — activated by per-row "Run" button
    let _runIssueId = "";
    content.querySelectorAll(".issue-run-pipeline").forEach((btn) => {
      btn.addEventListener("click", () => {
        _runIssueId = btn.getAttribute("data-issue-id") || "";
        const form = content.querySelector("#issues-run-form");
        const title = content.querySelector("#issues-run-form-title");
        if (form) form.style.display = "";
        if (title) title.textContent = `Run pipeline for ${_runIssueId}`;
      });
    });
    const runSubmitBtn = content.querySelector("#run-submit-btn");
    if (runSubmitBtn) {
      runSubmitBtn.addEventListener("click", async () => {
        if (!_runIssueId) return;
        const stage = (content.querySelector("#run-stage") || {}).value || "auto";
        const executorEl = content.querySelector("#run-executor");
        const executor = executorEl && executorEl.value ? executorEl.value : null;
        const live = !!(content.querySelector("#run-live") || {}).checked;
        try {
          await apiPost(`/api/v1/evolution/pipelines/${encodeURIComponent(_runIssueId)}/run`, {
            stage,
            ...(executor ? { executor } : {}),
            live,
          });
          await renderContent();
        } catch (err) {
          alert(err.message);
        }
      });
    }
    const runCancelBtn = content.querySelector("#run-cancel-btn");
    if (runCancelBtn) {
      runCancelBtn.addEventListener("click", () => {
        const form = content.querySelector("#issues-run-form");
        if (form) form.style.display = "none";
        _runIssueId = "";
      });
    }
  }
  if (tabSlug === "pipelines") {
    // Run (auto stage, no executor override, non-live by default)
    content.querySelectorAll(".pipeline-run").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const issueId = btn.getAttribute("data-issue-id");
        if (!issueId) return;
        try {
          await apiPost(`/api/v1/evolution/pipelines/${encodeURIComponent(issueId)}/run`, { stage: "auto" });
          await renderContent();
        } catch (err) {
          alert(err.message);
        }
      });
    });
    // Poll (Cursor Cloud manual refresh)
    content.querySelectorAll(".pipeline-poll").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const issueId = btn.getAttribute("data-issue-id");
        if (!issueId) return;
        try {
          await apiPost(`/api/v1/evolution/pipelines/${encodeURIComponent(issueId)}/poll`);
          await renderContent();
        } catch (err) {
          alert(err.message);
        }
      });
    });
    // Kill
    content.querySelectorAll(".pipeline-kill").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const issueId = btn.getAttribute("data-issue-id");
        if (!issueId) return;
        try {
          await apiPost(`/api/v1/evolution/pipelines/${encodeURIComponent(issueId)}/kill`);
          await renderContent();
        } catch (err) {
          alert(err.message);
        }
      });
    });
  }
  if (tabSlug === "approvals") {
    content.querySelectorAll(".approval-approve").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        if (!id) return;
        try {
          await apiPost(`/api/v1/evolution/approvals/${encodeURIComponent(id)}/approve`);
          await renderContent();
        } catch (err) {
          alert(err.message);
        }
      });
    });
    content.querySelectorAll(".approval-reject").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        if (!id) return;
        try {
          await apiPost(`/api/v1/evolution/approvals/${encodeURIComponent(id)}/reject`);
          await renderContent();
        } catch (err) {
          alert(err.message);
        }
      });
    });
  }
}

async function renderWiredTab(tab) {
  const sessionId = sessionApiCallsPath();
  if (sessionId) {
    return renderSessionApiCalls(sessionId);
  }
  const tabSlug = slug(tab.name);
  if (tabSlug === "overview") return renderOverview();
  if (tabSlug === "chat") return renderChat();
  if (tabSlug === "canvas-openui") return renderCanvas();
  if (tabSlug === "sessions") return renderSessions();
  if (tabSlug === "traces") return renderTraces();
  if (tabSlug === "audit-analytics") return renderAuditAnalytics();
  if (tabSlug === "budget-cost") return renderBudget();
    if (tabSlug === "providers-llms") return renderProviders();
  if (tabSlug === "channels") return renderChannels();
  if (tabSlug === "sub-agents") return renderSubagents();
  if (tabSlug === "alerts-logs") return renderAlertsLogs();
  if (tabSlug === "jobs") return renderJobs();
  if (tabSlug === "trajectories") return renderTrajectories();
  if (tabSlug === "feedback") return renderFeedback();
  if (tabSlug === "rlm-training") return renderRlmConfig();
  if (tabSlug === "experiments-metrics") return renderExperimentsMetrics();
  if (tabSlug === "issues") return renderEvolutionIssues();
  if (tabSlug === "pipelines") return renderEvolutionPipelines();
  if (tabSlug === "approvals") return renderEvolutionApprovals();
  if (tabSlug === "evolution-traces") return renderEvolutionTraces();
  if (tabSlug === "stats") return renderEvolutionStats();
  if (tabSlug === "spec-kit") return renderSpecKit();
  if (tabSlug === "cron") return renderCron();
  if (tabSlug === "security") return renderSecurity();
  if (tabSlug === "secrets") return renderSecrets();
  if (tabSlug === "egress-proxy") return renderEgressProxy();
  if (tabSlug === "tunnels-infra") return renderTunnelsInfra();
  if (tabSlug === "backup-snapshots") return renderBackupSnapshots();
  if (tabSlug === "config") return renderConfig();
  if (tabSlug === "schema-ontology") return renderSchemaOntology();
  if (tabSlug === "sevn-cli") return renderSevnCli();
  if (tabSlug === "terminal") return renderTerminal();
  if (tabSlug === "memory") return renderMemory();
  if (tabSlug === "second-brain") return renderSecondBrain();
  if (tabSlug === "workspace-files") return renderWorkspaceFiles();
  if (tabSlug === "code-understanding") return renderCodeUnderstanding();
  if (tabSlug === "tools-permissions") return renderToolsPermissions();
  if (tabSlug === "skills") return renderSkills();
  if (tabSlug === "mcp-servers") return renderMcpServers();
  if (tabSlug === "coding-agents") return renderCodingAgents();
  if (tabSlug === "agent-config") return renderAgentConfig();
  if (tabSlug === "model-params") return renderModelParams();
  if (tabSlug === "telegram-menu") return renderTelegramMenu();
  if (tabSlug === "web-apps") return renderWebApps();
  if (tabSlug === "onboarding") return renderOnboarding();
  if (tabSlug === "users-rbac") return renderUsersRbac();
  return `<p class="muted">Tab not wired.</p>`;
}

function renderStub(tab) {
  const tabSlug = slug(tab.name);
  if (postV1Slugs.has(tabSlug)) {
    return `<article class="card post-v1-panel">
      <h3>Claude Agent (post-v1)</h3>
      <p>Dedicated Telegram topic / Claude Code runner is <strong>not shipped in v1</strong>. This tab reserves the Mission Control surface only.</p>
      <ul>
        <li>Planned post-v1: dedicated Telegram topic and Claude Code runner (not in v0.0.x).</li>
        <li>Config hooks: <code>telegram.claude_agent_topic_id</code> + <code>claude_agent</code> permission template (empty tools/skills/MCP).</li>
      </ul>
      <p class="muted">v1 coding uses tier-C executor (DSPy / λ-RLM). No Triager bypass or inner Claude runner until post-v1.</p>
    </article>`;
  }
  return `<p>This tab is not wired in the current build. JSON APIs live under <code>/api/v1</code>; live updates use <code>/ws/dashboard</code>.</p>
      <p class="muted">Check the product roadmap for when this surface ships.</p>`;
}

async function renderContent() {
  const tab = resolveActiveTab();
  const sessionId = sessionApiCallsPath();
  const tabSlug = sessionId ? "sessions" : slug(tab.name);
  const wired = wiredSlugs.has(tabSlug) || sessionId;
  content.innerHTML = `
    <article class="card">
      <p class="muted">${tab.group}</p>
      <h2>${sessionId ? `Session ${sessionId} API calls` : tab.name}</h2>
      <p class="muted">Loading…</p>
    </article>
  `;
  try {
    const body = wired ? await renderWiredTab(tab) : renderStub(tab);
    content.querySelector("article").innerHTML = `
      <p class="muted">${tab.group}</p>
      <h2>${sessionId ? `Session ${sessionId} API calls` : tab.name}</h2>
      ${body}
    `;
    if (tabSlug === "traces") {
      bindTraceTabHandlers();
    }
    if (tabSlug === "alerts-logs") {
      bindAlertsLogsHandlers();
    }
    if (tabSlug === "jobs") {
      bindJobsHandlers();
    }
    if (["issues", "pipelines", "approvals"].includes(tabSlug)) {
      bindEvolutionHandlers(tabSlug);
      syncEvolutionWsSubscriptions(evolutionWsIssueIds);
    } else {
      evolutionWsIssueIds = [];
      syncEvolutionWsSubscriptions([]);
    }
    if (tabSlug === "spec-kit") {
      bindSpecKitHandlers();
    }
    if (tabSlug === "security") {
      bindSecurityHandlers();
    }
    if (tabSlug === "egress-proxy") {
      bindEgressProxyHandlers();
    }
    if (tabSlug === "config") {
      bindConfigHandlers();
    }
    if (tabSlug === "skills") {
      bindSkillsHandlers();
    }
    if (tabSlug === "agent-config") {
      bindAgentConfigHandlers();
    }
    if (tabSlug === "model-params") {
      bindModelParamsHandlers();
    }
    if (tabSlug === "channels") {
      bindChannelsHandlers();
    }
    if (tabSlug === "sub-agents") {
      bindSubagentsHandlers();
    }
    if (tabSlug === "tunnels-infra") {
      bindTunnelsInfraHandlers();
    }
    if (tabSlug === "backup-snapshots") {
      bindBackupSnapshotsHandlers();
    }
    if (tabSlug === "cron") {
      bindCronHandlers();
    }
    if (tabSlug === "providers-llms") {
      bindProvidersHandlers();
    }
    if (tabSlug === "tools-permissions") {
      bindToolsPermissionsHandlers();
    }
    if (tabSlug === "mcp-servers") {
      bindMcpServersHandlers();
    }
    if (tabSlug === "coding-agents") {
      bindCodingAgentsHandlers();
    }
    if (tabSlug === "telegram-menu") {
      bindTelegramMenuHandlers();
    }
    if (tabSlug === "web-apps") {
      bindWebAppsHandlers();
    }
    if (["workspace-files", "memory", "second-brain"].includes(tabSlug)) {
      bindFileEditorHandlers();
    }
    if (tabSlug === "secrets") {
      bindSecretsHandlers();
    }
    if (tabSlug === "sevn-cli") {
      bindSevnCliHandlers();
    }
    if (tabSlug === "chat") {
      bindChatHandlers();
    } else {
      disconnectChatConsole();
    }
    if (tabSlug === "terminal") {
      bindTerminalHandlers();
    } else {
      disconnectTerminal();
    }
  } catch (err) {
    content.querySelector("article").innerHTML = `
      <p class="muted">${tab.group}</p>
      <h2>${tab.name}</h2>
      <p class="error">Sign in via <code>POST /api/v1/auth/login</code> to load live data. (${err.message})</p>
    `;
  }
}

async function runGlobalSearch() {
  const q = (searchInput?.value || "").trim();
  if (!q) return;
  const page = await apiGet(`/api/v1/search?q=${encodeURIComponent(q)}&limit=25`);
  content.innerHTML = `
    <article class="card">
      <h2>Search: ${q}</h2>
      ${tableFromRows(page.items || [], [
        { key: "kind", label: "Kind" },
        { key: "session_id", label: "Session" },
        { key: "span_id", label: "Span" },
        { key: "status", label: "Status" },
      ])}
    </article>
  `;
}

searchInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    runGlobalSearch().catch((err) => {
      content.innerHTML = `<article class="card"><p class="error">Search failed: ${err.message}</p></article>`;
    });
  }
});

function updateProxyHealthBadge(payload) {
  if (!proxyHealthBadge) return;
  const configured = Boolean(payload?.configured);
  const ok = Boolean(payload?.ok);
  if (!configured) {
    proxyHealthBadge.textContent = "Proxy off";
    proxyHealthBadge.className = "badge badge-muted";
    return;
  }
  proxyHealthBadge.textContent = ok ? "Proxy up" : "Proxy down";
  proxyHealthBadge.className = ok ? "badge badge-success" : "badge badge-warning";
}

function updateProviderHealthBadge(payload) {
  if (!providerHealthBadge) return;
  const providers = Array.isArray(payload?.providers) ? payload.providers : [];
  if (!providers.length && payload?.id) {
    providerHealthBadge.textContent = payload.ok ? "Providers ok" : "Provider degraded";
    providerHealthBadge.className = payload.ok ? "badge badge-success" : "badge badge-warning";
    return;
  }
  const degraded = providers.filter((row) => !row.ok).length;
  if (!providers.length) {
    providerHealthBadge.textContent = "Providers …";
    providerHealthBadge.className = "badge badge-muted";
    return;
  }
  if (degraded === 0) {
    providerHealthBadge.textContent = "Providers ok";
    providerHealthBadge.className = "badge badge-success";
  } else {
    providerHealthBadge.textContent = `${degraded} degraded`;
    providerHealthBadge.className = "badge badge-warning";
  }
}

async function refreshHealthBadges() {
  try {
    updateProxyHealthBadge(await apiGet("/api/v1/proxy/status"));
  } catch (_err) {
    /* badges stay at last WS/REST value */
  }
  try {
    const health = await apiGet("/api/v1/providers/health");
    updateProviderHealthBadge(health);
  } catch (_err) {
    /* ignore */
  }
}

function dashboardWsUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/dashboard`;
}

const DASHBOARD_WS_HEALTH_TOPICS = ["provider.health", "proxy.health", "budget.alert", "mission.file", "mission.secrets", "mission.ops", "mission.approval.pending", "mission.approval.resolved"];

function scheduleEvolutionTabRefresh() {
  if (evolutionWsRefreshTimer) return;
  evolutionWsRefreshTimer = window.setTimeout(() => {
    evolutionWsRefreshTimer = null;
    const tabSlug = slug(resolveActiveTab().name);
    if (tabSlug === "pipelines" || tabSlug === "approvals") {
      renderContent().catch(() => {});
    }
  }, 250);
}

function dashboardWsSubscribe(extraTopics = []) {
  if (!dashboardWs || dashboardWs.readyState !== WebSocket.OPEN) return;
  const topics = [...DASHBOARD_WS_HEALTH_TOPICS];
  for (const topic of extraTopics) {
    if (topic && !topics.includes(topic)) topics.push(topic);
  }
  dashboardWs.send(JSON.stringify({ type: "subscribe", topics }));
}

function syncEvolutionWsSubscriptions(issueIds) {
  const tabSlug = slug(resolveActiveTab().name);
  if (tabSlug !== "pipelines" && tabSlug !== "approvals") {
    dashboardWsSubscribe([]);
    return;
  }
  const topics = issueIds.map((id) => evolutionIssueTopic(id)).filter(Boolean);
  dashboardWsSubscribe(topics);
}

function handleDashboardWsEvent(frame) {
  if (frame?.type !== "event") return;
  const topic = frame.topic || "";
  if (topic === "proxy.health") {
    updateProxyHealthBadge(frame.payload || {});
    return;
  }
  if (topic === "provider.health") {
    updateProviderHealthBadge(frame.payload || {});
    return;
  }
  if (topic === "budget.alert") {
    pushLiveActivity(topic, frame.payload || {});
    const tabSlug = slug(resolveActiveTab().name);
    if (tabSlug === "budget-cost") {
      renderContent().catch(() => {});
    }
    return;
  }
  if (topic.startsWith("mission.")) {
    pushLiveActivity(topic, frame.payload || {});
    if (topic === "mission.approval.pending") {
      const payload = frame.payload || {};
      if (payload.decision_id && !pendingToolApprovals.some((row) => row.decision_id === payload.decision_id)) {
        pendingToolApprovals.push({
          decision_id: payload.decision_id,
          tool_name: payload.tool_name,
          args_summary: payload.args_summary,
          session_id: payload.session_id,
          turn_id: payload.turn_id,
        });
        updateApprovalPendingBadge();
        const tabSlug = slug(resolveActiveTab().name);
        if (tabSlug === "tools-permissions") {
          renderContent().catch(() => {});
        }
      }
    }
    if (topic === "mission.approval.resolved") {
      const payload = frame.payload || {};
      if (payload.decision_id) {
        pendingToolApprovals = pendingToolApprovals.filter((row) => row.decision_id !== payload.decision_id);
        updateApprovalPendingBadge();
        const tabSlug = slug(resolveActiveTab().name);
        if (tabSlug === "tools-permissions") {
          renderContent().catch(() => {});
        }
      }
    }
    return;
  }
  if (topic.startsWith("evolution.issue.")) {
    scheduleEvolutionTabRefresh();
  }
}

function connectDashboardHealthWs() {
  if (dashboardWs && (dashboardWs.readyState === WebSocket.OPEN || dashboardWs.readyState === WebSocket.CONNECTING)) {
    return;
  }
  if (authRequired && !localOpen && !dashboardAccessToken) {
    return;
  }
  let ws;
  try {
    ws = new WebSocket(dashboardWsUrl());
  } catch (_err) {
    return;
  }
  dashboardWs = ws;
  ws.addEventListener("open", () => {
    if (authRequired && !localOpen && dashboardAccessToken) {
      ws.send(JSON.stringify({ type: "auth", token: dashboardAccessToken }));
    }
    const tabSlug = slug(resolveActiveTab().name);
    if (tabSlug === "pipelines" || tabSlug === "approvals") {
      syncEvolutionWsSubscriptions(evolutionWsIssueIds);
    } else {
      dashboardWsSubscribe([]);
    }
  });
  ws.addEventListener("message", (event) => {
    let frame;
    try {
      frame = JSON.parse(event.data);
    } catch (_err) {
      return;
    }
    handleDashboardWsEvent(frame);
  });
  ws.addEventListener("close", () => {
    if (dashboardWs === ws) dashboardWs = null;
  });
}

function setSystemMenuOpen(open) {
  if (!systemMenuPanel || !systemMenuToggle) return;
  systemMenuPanel.hidden = !open;
  systemMenuToggle.setAttribute("aria-expanded", open ? "true" : "false");
}

function openCommandPalette() {
  if (!commandPalette || !paletteQuery) return;
  commandPalette.hidden = false;
  paletteQuery.value = searchInput?.value || "";
  paletteResults.innerHTML = renderPaletteNavItems(paletteTabItems().slice(0, 12));
  paletteResults.querySelectorAll("[data-palette-href]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const href = btn.getAttribute("data-palette-href");
      closeCommandPalette();
      if (href) location.href = href;
    });
  });
  paletteQuery.focus();
  paletteQuery.select();
}

function closeCommandPalette() {
  if (commandPalette) commandPalette.hidden = true;
}

async function runPaletteSearch(query) {
  const q = (query || "").trim();
  if (!q || !paletteResults) return;
  paletteResults.innerHTML = "<p class=\"muted\">Searching…</p>";
  const qLower = q.toLowerCase();
  const tabMatches = paletteTabItems().filter(
    (item) => item.label.toLowerCase().includes(qLower) || item.group.toLowerCase().includes(qLower),
  );
  let html = renderPaletteNavItems(tabMatches.slice(0, 8));
  if (qLower.startsWith("config:") || qLower.startsWith("file:")) {
    const configKey = q.slice(q.indexOf(":") + 1).trim();
    if (configKey) {
      html += `<p class="muted">Config</p><button type="button" class="mission-palette-item" data-palette-href="/mission/config">Open Configuration · jump to <code>${escapeHtml(configKey)}</code></button>`;
    }
    if (qLower.startsWith("file:")) {
      const filePath = q.slice(5).trim();
      if (filePath) {
        html += `<button type="button" class="mission-palette-item" data-palette-href="/mission/workspace-files?file=${encodeURIComponent(filePath)}">Open file · ${escapeHtml(filePath)}</button>`;
      }
    }
  } else if (q.length >= 2) {
    const page = await apiGet(`/api/v1/search?q=${encodeURIComponent(q)}&limit=15`);
    const items = page.items || [];
    if (items.length) {
      html += `<p class="muted">Traces</p>${items
        .map((row) => {
          const label = `${row.kind || "span"} · ${row.session_id || ""} · ${row.span_id || ""}`;
          return `<button type="button" class="mission-palette-item" data-palette-href="/mission/traces?span=${encodeURIComponent(row.span_id || "")}">${escapeHtml(label)}</button>`;
        })
        .join("")}`;
    }
  }
  if (!html) {
    paletteResults.innerHTML = "<p class=\"muted\">No results — try a tab name, trace keyword, <code>file:path</code>, or <code>config:key</code>.</p>";
    return;
  }
  paletteResults.innerHTML = html;
  paletteResults.querySelectorAll("[data-palette-href]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const href = btn.getAttribute("data-palette-href");
      closeCommandPalette();
      if (href) location.href = href;
    });
  });
}

function openLogRetentionModal() {
  if (!logRetentionModal) return;
  logRetentionModal.hidden = false;
  if (logRetentionError) {
    logRetentionError.hidden = true;
    logRetentionError.textContent = "";
  }
  apiGet("/api/v1/system/logging")
    .then((cfg) => {
      if (loggingRetentionDays) loggingRetentionDays.value = String(cfg.retention_days ?? 30);
      if (loggingArchiveMode) loggingArchiveMode.value = cfg.archive_mode || "copy";
      if (loggingArchiveDestination) loggingArchiveDestination.value = cfg.archive_destination || "";
    })
    .catch((err) => {
      if (logRetentionError) {
        logRetentionError.hidden = false;
        logRetentionError.textContent = err.message;
      }
    });
}

function closeLogRetentionModal() {
  if (logRetentionModal) logRetentionModal.hidden = true;
}

function bindShellHandlers() {
  systemMenuToggle?.addEventListener("click", (event) => {
    event.stopPropagation();
    const open = systemMenuPanel?.hidden !== false;
    setSystemMenuOpen(open);
  });
  document.addEventListener("click", () => setSystemMenuOpen(false));
  systemMenuPanel?.addEventListener("click", (event) => event.stopPropagation());

  document.querySelector("#system-upgrade")?.addEventListener("click", async () => {
    setSystemMenuOpen(false);
    const consent = window.confirm(
      "Upgrade schema (if needed) and restart the gateway? Active runs will be paused.",
    );
    if (!consent) return;
    try {
      await apiPost("/api/v1/system/upgrade-restart", {
        consent: true,
        apply_schema_upgrade: true,
      });
      window.alert("Upgrade and restart requested. The page may disconnect briefly.");
    } catch (err) {
      window.alert(`Upgrade failed: ${err.message}`);
    }
  });

  document.querySelector("#system-logging")?.addEventListener("click", () => {
    setSystemMenuOpen(false);
    openLogRetentionModal();
  });

  document.querySelector("#system-sign-out")?.addEventListener("click", async () => {
    setSystemMenuOpen(false);
    try {
      await apiPost("/api/v1/auth/logout");
    } catch (_err) {
      /* cookie may already be cleared */
    }
    dashboardAccessToken = null;
    authRequired = true;
    updateAuthChrome();
    if (loginPanel) loginPanel.hidden = false;
    content.innerHTML = "";
    if (dashboardWs) {
      dashboardWs.close();
      dashboardWs = null;
    }
  });

  document.querySelector("#log-retention-cancel")?.addEventListener("click", closeLogRetentionModal);
  logRetentionModal?.addEventListener("click", (event) => {
    if (event.target === logRetentionModal) closeLogRetentionModal();
  });
  logRetentionForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (logRetentionError) {
      logRetentionError.hidden = true;
      logRetentionError.textContent = "";
    }
    try {
      await apiPut("/api/v1/system/logging", {
        retention_days: Number(loggingRetentionDays?.value || 30),
        archive_mode: loggingArchiveMode?.value || "copy",
        archive_destination: loggingArchiveDestination?.value || "",
      });
      closeLogRetentionModal();
    } catch (err) {
      if (logRetentionError) {
        logRetentionError.hidden = false;
        logRetentionError.textContent = err.message;
      }
    }
  });

  commandPalette?.addEventListener("click", (event) => {
    if (event.target === commandPalette) closeCommandPalette();
  });
  paletteQuery?.addEventListener("input", () => {
    const q = paletteQuery.value.trim();
    if (!q) {
      paletteResults.innerHTML = renderPaletteNavItems(paletteTabItems().slice(0, 12));
      paletteResults.querySelectorAll("[data-palette-href]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const href = btn.getAttribute("data-palette-href");
          closeCommandPalette();
          if (href) location.href = href;
        });
      });
      return;
    }
    runPaletteSearch(q).catch((err) => {
      paletteResults.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
    });
  });
  paletteQuery?.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeCommandPalette();
    }
    if (event.key === "Enter") {
      event.preventDefault();
      runPaletteSearch(paletteQuery.value).catch((err) => {
        paletteResults.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
      });
    }
  });

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openCommandPalette();
      return;
    }
    if (event.key === "Escape" && commandPalette && !commandPalette.hidden) {
      closeCommandPalette();
    }
  });
}

if (typeof initSevnTheme === "function") {
  initSevnTheme({ cycleButtonSelector: "#theme" });
}

bindShellHandlers();

loginForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (loginError) {
    loginError.hidden = true;
    loginError.textContent = "";
  }
  try {
    const loginResp = await apiPost("/api/v1/auth/login", { password: loginPassword?.value || "" });
    dashboardAccessToken = loginResp.access_token || null;
    authRequired = false;
    updateAuthChrome();
    renderNav();
    await renderContent();
  } catch (err) {
    if (loginError) {
      loginError.hidden = false;
      loginError.textContent = err.message;
    }
  }
});

async function boot() {
  try {
    await ensureAuthenticated();
    const navPayload = await apiGet("/api/v1/dashboard/nav");
    applyNavPayload(navPayload);
  } catch (err) {
    if (authRequired) {
      renderNav();
      return;
    }
    groups = INLINE_GROUPS;
    wiredSlugs = new Set(INLINE_WIRED_SLUGS);
    postV1Slugs = new Set([]);
    rebuildTabsFromGroups();
  }
  renderNav();
  if (!authRequired) {
    await refreshHealthBadges();
    await refreshPendingToolApprovals();
    connectDashboardHealthWs();
    renderContent();
  }
}

window.addEventListener("popstate", () => {
  renderNav();
  renderContent();
});

boot();
