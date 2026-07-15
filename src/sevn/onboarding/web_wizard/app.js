/* sevn web onboarding wizard */

const BASE_STEPS = [
  "profile",
  "workspace",
  "my_sevn",
  "model",
  "capabilities",
  "channels",
  "secrets",
  "sandbox",
  "tunnel",
  "personality",
  "validate",
  "promote",
  "handoff",
];

let STEPS = [...BASE_STEPS];

const MODEL_SLOT_FIELDS = [
  "providers.tier_default.B",
  "providers.tier_default.C",
  "providers.tier_default.D",
  "providers.tier_default.C.sub_lm",
  "providers.tier_default.D.sub_lm",
  "providers.tier_default.C.lambda_leaf",
  "providers.tier_default.D.lambda_leaf",
  "lcm.summary_model",
  "memory.pre_compaction_flush.model",
  "memory.dreaming.scoring.llm_ranker.model",
  "memory.user_model.extractor_model",
  "security.scanner.model",
];

const MODEL_SLOT_LABELS = {
  "providers.tier_default.B": "Tier B",
  "providers.tier_default.C": "Tier C",
  "providers.tier_default.D": "Tier D",
  "providers.tier_default.C.sub_lm": "C sub-LM",
  "providers.tier_default.D.sub_lm": "D sub-LM",
  "providers.tier_default.C.lambda_leaf": "C λ-leaf",
  "providers.tier_default.D.lambda_leaf": "D λ-leaf",
  "lcm.summary_model": "LCM summary",
  "memory.pre_compaction_flush.model": "Pre-compaction",
  "memory.dreaming.scoring.llm_ranker.model": "Dreaming ranker",
  "memory.user_model.extractor_model": "User-model extractor",
  "security.scanner.model": "Scanner",
};

const STEP_LABELS = {
  profile: "Profile",
  workspace: "Workspace",
  my_sevn: "My Sevn.bot",
  model: "Main model",
  capabilities: "Capabilities",
  channels: "Channels",
  secrets: "Secrets",
  sandbox: "Sandbox",
  tunnel: "Public access",
  personality: "Personality",
  validate: "Validate",
  promote: "Promote",
  handoff: "Handoff",
  existing: "Existing install",
};

const SUMMARY_FIELDS = [
  { id: "agent.display_name", label: "Bot name", required: true },
  { id: "my_sevn.repo_url", label: "Repository URL", required: true },
  { id: "my_sevn.workspace_backup.repo_url", label: "Workspace backup repo" },
  { id: "my_sevn.sync.enabled", label: "Daily repo sync" },
  { id: "self_improve.enabled", label: "Self-improve" },
  { id: "self_improve.hub.use_github", label: "Self-improve via GitHub" },
  { id: "workspace_root", label: "Workspace root", required: true },
  { id: "providers.tier_default.triager", label: "Main model (triager)", required: true },
  { id: "wizard.telegram_bot_token", label: "Telegram bot token", secret: true, required: true },
  { id: "wizard.telegram_owner_user_id", label: "Telegram owner user id", required: true },
  { id: "channels.telegram.bot_token_ref", label: "Token ref in sevn.json" },
  { id: "infrastructure.tunnel.mode", label: "Public access" },
  { id: "secrets_backend.type", label: "Secrets backend" },
  {
    id: "wizard.secrets_passphrase",
    label: "Secrets passphrase",
    secret: true,
    required: true,
    requiredWhen: () => {
      const sb = document.querySelector('[data-field-id="secrets_backend.type"]');
      return !sb || sb.value === "encrypted_file";
    },
  },
];

const STEP_REQUIRED = {
  profile: [],
  workspace: ["workspace_root", "gateway.host", "gateway.port", "wizard.gateway_token"],
  my_sevn: ["agent.display_name", "my_sevn.repo_url"],
  model: ["providers.tier_default.triager"],
  capabilities: ["gateway.queue_mode"],
  channels: ["wizard.telegram_bot_token", "wizard.telegram_owner_user_id"],
  secrets: ["secrets_backend.type", "wizard.secrets_passphrase"],
  sandbox: [],
  tunnel: ["infrastructure.tunnel.mode"],
  personality: [],
  validate: [],
  promote: [],
  handoff: [],
};

let meta = null;
let fieldHelp = {};
let capabilitiesData = null;
let lastAppliedConfig = {};
let currentStep = 0;
let selectedProfile = "skip";
let credentialsReady = false;
let installGate = null;
let selectedInstallHome = null;
let reuseMode = false;
let freshInstall = true;
let hasKeystore = false;
let configSaved = false;
let validationPassed = false;
let installRunComplete = false;
let fatalInstallFailed = false;
let installPlanData = null;

async function api(path, options = {}) {
  const url = path.startsWith("/") ? path.slice(1) : path;
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await res.json().catch(() => ({}));
  return { res, body };
}

function updateProgress() {
  const fill = document.getElementById("progressFill");
  const label = document.getElementById("progressLabel");
  const pct = ((currentStep + 1) / STEPS.length) * 100;
  if (fill) fill.style.width = `${pct}%`;
  if (label) {
    label.textContent = `step ${String(currentStep + 1).padStart(2, "0")} / ${String(STEPS.length).padStart(2, "0")}`;
  }
}

function updatePageHead() {
  const stepId = STEPS[currentStep];
  const section = document.querySelector(`.wizard-step[data-step="${stepId}"]`);
  if (!section) return;
  const crumb = section.querySelector(".wizard-crumb");
  if (crumb) {
    crumb.textContent = `${String(currentStep + 1).padStart(2, "0")} · ${stepId}`;
  }
}

function updateNavButtons() {
  const stepId = STEPS[currentStep];
  const isHandoff = stepId === "handoff";
  const btnNext = document.getElementById("btn-next");
  const btnExit = document.getElementById("btn-exit");
  if (btnNext) btnNext.hidden = isHandoff;
  if (btnExit) {
    btnExit.hidden = false;
    btnExit.textContent = isHandoff && configSaved ? "Finish" : "Exit";
  }
  const btnRunGateway = document.getElementById("btn-run-gateway");
  if (btnRunGateway) {
    btnRunGateway.textContent = configSaved ? "Restart gateway" : "Run gateway";
  }
}

async function finishOnboarding() {
  if (document.body.dataset.onboardingExited === "1") return;
  document.body.dataset.onboardingExited = "1";
  try {
    await api("/api/shutdown", { method: "POST", body: "{}" });
  } catch (_e) {
    /* server may already be gone */
  }
  document.open();
  document.write("<!DOCTYPE html><html><head><title></title></head><body></body></html>");
  document.close();
  try {
    window.close();
  } catch (_e) {
    /* browsers block close for user-opened tabs */
  }
}

async function cancelOnboarding() {
  if (document.body.dataset.onboardingExited === "1") return;
  document.body.dataset.onboardingExited = "1";
  try {
    await api("/api/shutdown", { method: "POST", body: "{}" });
  } catch (_e) {
    /* server may already be gone */
  }
  document.open();
  document.write(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>sevn.bot · setup ended</title>
  <style>
    body { font-family: system-ui, sans-serif; display: flex; align-items: center; justify-content: center;
      min-height: 100vh; margin: 0; background: #0a0a0a; color: #eee; text-align: center; padding: 24px; }
    p { color: #aaa; max-width: 420px; line-height: 1.5; }
  </style>
</head>
<body>
  <div>
    <h1>Setup ended</h1>
    <p>The onboarding server has stopped. You can close this tab.</p>
  </div>
</body>
</html>`);
  document.close();
  try {
    window.close();
  } catch (_e) {
    /* browsers block close for user-opened tabs */
  }
}

function showExitConfirm() {
  const modal = document.getElementById("exit-confirm-modal");
  if (modal) modal.hidden = false;
}

function hideExitConfirm() {
  const modal = document.getElementById("exit-confirm-modal");
  if (modal) modal.hidden = true;
}

function confirmExit() {
  showExitConfirm();
}

function wireExitConfirmUi() {
  document.getElementById("btn-exit")?.addEventListener("click", () => {
    if (STEPS[currentStep] === "handoff" && configSaved) {
      finishOnboarding();
      return;
    }
    confirmExit();
  });
  document.getElementById("btn-profile-exit")?.addEventListener("click", confirmExit);
  document.getElementById("btn-exit-cancel")?.addEventListener("click", hideExitConfirm);
  document.getElementById("btn-exit-proceed")?.addEventListener("click", () => {
    hideExitConfirm();
    cancelOnboarding();
  });
  document.getElementById("exit-confirm-modal")?.addEventListener("click", (ev) => {
    if (ev.target?.classList?.contains("wizard-modal-backdrop")) hideExitConfirm();
  });
}

function shouldPrefillFromExisting(body) {
  if (!body || typeof body !== "object") return false;
  if (body.gate_required) return false;
  if (body.should_prefill_secrets !== undefined) {
    return Boolean(body.should_prefill_secrets);
  }
  return Boolean(body.reuse || body.exists);
}

function providerSecretEnvKey(name) {
  return `SEVN_SECRET_${name.toUpperCase()}`;
}

function clearWizardCredentialFields() {
  for (const id of [
    "tg_bot_token",
    "tg_api_id",
    "tg_api_hash",
    "tg_phone",
    "secrets_passphrase",
    "secrets_passphrase_confirm",
  ]) {
    const el = document.getElementById(id);
    if (el) el.value = "";
  }
  document.querySelectorAll(".provider-api-key-input").forEach((el) => {
    el.value = "";
  });
  renderFieldSummary();
}

function applySecretsToForm(secrets) {
  if (!secrets || typeof secrets !== "object") return;
  const map = {
    SEVN_TELEGRAM_BOT_TOKEN: "tg_bot_token",
    SEVN_TELEGRAM_API_ID: "tg_api_id",
    SEVN_TELEGRAM_API_HASH: "tg_api_hash",
    SEVN_TELEGRAM_PHONE: "tg_phone",
  };
  for (const [envKey, elId] of Object.entries(map)) {
    const val = secrets[envKey];
    const el = document.getElementById(elId);
    if (el && val) el.value = val;
  }
  updateProviderKeyFields();
  for (const [key, val] of Object.entries(secrets)) {
    if (!key.startsWith("SEVN_SECRET_") || !val) continue;
    const suffix = key.slice("SEVN_SECRET_".length).toLowerCase();
    const el = document.querySelector(`[data-field-id="wizard.provider_api_key.${suffix}"]`);
    if (el) el.value = val;
  }
  for (const [key, val] of Object.entries(secrets)) {
    if (!key.startsWith("providers.") || !key.endsWith(".api_key") || !val) continue;
    const name = key.slice("providers.".length, -".api_key".length);
    const el = document.querySelector(`[data-field-id="wizard.provider_api_key.${name}"]`);
    if (el) el.value = val;
  }
  const pass = secrets.SEVN_SECRETS_PASSPHRASE;
  if (pass) {
    const passEl = document.getElementById("secrets_passphrase");
    const confirmEl = document.getElementById("secrets_passphrase_confirm");
    if (passEl) passEl.value = pass;
    if (confirmEl) confirmEl.value = pass;
  }
  renderFieldSummary();
}

const PASSPHRASE_MAX_ATTEMPTS = 3;

async function verifyPassphrase(passphrase) {
  const { res, body } = await api("/api/verify-passphrase", {
    method: "POST",
    body: JSON.stringify({ passphrase }),
  });
  if (res.ok) return { ok: true };
  return { ok: false, message: body.detail || "Incorrect passphrase" };
}

async function verifyPassphraseWithRetries(passphrase) {
  for (let attempt = 1; attempt <= PASSPHRASE_MAX_ATTEMPTS; attempt += 1) {
    const result = await verifyPassphrase(passphrase);
    if (result.ok) return result;
    const remaining = PASSPHRASE_MAX_ATTEMPTS - attempt;
    if (remaining <= 0) {
      return {
        ok: false,
        message: `${result.message}. No attempts remaining.`,
      };
    }
    const retry = window.prompt(
      `${result.message}\n\nEnter the correct passphrase (${remaining} attempt${
        remaining === 1 ? "" : "s"
      } left):`,
      "",
    );
    if (retry === null) {
      return { ok: false, message: "Passphrase verification cancelled." };
    }
    passphrase = retry;
  }
  return { ok: false, message: "Incorrect passphrase" };
}

function promptUnlockKeystore() {
  return new Promise((resolve) => {
    const modal = document.getElementById("unlock-keystore-modal");
    const input = document.getElementById("unlock-keystore-input");
    const err = document.getElementById("unlock-keystore-error");
    if (!modal) {
      resolve(false);
      return;
    }
    modal.hidden = false;
    if (input) {
      input.value = "";
      input.focus();
    }
    if (err) err.textContent = "";

    const onCancel = () => {
      modal.hidden = true;
      btnCancel?.removeEventListener("click", onCancel);
      btnProceed?.removeEventListener("click", onProceed);
      resolve(false);
    };

    const btnCancel = document.getElementById("btn-unlock-cancel");
    const btnProceed = document.getElementById("btn-unlock-proceed");
    let attemptsLeft = PASSPHRASE_MAX_ATTEMPTS;

    async function onProceed() {
      const passphrase = input?.value || "";
      const { res, body } = await api("/api/unlock-keystore", {
        method: "POST",
        body: JSON.stringify({ passphrase }),
      });
      if (!res.ok) {
        attemptsLeft -= 1;
        if (attemptsLeft <= 0) {
          if (err) err.textContent = `${body.detail || "Incorrect passphrase"} — no attempts remaining.`;
          btnProceed?.setAttribute("disabled", "disabled");
          return;
        }
        if (err) {
          err.textContent = `${body.detail || "Incorrect passphrase"} (${attemptsLeft} attempt${
            attemptsLeft === 1 ? "" : "s"
          } left)`;
        }
        if (input) {
          input.value = "";
          input.focus();
        }
        return;
      }
      applySecretsToForm(body.secrets || {});
      modal.hidden = true;
      btnCancel?.removeEventListener("click", onCancel);
      btnProceed?.removeEventListener("click", onProceed);
      resolve(true);
    }

    btnCancel?.addEventListener("click", onCancel);
    btnProceed?.addEventListener("click", onProceed);
  });
}

async function ensureKeystoreUnlocked(existingBody) {
  if (!shouldPrefillFromExisting(existingBody)) {
    clearWizardCredentialFields();
    return true;
  }
  if (existingBody?.wizard_secrets && Object.keys(existingBody.wizard_secrets).length) {
    applySecretsToForm(existingBody.wizard_secrets);
  }
  if (!existingBody?.needs_passphrase) return true;
  const unlocked = await promptUnlockKeystore();
  return unlocked;
}

function isUseMainModelForAll() {
  const el = document.getElementById("use_main_model_for_all");
  if (!el) return true;
  return el.checked;
}

function providerNameFromModelId(modelId) {
  const text = String(modelId || "").trim();
  if (!text) return null;
  const slash = text.indexOf("/");
  if (slash > 0) return text.slice(0, slash);
  return "openai";
}

function collectAssignedModelIds() {
  const ids = [];
  const main = fieldValue("providers.tier_default.triager");
  const mainText = main !== undefined && main !== null ? String(main).trim() : "";
  if (isUseMainModelForAll()) {
    if (mainText) ids.push(mainText);
    return ids;
  }
  if (mainText) ids.push(mainText);
  for (const fieldId of MODEL_SLOT_FIELDS) {
    const v = fieldValue(fieldId);
    if (v !== undefined && v !== null && String(v).trim()) ids.push(String(v).trim());
  }
  return ids;
}

function collectAssignedProviderNames() {
  const names = new Set();
  for (const mid of collectAssignedModelIds()) {
    const p = providerNameFromModelId(mid);
    if (p) names.add(p);
  }
  return [...names].sort();
}

function updateProviderKeyFields() {
  const providers = collectAssignedProviderNames();
  const multiWrap = document.getElementById("provider-api-keys-multi");
  const list = document.getElementById("provider-api-keys-list");
  const openaiOauthPanel = document.getElementById("openai-oauth-panel");
  if (multiWrap) multiWrap.hidden = providers.length === 0;
  if (openaiOauthPanel) openaiOauthPanel.hidden = !providers.includes("openai");
  if (!list) return;
  const existing = new Map();
  list.querySelectorAll("[data-provider-name]").forEach((el) => {
    existing.set(el.dataset.providerName, el.value);
  });
  list.innerHTML = "";
  for (const name of providers) {
    const row = document.createElement("div");
    row.className = "field";
    row.style.marginTop = "8px";
    const label = document.createElement("label");
    label.setAttribute("for", `provider_api_key_${name}`);
    label.textContent = `${name} API key`;
    const input = document.createElement("input");
    input.type = "password";
    input.className = "input provider-api-key-input";
    input.id = `provider_api_key_${name}`;
    input.dataset.fieldId = `wizard.provider_api_key.${name}`;
    input.dataset.providerName = name;
    input.autocomplete = "off";
    input.required = name !== "openai";
    const prev = existing.get(name);
    if (prev) input.value = prev;
    const err = document.createElement("span");
    err.className = "err";
    row.append(label, input, err);
    list.appendChild(row);
    input.addEventListener("blur", onBlurValidate);
    input.addEventListener("input", () => {
      renderFieldSummary();
      renderSidebarChecks();
    });
  }
  renderFieldSummary();
  renderSidebarChecks();
}

function collectProviderApiKeysForStore() {
  const providers = collectAssignedProviderNames();
  const out = {};
  for (const name of providers) {
    const el = document.querySelector(`[data-field-id="wizard.provider_api_key.${name}"]`);
    const val = el?.value?.trim();
    if (val) out[name] = val;
  }
  return Object.keys(out).length ? out : null;
}

/**
 * Copy main triager model into per-slot inputs.
 * @param {boolean} [onlyEmpty] When true, only fill inputs that are blank (uncheck unified).
 */
function syncMainModelToSlots(onlyEmpty = false) {
  const main = fieldValue("providers.tier_default.triager");
  if (main === undefined || main === null) return;
  const text = String(main).trim();
  if (!text) return;
  for (const fieldId of MODEL_SLOT_FIELDS) {
    const el = document.querySelector(`[data-field-id="${fieldId}"]`);
    if (!el || el.disabled) continue;
    if (onlyEmpty && String(el.value || "").trim()) continue;
    el.value = text;
  }
}

let modelSlotsWereUnified = true;

function updateModelSlotsPanel() {
  const unified = isUseMainModelForAll();
  const panel = document.getElementById("model-slots-panel");
  if (panel) panel.hidden = unified;
  document.querySelectorAll(".model-slot-input").forEach((el) => {
    el.disabled = unified;
    if (unified) el.removeAttribute("required");
    else el.setAttribute("required", "required");
  });
  if (!unified && modelSlotsWereUnified) {
    syncMainModelToSlots(true);
  }
  modelSlotsWereUnified = unified;
  updateProviderKeyFields();
  renderFieldSummary();
}

function stepComplete(stepId) {
  let required = STEP_REQUIRED[stepId] || [];
  if (stepId === "channels" && !fieldValue("wizard.telegram_create_new_bot")) {
    required = [...required, "wizard.telegram_bot_username"];
  }
  if (stepId === "model" && !isUseMainModelForAll()) {
    required = [...required, ...MODEL_SLOT_FIELDS];
  }
  if (stepId === "model") {
    for (const name of collectAssignedProviderNames()) {
      const v = fieldValue(`wizard.provider_api_key.${name}`);
      if (!v || !String(v).trim()) return false;
    }
  }
  if (required.length === 0) {
    if (stepId === "profile") return Boolean(selectedProfile);
    // A chosen preset fragment covers Sandbox defaults, so smart Next can fly
    // past it. Capabilities is always shown (D4/W3.4) — profiles pre-check only.
    if (selectedProfile && selectedProfile !== "skip") {
      if (stepId === "sandbox") return true;
    }
    return false;
  }
  const backendType = fieldValue("secrets_backend.type");
  for (const fieldId of required) {
    // Passphrase only applies to the encrypted_file backend; an openbao
    // selection skips that requirement (operator finalises address/token
    // by editing sevn.json by hand).
    if (fieldId === "wizard.secrets_passphrase" && backendType === "openbao") {
      continue;
    }
    const dom = fieldValue(fieldId);
    const hasDom = dom !== undefined && dom !== null && String(dom).trim() !== "";
    if (!hasDom) return false;
  }
  return true;
}

function renderSidebarChecks() {
  document.querySelectorAll(".wizard-nav-step").forEach((el, i) => {
    const sid = STEPS[i];
    el.classList.toggle("done", stepComplete(sid));
  });
}

function fieldValue(fieldId) {
  const el = document.querySelector(`[data-field-id="${fieldId}"]`);
  if (!el) return undefined;
  if (el.type === "checkbox") return el.checked;
  if (el.type === "hidden") return el.value;
  return el.value;
}

function isFieldEmpty(fieldId) {
  const v = fieldValue(fieldId);
  if (v === undefined || v === null) return true;
  if (typeof v === "boolean") return false;
  return String(v).trim() === "";
}

function isSummaryRequired(spec) {
  if (!spec.required) return false;
  if (typeof spec.requiredWhen === "function") {
    try {
      return Boolean(spec.requiredWhen());
    } catch (_e) {
      return true;
    }
  }
  return true;
}

function renderFieldSummary() {
  const host = document.getElementById("fieldSummaryList");
  if (!host) return;
  host.innerHTML = "";
  if (STEPS.includes("model")) {
    const main = fieldValue("providers.tier_default.triager");
    const row = document.createElement("div");
    row.className = "field-summary-row";
    const label = isUseMainModelForAll() ? "All LLM slots" : "Model mode";
    const display = isUseMainModelForAll()
      ? main && String(main).trim()
        ? `→ ${String(main).trim()}`
        : "(main model required)"
      : "Per-slot overrides";
    row.innerHTML = `<div class="field-summary-label">${label}</div><div class="field-summary-value">${display}</div>`;
    host.appendChild(row);
    if (!isUseMainModelForAll()) {
      for (const fieldId of MODEL_SLOT_FIELDS) {
        const raw = fieldValue(fieldId);
        const sub = document.createElement("div");
        sub.className = `field-summary-row${isFieldEmpty(fieldId) ? " is-empty" : ""}`;
        const name = MODEL_SLOT_LABELS[fieldId] || fieldId;
        sub.innerHTML = `<div class="field-summary-label">${name}</div><div class="field-summary-value">${raw && String(raw).trim() ? String(raw).trim() : "(required)"}</div>`;
        host.appendChild(sub);
      }
    }
  }
  for (const spec of SUMMARY_FIELDS) {
    const required = isSummaryRequired(spec);
    const raw = fieldValue(spec.id);
    const domHasValue = !isFieldEmpty(spec.id);
    const empty = required && !domHasValue;
    let display = "—";
    if (spec.secret) {
      display = domHasValue ? "••••••••" : required ? "(required)" : "—";
    } else if (raw !== undefined && raw !== null && String(raw).trim() !== "") {
      display = String(raw);
    } else if (raw === false) {
      display = "false";
    } else if (raw === true) {
      display = "true";
    }
    const row = document.createElement("div");
    row.className = `field-summary-row${empty ? " is-empty" : ""}`;
    row.innerHTML = `<div class="field-summary-label">${spec.label}</div><div class="field-summary-value${display === "—" ? " muted" : ""}">${display}</div>`;
    host.appendChild(row);
  }
  const badge = document.getElementById("configValidBadge");
  if (badge) {
    const ok = !SUMMARY_FIELDS.some((s) => isSummaryRequired(s) && isFieldEmpty(s.id));
    badge.hidden = !ok;
  }
  renderSidebarChecks();
}

async function refreshCredentialsStatus() {
  const { body } = await api("/api/credentials-status");
  credentialsReady = Boolean(body.ready_for_handoff);
  renderFieldSummary();
  return body;
}

function showStep(idx) {
  if (idx < 0 || idx >= STEPS.length) return;
  currentStep = idx;
  const stepId = STEPS[idx];
  document.querySelectorAll(".wizard-step").forEach((el) => {
    el.classList.toggle("active", el.getAttribute("data-step") === stepId);
  });
  document.querySelectorAll(".wizard-nav-step").forEach((el, i) => {
    el.classList.toggle("active", i === idx);
    el.setAttribute("aria-current", i === idx ? "step" : "false");
  });
  updateProgress();
  updatePageHead();
  updateNavButtons();
  renderFieldSummary();
  if (stepId === "workspace") ensureGatewayTokenGenerated();
  if (stepId === "capabilities" && !capabilitiesData) {
    refreshCapabilitiesUi().catch(() => {});
  }
  if (stepId === "validate") {
    refreshInstallPlan().catch(() => {});
  }
  updatePromoteGate();
}

function collectFields() {
  const fields = {};
  document.querySelectorAll("[data-field-id]").forEach((el) => {
    const id = el.getAttribute("data-field-id");
    if (!id) return;
    if (el.classList.contains("model-slot-input") && el.disabled) return;
    if (el.type === "checkbox") {
      fields[id] = el.checked;
    } else if (el.type === "number") {
      fields[id] = el.value === "" ? null : Number(el.value);
    } else if (el.type === "hidden") {
      const v = el.value;
      if (v === "true") fields[id] = true;
      else if (v === "false") fields[id] = false;
      else fields[id] = v;
    } else {
      fields[id] = el.value;
    }
  });
  fields["onboarding.applied_profile"] = selectedProfile;
  return fields;
}

function buildPayload() {
  return {
    profile_id: selectedProfile === "skip" ? null : selectedProfile,
    fields: collectFields(),
  };
}

function channelsValidationContext() {
  return {
    "wizard.telegram_create_new_bot": fieldValue("wizard.telegram_create_new_bot"),
  };
}

function updateTelegramCreateNewUi() {
  const createNew = Boolean(fieldValue("wizard.telegram_create_new_bot"));
  const usernameField = document.getElementById("tg-bot-username-field");
  if (usernameField) usernameField.hidden = createNew;
  const nameField = document.getElementById("tg-bot-name-field");
  if (nameField) nameField.hidden = !createNew;
  const automateBtn = document.getElementById("btn-telegram-automate");
  if (automateBtn) {
    automateBtn.textContent = createNew
      ? "Create bot via BotFather"
      : "Look up token via BotFather";
  }
}

function setTelegramAutomationStatus(message, kind = "info") {
  const el = document.getElementById("telegram-automation-status");
  if (!el) return;
  el.textContent = message || "";
  el.className = `hint telegram-automation-status telegram-automation-status--${kind}`;
}

async function pollBrowserSteps(maxPolls = 30) {
  for (let i = 0; i < maxPolls; i += 1) {
    const { res, body } = await api("/api/browser/status");
    if (!res.ok) break;
    const steps = Array.isArray(body.steps) ? body.steps : [];
    const running = steps.filter((s) => s.state === "running").pop();
    if (running?.label) {
      setTelegramAutomationStatus(`Browser: ${running.label}…`);
    }
    if (!body.running && steps.length > 0) break;
    await new Promise((r) => setTimeout(r, 400));
  }
}

async function pollBrowserStepsUntil(isDone, intervalMs = 600) {
  while (!isDone()) {
    const { res, body } = await api("/api/browser/status");
    if (res.ok) {
      const steps = Array.isArray(body.steps) ? body.steps : [];
      const running = steps.filter((s) => s.state === "running").pop();
      const last = steps[steps.length - 1];
      const label = running?.label || last?.label || "";
      if (label === "telegram.wait_login") {
        setTelegramAutomationStatus(
          "Waiting for Telegram Web sign-in — scan the QR code in Chrome (checking every 10s)…",
        );
      } else if (label === "mytelegram.wait_auth") {
        setTelegramAppStatus(
          "Waiting for my.telegram.org sign-in — enter phone/code in Chrome (checking every 15s)…",
        );
      } else if (label === "mytelegram.enter_code") {
        setTelegramAppStatus(
          "Enter the Telegram verification code in Chrome — sevn checks every 30s and will not navigate away…",
        );
      } else if (label === "mytelegram.session_reused") {
        setTelegramAppStatus("Reusing my.telegram.org session from Chrome profile…");
      } else if (label === "mytelegram.use_existing_app") {
        setTelegramAppStatus("Using existing my.telegram.org app credentials…");
      } else if (label === "mytelegram.skipped") {
        setTelegramAppStatus("Skipping my.telegram.org — optional step…", "info");
      } else if (label.startsWith("mytelegram.")) {
        setTelegramAppStatus(`my.telegram.org: ${label.replace("mytelegram.", "")}…`);
      } else if (label) {
        setTelegramAutomationStatus(`Browser: ${label}…`);
      }
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

function applyTelegramAutomateResult(body) {
  if (body.bot_token) {
    const tokenInput = document.getElementById("tg_bot_token");
    if (tokenInput) {
      tokenInput.value = body.bot_token;
      tokenInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  if (body.bot_username) {
    const usernameInput = document.getElementById("tg_bot_username");
    if (usernameInput && !fieldValue("wizard.telegram_create_new_bot")) {
      usernameInput.value = body.bot_username;
      usernameInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  if (body.suggested_owner_user_id) {
    const ownerInput = document.getElementById("tg_owner_user_id");
    if (ownerInput && !ownerInput.value.trim()) {
      ownerInput.value = String(body.suggested_owner_user_id);
      ownerInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  renderFieldSummary();
  renderSidebarChecks();
}

function setTelegramAppStatus(message, kind = "info") {
  const el = document.getElementById("telegram-app-status");
  if (!el) return;
  el.textContent = message || "";
  el.className = `hint telegram-app-status telegram-app-status--${kind}`;
}

const MY_TELEGRAM_CONFIGURE_LATER =
  "Optional — set api_id and api_hash later from the Telegram /config menu or Mission Control.";

async function skipMyTelegramApiOptional(detail) {
  await api("/api/browser/stop", { method: "POST", body: "{}" }).catch(() => {});
  const message = detail
    ? `${detail} ${MY_TELEGRAM_CONFIGURE_LATER}`
    : `Skipped my.telegram.org setup. ${MY_TELEGRAM_CONFIGURE_LATER}`;
  setTelegramAppStatus(message, "info");
  if (STEPS[currentStep] === "channels") {
    const next = computeNextStep();
    if (next !== null) showStep(next);
  }
}

function isMyTelegramRateLimited(detail) {
  const text = String(detail || "").toLowerCase();
  return text.includes("too many tries") || text.includes("rate-limited");
}

function applyMyTelegramApiResult(body) {
  if (body.api_id) {
    const apiIdInput = document.getElementById("tg_api_id");
    if (apiIdInput) {
      apiIdInput.value = String(body.api_id);
      apiIdInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  if (body.api_hash) {
    const apiHashInput = document.getElementById("tg_api_hash");
    if (apiHashInput) {
      apiHashInput.value = String(body.api_hash);
      apiHashInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  if (body.phone) {
    const phoneInput = document.getElementById("tg_phone");
    if (phoneInput && !phoneInput.value.trim()) {
      phoneInput.value = String(body.phone);
      phoneInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  renderFieldSummary();
  renderSidebarChecks();
}

function wireChannelsUi() {
  document.querySelectorAll(".channel-sub-nav__tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.disabled) return;
      const id = tab.getAttribute("data-channel-tab");
      if (!id) return;
      document.querySelectorAll(".channel-sub-nav__tab").forEach((t) => {
        t.classList.toggle("active", t === tab);
      });
      document.querySelectorAll(".channel-panel").forEach((panel) => {
        const panelId = panel.getAttribute("data-channel-panel");
        panel.hidden = panelId !== id;
      });
    });
  });

  document.getElementById("tg_create_new_bot")?.addEventListener("change", () => {
    updateTelegramCreateNewUi();
    renderFieldSummary();
    renderSidebarChecks();
  });
  updateTelegramCreateNewUi();

  document.getElementById("btn-telegram-login")?.addEventListener("click", async () => {
    setTelegramAutomationStatus("Starting browser…");
    const start = await api("/api/browser/start", { method: "POST", body: "{}" });
    if (!start.res.ok) {
      setTelegramAutomationStatus(start.body.detail || "Could not start browser", "error");
      return;
    }
    setTelegramAutomationStatus("Chrome opened — sign in to Telegram Web (QR or phone). sevn waits for login…");
    const { res, body } = await api("/api/telegram/login", { method: "POST", body: "{}" });
    if (!res.ok) {
      setTelegramAutomationStatus(body.detail || "Telegram login failed", "error");
      return;
    }
    setTelegramAutomationStatus("Telegram Web signed in — run BotFather automation when ready.", "success");
    await pollBrowserSteps();
  });

  document.getElementById("btn-telegram-automate")?.addEventListener("click", async () => {
    const createNew = Boolean(fieldValue("wizard.telegram_create_new_bot"));
    const botUsername = fieldValue("wizard.telegram_bot_username");
    const botName = fieldValue("wizard.telegram_bot_name");
    if (createNew) {
      const { ok, message } = await validateField(
        "wizard.telegram_bot_name",
        botName,
        channelsValidationContext(),
      );
      if (!ok) {
        setTelegramAutomationStatus(message, "error");
        return;
      }
    } else {
      const { ok, message } = await validateField(
        "wizard.telegram_bot_username",
        botUsername,
        channelsValidationContext(),
      );
      if (!ok) {
        setTelegramAutomationStatus(message, "error");
        return;
      }
    }
    setTelegramAutomationStatus("Starting browser automation…");
    const start = await api("/api/browser/start", { method: "POST", body: "{}" });
    if (!start.res.ok) {
      setTelegramAutomationStatus(start.body.detail || "Could not start browser", "error");
      return;
    }
    const payload = { create_new: createNew };
    if (createNew) {
      payload.display_name = String(botName).trim();
      setTelegramAutomationStatus(
        "Chrome opened — sign in to Telegram Web if prompted; sevn drives BotFather automatically…",
      );
    } else {
      payload.bot_username = String(botUsername).trim();
      setTelegramAutomationStatus(
        "Chrome opened — sign in if needed; looking up existing bot token via BotFather…",
      );
    }
    let automateDone = false;
    const automatePromise = api("/api/telegram/automate", {
      method: "POST",
      body: JSON.stringify(payload),
    }).finally(() => {
      automateDone = true;
    });
    void pollBrowserStepsUntil(() => automateDone);
    const { res, body } = await automatePromise;
    if (!res.ok) {
      setTelegramAutomationStatus(body.detail || "BotFather automation failed", "error");
      return;
    }
    applyTelegramAutomateResult(body);
    const { res: credRes } = await storeCredentials();
    if (!credRes.ok) {
      setTelegramAutomationStatus(
        "Token extracted but saving secrets failed — click Save channel secrets",
        "error",
      );
      return;
    }
    await refreshCredentialsStatus();
    setTelegramAutomationStatus(
      body.bot_username
        ? `Stored token for @${body.bot_username} — review owner user id below`
        : "Token stored — review fields below",
      "success",
    );
  });

  document.getElementById("btn-telegram-my-api")?.addEventListener("click", async () => {
    const phone = fieldValue("wizard.telegram_phone");
    if (phone && String(phone).trim()) {
      const { ok, message } = await validateField("wizard.telegram_phone", phone);
      if (!ok) {
        setTelegramAppStatus(message, "error");
        return;
      }
    }
    setTelegramAppStatus("Starting browser for my.telegram.org…");
    const start = await api("/api/browser/start", { method: "POST", body: "{}" });
    if (!start.res.ok) {
      setTelegramAppStatus(start.body.detail || "Could not start browser", "error");
      return;
    }
    const payload = {};
    if (phone && String(phone).trim()) payload.phone = String(phone).trim();
    setTelegramAppStatus(
      phone && String(phone).trim()
        ? "Chrome opened — completing my.telegram.org sign-in (phone pre-filled)…"
        : "Chrome opened — sign in on my.telegram.org in Chrome, then sevn continues…",
    );
    let myApiDone = false;
    const myApiPromise = api("/api/telegram/my-api", {
      method: "POST",
      body: JSON.stringify(payload),
    }).finally(() => {
      myApiDone = true;
    });
    void pollBrowserStepsUntil(() => myApiDone);
    const { res, body } = await myApiPromise;
    if (res.ok && body.skipped) {
      await skipMyTelegramApiOptional(body.detail || body.configure_later);
      return;
    }
    if (!res.ok) {
      if (isMyTelegramRateLimited(body.detail)) {
        await skipMyTelegramApiOptional(body.detail);
        return;
      }
      setTelegramAppStatus(body.detail || "my.telegram.org automation failed", "error");
      return;
    }
    applyMyTelegramApiResult(body);
    const { res: credRes } = await storeCredentials();
    if (!credRes.ok) {
      setTelegramAppStatus(
        "Credentials extracted but saving secrets failed — click Save channel secrets",
        "error",
      );
      return;
    }
    await refreshCredentialsStatus();
    setTelegramAppStatus(
      body.api_id
        ? `Stored api_id ${body.api_id} — review api_hash below`
        : "API credentials stored",
      "success",
    );
  });

  document.getElementById("btn-skip-telegram-my-api")?.addEventListener("click", async () => {
    await skipMyTelegramApiOptional();
  });
}

async function validateField(fieldId, value, context = undefined) {
  const payload = { field_id: fieldId, value };
  if (context && typeof context === "object") payload.context = context;
  const { res, body } = await api("/api/validate-field", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return { ok: res.ok && body.ok, message: body.message || body.detail || "" };
}

async function onBlurValidate(ev) {
  const el = ev.target;
  const fieldId = el.getAttribute("data-field-id");
  if (!fieldId || fieldId.startsWith("wizard.") === false && el.type === "password") return;
  if (!fieldId || (el.type !== "checkbox" && !el.value && el.value !== 0)) return;
  const { ok, message } = await validateField(
    fieldId,
    el.type === "checkbox" ? el.checked : el.value,
  );
  const wrap = el.closest(".field");
  if (!wrap) return;
  wrap.classList.toggle("invalid", !ok);
  const err = wrap.querySelector(".err");
  if (err) {
    err.textContent = ok ? "" : message;
    err.style.display = ok ? "none" : "block";
  }
  renderFieldSummary();
}

function isValueProfile(row) {
  return (row.tags || []).includes("value");
}

function profileCapabilitiesReady(row) {
  return row.capabilities_ready === true;
}

function profileTag(row) {
  if (isValueProfile(row)) return "recommended";
  return "";
}

function profileCardSubtitle(row) {
  return row.capabilities_summary || row.short_description || "";
}

function applyProfileToModel(profileId) {
  const row = (meta?.profiles || []).find((p) => p.profile_id === profileId);
  if (!row?.model) return;
  const triager = document.getElementById("triager_model");
  if (triager) triager.value = row.model;
  if (isUseMainModelForAll()) syncMainModelToSlots(false);
  updateProviderKeyFields();
  renderFieldSummary();
}

function sortedProfiles() {
  const rows = [...(meta?.profiles || [])];
  rows.sort((a, b) => {
    const av = isValueProfile(a) ? 0 : 1;
    const bv = isValueProfile(b) ? 0 : 1;
    return av - bv;
  });
  return rows;
}

function renderProfiles() {
  const host = document.getElementById("profile-list");
  if (!host) return;
  host.innerHTML = "";

  const rows = sortedProfiles();
  for (const row of rows) {
    const tag = profileTag(row);
    const disabled = !profileCapabilitiesReady(row);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `card profile-card${selectedProfile === row.profile_id ? " selected" : ""}${disabled ? " is-disabled" : ""}`;
    if (disabled) {
      btn.setAttribute("aria-disabled", "true");
      btn.title = "coming soon — pick a recommended preset or Skip / custom for now";
    }
    if (tag) {
      btn.innerHTML = `<span class="profile-tag ${tag}">${tag}</span>`;
    } else if (disabled) {
      btn.innerHTML = `<span class="profile-tag muted">soon</span>`;
    }
    const model = row.model || "—";
    const hostVal = row.host || "—";
    btn.innerHTML += `
      <div class="profile-card-top">
        <div style="flex:1">
          <div class="card__heading">${row.title}</div>
          <p class="card__sub">${profileCardSubtitle(row)}</p>
        </div>
        <div class="profile-check"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg></div>
      </div>
      <div class="profile-meta">
        <div class="profile-meta-cell"><span class="profile-meta-key">model</span><span class="profile-meta-val">${model}</span></div>
        <div class="profile-meta-cell"><span class="profile-meta-key">host</span><span class="profile-meta-val">${hostVal}</span></div>
      </div>`;
    btn.onclick = () => {
      if (disabled) return;
      selectedProfile = row.profile_id;
      applyProfileToModel(row.profile_id);
      renderProfiles();
      refreshCapabilitiesUi(row.profile_id).catch(() => {});
      renderFieldSummary();
    };
    btn.addEventListener("dblclick", (ev) => {
      ev.preventDefault();
      if (disabled) return;
      openProfileInspector(row.profile_id);
    });
    btn.title = disabled
      ? "coming soon — pick a recommended preset or Skip / custom for now"
      : "Click to select · double-click to inspect preset values";
    host.appendChild(btn);
  }

  const skipBtn = document.createElement("button");
  skipBtn.type = "button";
  skipBtn.className = `card profile-card${selectedProfile === "skip" ? " selected" : ""}`;
  skipBtn.innerHTML = `
    <div class="profile-card-top">
      <div style="flex:1">
        <div class="card__heading">Skip / custom</div>
        <p class="card__sub">No preset fragment. Walk every step and choose your own values.</p>
      </div>
      <div class="profile-check"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg></div>
    </div>
    <div class="profile-meta">
      <div class="profile-meta-cell"><span class="profile-meta-key">model</span><span class="profile-meta-val">—</span></div>
      <div class="profile-meta-cell"><span class="profile-meta-key">host</span><span class="profile-meta-val">—</span></div>
    </div>`;
  skipBtn.onclick = () => {
    selectedProfile = "skip";
    renderProfiles();
    refreshCapabilitiesUi("skip").catch(() => {});
    renderFieldSummary();
  };
  host.appendChild(skipBtn);
}

let profileInspectorOpen = false;

function hideProfileInspectorModal() {
  const modal = document.getElementById("profile-inspector-modal");
  if (modal) modal.hidden = true;
  profileInspectorOpen = false;
  const errEl = document.getElementById("profile-inspector-error");
  if (errEl) {
    errEl.hidden = true;
    errEl.textContent = "";
  }
}

function renderProfileInspectorRows(rows) {
  const tbody = document.getElementById("profile-inspector-tbody");
  const wrap = document.getElementById("profile-inspector-table-wrap");
  if (!tbody || !wrap) return;
  tbody.innerHTML = "";
  for (const row of rows || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.tab || "")}</td>
      <td>${escapeHtml(row.field || "")}</td>
      <td>${escapeHtml(row.value || "")}</td>
      <td>${escapeHtml(row.explanation || "")}</td>`;
    tbody.appendChild(tr);
  }
  wrap.hidden = rows.length === 0;
}

async function openProfileInspector(profileId) {
  const modal = document.getElementById("profile-inspector-modal");
  const titleEl = document.getElementById("profile-inspector-title");
  const subtitleEl = document.getElementById("profile-inspector-subtitle");
  const loadingEl = document.getElementById("profile-inspector-loading");
  const errEl = document.getElementById("profile-inspector-error");
  const wrap = document.getElementById("profile-inspector-table-wrap");
  if (!modal || !profileId || profileId === "skip") return;

  profileInspectorOpen = true;
  modal.hidden = false;
  if (titleEl) titleEl.textContent = "Profile inspector";
  if (subtitleEl) subtitleEl.textContent = "Loading preset values…";
  if (loadingEl) loadingEl.hidden = false;
  if (errEl) {
    errEl.hidden = true;
    errEl.textContent = "";
  }
  if (wrap) wrap.hidden = true;
  renderProfileInspectorRows([]);

  const { res, body } = await api(
    `/api/profile-inspector?profile_id=${encodeURIComponent(profileId)}`,
  );
  if (loadingEl) loadingEl.hidden = true;
  if (!res.ok) {
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = body.detail || "Could not load profile inspector";
    }
    if (subtitleEl) subtitleEl.textContent = "Read-only preset values.";
    return;
  }
  if (titleEl) titleEl.textContent = `Profile inspector — ${body.title || profileId}`;
  if (subtitleEl) {
    subtitleEl.textContent =
      "Read-only table of values this preset applies (Tab | Field | Value | Explanation). Edit on wizard steps, not here.";
  }
  renderProfileInspectorRows(body.rows || []);
}

function wireProfileInspectorModal() {
  const modal = document.getElementById("profile-inspector-modal");
  document.getElementById("btn-profile-inspector-cancel")?.addEventListener("click", hideProfileInspectorModal);
  modal?.addEventListener("click", (ev) => {
    if (ev.target?.classList?.contains("wizard-modal-backdrop")) hideProfileInspectorModal();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && profileInspectorOpen) {
      ev.preventDefault();
      hideProfileInspectorModal();
    }
  });
}

function pickDefaultValueProfile() {
  const rows = sortedProfiles().filter(isValueProfile);
  if (rows.length === 0) return "skip";
  const hostHint = (meta?.defaults?.host || "").toLowerCase();
  const dockerHit = rows.find((r) => (r.host || "").toLowerCase() === "docker");
  const osxHit = rows.find((r) => (r.host || "").toLowerCase() === "osx");
  if (hostHint === "docker" && dockerHit) return dockerHit.profile_id;
  if (osxHit) return osxHit.profile_id;
  return rows[0].profile_id;
}

const MAJOR_TIMEZONE_LABELS = {
  "Pacific/Honolulu": "Honolulu",
  "America/Anchorage": "Anchorage",
  "America/Los_Angeles": "Los Angeles",
  "America/Denver": "Denver",
  "America/Phoenix": "Phoenix",
  "America/Chicago": "Chicago",
  "America/Mexico_City": "Mexico City",
  "America/Bogota": "Bogotá",
  "America/Toronto": "Toronto",
  "America/New_York": "New York",
  "America/Sao_Paulo": "São Paulo",
  "America/Buenos_Aires": "Buenos Aires",
  "Atlantic/Reykjavik": "Reykjavik",
  "Europe/London": "London",
  "Europe/Dublin": "Dublin",
  "Europe/Paris": "Paris",
  "Europe/Berlin": "Berlin",
  "Europe/Amsterdam": "Amsterdam",
  "Europe/Madrid": "Madrid",
  "Europe/Rome": "Rome",
  "Europe/Stockholm": "Stockholm",
  "Europe/Helsinki": "Helsinki",
  "Europe/Athens": "Athens",
  "Europe/Istanbul": "Istanbul",
  "Europe/Moscow": "Moscow",
  "Africa/Cairo": "Cairo",
  "Africa/Johannesburg": "Johannesburg",
  "Africa/Lagos": "Lagos",
  "Africa/Nairobi": "Nairobi",
  "Asia/Jerusalem": "Jerusalem",
  "Asia/Dubai": "Dubai",
  "Asia/Karachi": "Karachi",
  "Asia/Kolkata": "Mumbai / Delhi",
  "Asia/Dhaka": "Dhaka",
  "Asia/Bangkok": "Bangkok",
  "Asia/Singapore": "Singapore",
  "Asia/Hong_Kong": "Hong Kong",
  "Asia/Shanghai": "Shanghai",
  "Asia/Taipei": "Taipei",
  "Asia/Seoul": "Seoul",
  "Asia/Tokyo": "Tokyo",
  "Australia/Perth": "Perth",
  "Australia/Adelaide": "Adelaide",
  "Australia/Sydney": "Sydney",
  "Pacific/Auckland": "Auckland",
  UTC: "UTC",
};

function populateTimezoneSelect(select) {
  if (!select) return;
  const keep = select.querySelector("option[value='']");
  select.innerHTML = "";
  if (keep) select.appendChild(keep);
  let zones = [];
  try {
    zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  } catch (_e) {
    zones = Object.keys(MAJOR_TIMEZONE_LABELS);
  }
  const labeled = [];
  const rest = [];
  for (const tz of zones) {
    const city = MAJOR_TIMEZONE_LABELS[tz];
    if (city) labeled.push({ tz, label: `${city} (${tz})` });
    else rest.push({ tz, label: tz.replace(/_/g, " ") });
  }
  labeled.sort((a, b) => a.label.localeCompare(b.label));
  rest.sort((a, b) => a.label.localeCompare(b.label));
  for (const { tz, label } of [...labeled, ...rest]) {
    const opt = document.createElement("option");
    opt.value = tz;
    opt.textContent = label;
    select.appendChild(opt);
  }
}

function fillSelectOptions(select, values, emptyLabel) {
  if (!select || !Array.isArray(values)) return;
  const current = select.value;
  const keep = select.querySelector("option[value='']");
  select.innerHTML = "";
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = emptyLabel || "— optional —";
  select.appendChild(empty);
  for (const value of values) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    select.appendChild(opt);
  }
  if (current && [...select.options].some((o) => o.value === current)) {
    select.value = current;
  }
}

function syncPersonalityPreferencesHidden() {
  const hidden = document.getElementById("personality_preferences");
  if (!hidden) return;
  const selected = [...document.querySelectorAll("#personality_preferences_options input[type='checkbox']:checked")]
    .map((cb) => cb.value);
  hidden.value = selected.join("; ");
  renderFieldSummary();
}

function applyPersonalityPreferencesToCheckboxes(raw) {
  const text = String(raw || "").trim();
  if (!text) return;
  const selected = new Set(text.split(";").map((s) => s.trim()).filter(Boolean));
  document.querySelectorAll("#personality_preferences_options input[type='checkbox']").forEach((cb) => {
    cb.checked = selected.has(cb.value);
  });
  syncPersonalityPreferencesHidden();
}

function renderPersonalityPreferenceCheckboxes(values) {
  const host = document.getElementById("personality_preferences_options");
  if (!host || !Array.isArray(values)) return;
  const hidden = document.getElementById("personality_preferences");
  const prior = hidden?.value || "";
  host.innerHTML = "";
  for (const value of values) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = value;
    input.addEventListener("change", syncPersonalityPreferencesHidden);
    label.append(input, document.createTextNode(` ${value}`));
    host.appendChild(label);
  }
  applyPersonalityPreferencesToCheckboxes(prior);
}

function wirePersonalityUi() {
  populateTimezoneSelect(document.getElementById("personality_timezone"));
  api("/api/personality-presets")
    .then(({ res, body }) => {
      if (!res.ok) return;
      fillSelectOptions(document.getElementById("personality_style"), body.style, "— optional preset —");
      fillSelectOptions(document.getElementById("personality_language"), body.languages || ["English"], "— optional —");
      fillSelectOptions(document.getElementById("personality_vibe"), body.vibes, "— optional preset —");
      fillSelectOptions(document.getElementById("personality_emoji"), body.emojis, "— optional —");
      renderPersonalityPreferenceCheckboxes(body.preferences);
    })
    .catch(() => {});
}

function wireFieldHelp() {
  document.querySelectorAll("[data-field-id]").forEach((el) => {
    const fieldId = el.getAttribute("data-field-id");
    const label = el.closest(".field")?.querySelector("label");
    if (!label || label.querySelector(".field-help-toggle")) return;
    let help = fieldHelp[fieldId];
    if (!help) {
      const raw = el.closest(".field")?.dataset.capabilityHelp;
      if (raw) {
        try {
          help = JSON.parse(raw);
        } catch (_e) {
          help = { long_description: raw };
        }
      }
    }
    if (!help) return;
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "field-help-toggle";
    toggle.textContent = "?";
    toggle.title = "What is this?";
    toggle.addEventListener("click", (ev) => {
      ev.preventDefault();
      const panel = el.closest(".field")?.querySelector(`[data-help-for="${fieldId}"]`);
      if (!panel) return;
      panel.classList.toggle("open");
    });
    label.appendChild(toggle);
    const panel = el.closest(".field")?.querySelector(`[data-help-for="${fieldId}"]`);
    if (panel && !panel.textContent.trim()) {
      let html = "";
      const longDesc = typeof help === "string" ? help : help.long_description;
      const howTo = typeof help === "object" ? help.how_to_collect : "";
      if (longDesc) {
        html += `<strong>What it does</strong>${longDesc}`;
      }
      if (howTo) {
        html += `<strong style="margin-top:8px">How to choose</strong>${howTo}`;
      }
      panel.innerHTML = html;
    }
  });
}

function capabilityHelpFor(cap) {
  const fieldId = cap.config_paths?.[0];
  if (fieldId && fieldHelp[fieldId]) {
    return fieldHelp[fieldId];
  }
  if (cap.description) {
    return { long_description: cap.description };
  }
  return null;
}

function isCapabilityStub(cap) {
  const cid = String(cap.capability_id || "");
  return cid.endsWith("_stub") || /coming soon/i.test(String(cap.label || ""));
}

function capabilityFieldId(cap) {
  return cap.config_paths?.[0] || `capability.${cap.capability_id}`;
}

async function loadCapabilities(profileId = selectedProfile) {
  const pid = profileId === "skip" ? "" : profileId || "";
  const qs = pid ? `?profile_id=${encodeURIComponent(pid)}` : "";
  const { res, body } = await api(`/api/capabilities${qs}`);
  if (!res.ok) {
    capabilitiesData = null;
    return null;
  }
  capabilitiesData = body;
  return body;
}

function renderCapabilityControl(cap, mergedDefault) {
  const fieldId = capabilityFieldId(cap);
  const cfgVal = configValueForField(lastAppliedConfig, fieldId);
  const initial =
    cfgVal !== undefined && cfgVal !== null && cfgVal !== ""
      ? cfgVal
      : mergedDefault;
  if (cap.control === "hidden") {
    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.setAttribute("data-field-id", fieldId);
    hidden.value = initial === true || initial === "true" ? "true" : "false";
    return hidden;
  }
  const field = document.createElement("div");
  field.className = "field";
  const help = capabilityHelpFor(cap);
  if (help) {
    field.dataset.capabilityHelp = JSON.stringify(help);
  }
  if (cap.control === "select") {
    const label = document.createElement("label");
    label.setAttribute("for", `cap_${cap.capability_id}`);
    label.textContent = cap.label;
    const select = document.createElement("select");
    select.className = "select";
    select.id = `cap_${cap.capability_id}`;
    select.setAttribute("data-field-id", fieldId);
    for (const opt of cap.select_options || []) {
      const option = document.createElement("option");
      option.value = opt;
      option.textContent = opt;
      if (String(initial) === opt) option.selected = true;
      select.appendChild(option);
    }
    const panel = document.createElement("div");
    panel.className = "field-help-panel";
    panel.setAttribute("data-help-for", fieldId);
    field.append(label, select, panel);
    return field;
  }
  if (cap.control === "text") {
    const label = document.createElement("label");
    label.setAttribute("for", `cap_${cap.capability_id}`);
    label.textContent = cap.label;
    const input = document.createElement("input");
    input.className = "input";
    input.type = "text";
    input.id = `cap_${cap.capability_id}`;
    input.setAttribute("data-field-id", fieldId);
    input.placeholder = "obsidian/alex_AI";
    input.value = initial === true || initial === false ? "" : String(initial ?? "");
    const panel = document.createElement("div");
    panel.className = "field-help-panel";
    panel.setAttribute("data-help-for", fieldId);
    field.append(label, input, panel);
    return field;
  }
  if (cap.control === "folder_picker") {
    const label = document.createElement("label");
    label.textContent = cap.label;
    const browseRoot = document.createElement("input");
    browseRoot.type = "hidden";
    browseRoot.setAttribute("data-field-id", fieldId);
    browseRoot.value = initial === true || initial === false ? "" : String(initial ?? "");
    const current = document.createElement("div");
    current.className = "hint";
    current.style.fontSize = "var(--sevn-fs-xs)";
    current.textContent = browseRoot.value
      ? `Selected: ${browseRoot.value}`
      : "No folder selected (uses default layout when empty).";
    const row = document.createElement("div");
    row.style.display = "flex";
    row.style.gap = "8px";
    row.style.flexWrap = "wrap";
    const pickBtn = document.createElement("button");
    pickBtn.type = "button";
    pickBtn.className = "btn btn-ghost btn-sm";
    pickBtn.textContent = "Browse…";
    const listHost = document.createElement("div");
    listHost.style.marginTop = "8px";
    let browsePath = ".";
    async function refreshBrowse() {
      listHost.innerHTML = "";
      const { res, body } = await api(
        `/api/onboarding/folder-picker?path=${encodeURIComponent(browsePath)}`
      );
      if (!res.ok) return;
      const entries = body.entries || [];
      if (body.adoption_note) {
        const note = document.createElement("p");
        note.className = "hint";
        note.style.fontSize = "var(--sevn-fs-xs)";
        note.textContent = body.adoption_note;
        listHost.appendChild(note);
      }
      if (browsePath !== ".") {
        const up = document.createElement("button");
        up.type = "button";
        up.className = "btn btn-ghost btn-sm";
        up.textContent = "⬆ Up";
        up.addEventListener("click", () => {
          browsePath = browsePath.includes("/")
            ? browsePath.replace(/\/[^/]+$/, "") || "."
            : ".";
          refreshBrowse();
        });
        listHost.appendChild(up);
      }
      for (const entry of entries) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-ghost btn-sm";
        btn.textContent = `📂 ${entry.name}`;
        btn.addEventListener("click", () => {
          browsePath = entry.relative;
          refreshBrowse();
        });
        listHost.appendChild(btn);
      }
      const selectHere = document.createElement("button");
      selectHere.type = "button";
      selectHere.className = "btn btn-primary btn-sm";
      selectHere.textContent = "✓ Select here";
      selectHere.addEventListener("click", () => {
        if (browsePath === ".") return;
        browseRoot.value = browsePath;
        current.textContent = `Selected: ${browsePath}`;
      });
      listHost.appendChild(selectHere);
    }
    pickBtn.addEventListener("click", () => {
      browsePath = ".";
      refreshBrowse();
    });
    row.append(pickBtn);
    const panel = document.createElement("div");
    panel.className = "field-help-panel";
    panel.setAttribute("data-help-for", fieldId);
    field.append(label, browseRoot, current, row, listHost, panel);
    return field;
  }
  const label = document.createElement("label");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.setAttribute("data-field-id", fieldId);
  const stub = isCapabilityStub(cap);
  if (stub) {
    input.disabled = true;
    input.checked = false;
  } else {
    input.checked = Boolean(initial);
  }
  label.append(input, document.createTextNode(` ${cap.label}`));
  const panel = document.createElement("div");
  panel.className = "field-help-panel";
  panel.setAttribute("data-help-for", fieldId);
  if (cap.description && !fieldHelp[fieldId]) {
    panel.textContent = cap.description;
  }
  field.append(label, panel);
  return field;
}

function renderCapabilitiesPanel() {
  const host = document.getElementById("capabilities-groups");
  if (!host || !capabilitiesData?.groups) return;
  const snapshot = {};
  host.querySelectorAll("[data-field-id]").forEach((el) => {
    const id = el.getAttribute("data-field-id");
    if (!id) return;
    if (el.type === "checkbox") snapshot[id] = el.checked;
    else snapshot[id] = el.value;
  });
  host.innerHTML = "";
  for (const group of capabilitiesData.groups) {
    const visible = (group.capabilities || []).filter((cap) => !cap.wizard_tab);
    if (!visible.length) continue;
    const card = document.createElement("div");
    card.className = "card capability-group-card";
    const heading = document.createElement("h3");
    heading.className = "card__heading";
    heading.textContent = group.label;
    card.appendChild(heading);
    if (group.description) {
      const sub = document.createElement("p");
      sub.className = "hint";
      sub.style.fontSize = "var(--sevn-fs-xs)";
      sub.style.marginBottom = "10px";
      sub.textContent = group.description;
      card.appendChild(sub);
    }
    for (const cap of visible) {
      const mergedDefault =
        cap.merged_default !== undefined && cap.merged_default !== null
          ? cap.merged_default
          : cap.default;
      card.appendChild(renderCapabilityControl(cap, mergedDefault));
    }
    host.appendChild(card);
  }
  for (const [id, val] of Object.entries(snapshot)) {
    const el = host.querySelector(`[data-field-id="${id}"]`);
    if (!el) continue;
    if (el.type === "checkbox") el.checked = Boolean(val);
    else el.value = String(val);
  }
  document.querySelectorAll("#capabilities-groups [data-field-id]").forEach((el) => {
    el.addEventListener("blur", onBlurValidate);
    el.addEventListener("input", () => renderFieldSummary());
    el.addEventListener("change", () => {
      renderFieldSummary();
      syncOpenwikiCredentialsPanel();
    });
  });
  wireFieldHelp();
  renderFieldSummary();
  syncOpenwikiCredentialsPanel();
}

function syncOpenwikiCredentialsPanel() {
  const panel = document.getElementById("openwiki-credentials-panel");
  if (!panel) return;
  const enabled = document.querySelector(
    '#capabilities-groups [data-field-id="skills.openwiki.enabled"]'
  );
  const show = enabled && enabled.type === "checkbox" && enabled.checked;
  panel.hidden = !show;
}

async function refreshCapabilitiesUi(profileId = selectedProfile) {
  await loadCapabilities(profileId);
  renderCapabilitiesPanel();
  await refreshAgplNotice();
}

async function refreshAgplNotice() {
  const footer = document.getElementById("capabilities-agpl-notice");
  if (!footer) return;
  footer.hidden = true;
  footer.textContent = "";
}

function wireTunnelUi() {
  document.querySelectorAll(".tunnel-option").forEach((opt) => {
    const radio = opt.querySelector('input[type="radio"]');
    if (!radio) return;
    radio.addEventListener("change", () => {
      document.querySelectorAll(".tunnel-option").forEach((o) => o.classList.remove("selected"));
      opt.classList.add("selected");
      const hidden = document.getElementById("tunnel_mode");
      if (hidden) hidden.value = radio.value;
      renderFieldSummary();
    });
  });
}

function wireSandboxUi() {
  document.querySelectorAll(".sandbox-option").forEach((opt) => {
    const radio = opt.querySelector('input[type="radio"]');
    if (!radio) return;
    radio.addEventListener("change", () => {
      document.querySelectorAll(".sandbox-option").forEach((o) => o.classList.remove("selected"));
      opt.classList.add("selected");
      const hidden = document.getElementById("sandbox_mode");
      if (hidden) hidden.value = radio.value;
      renderFieldSummary();
    });
  });
}

function generateGatewayTokenHex() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function ensureGatewayTokenGenerated() {
  const hidden = document.getElementById("gateway_token_hidden");
  const display = document.getElementById("gateway_token_display");
  if (!hidden) return;
  if (!hidden.value || hidden.value.length < 32) {
    hidden.value = generateGatewayTokenHex();
  }
  if (display) display.value = hidden.value;
}

function wireGatewayTokenUi() {
  const hidden = document.getElementById("gateway_token_hidden");
  const display = document.getElementById("gateway_token_display");
  const copyBtn = document.getElementById("gateway_token_copy");
  const regenBtn = document.getElementById("gateway_token_regen");
  if (!hidden) return;
  ensureGatewayTokenGenerated();
  copyBtn?.addEventListener("click", async () => {
    ensureGatewayTokenGenerated();
    try {
      await navigator.clipboard.writeText(hidden.value);
      copyBtn.textContent = "Copied";
      setTimeout(() => { copyBtn.textContent = "Copy"; }, 1500);
    } catch (_) {
      /* clipboard may be unavailable */
    }
  });
  regenBtn?.addEventListener("click", () => {
    hidden.value = generateGatewayTokenHex();
    if (display) display.value = hidden.value;
    renderFieldSummary();
  });
}

async function refreshGithubStatus() {
  const statusEl = document.getElementById("github-status-text");
  const oauthBtn = document.getElementById("btn-github-oauth");
  const disconnectBtn = document.getElementById("btn-github-disconnect");
  const hostOffer = document.getElementById("github-host-offer");
  const { res, body } = await api("/api/github/status");
  if (!res.ok || !statusEl) return;
  if (body.connected) {
    const login = body.login ? ` (@${body.login})` : "";
    statusEl.textContent = `Connected${login}`;
    statusEl.style.color = "var(--sevn-success)";
    if (disconnectBtn) disconnectBtn.hidden = false;
    if (hostOffer) hostOffer.hidden = true;
  } else {
    statusEl.textContent = "Not connected";
    statusEl.style.color = "var(--sevn-fg-muted)";
    if (disconnectBtn) disconnectBtn.hidden = true;
    await refreshHostGithubOffer();
  }
  if (oauthBtn) {
    oauthBtn.disabled = false;
    oauthBtn.title =
      body.oauth_configured === false
        ? "Enter OAuth app credentials below, save them, then connect — or use a PAT"
        : "";
  }
}

async function refreshHostGithubOffer() {
  const hostOffer = document.getElementById("github-host-offer");
  const hostText = document.getElementById("github-host-offer-text");
  if (!hostOffer || !hostText) return;
  const { res, body } = await api("/api/github/host-status");
  if (!res.ok || !body.available) {
    hostOffer.hidden = true;
    return;
  }
  const login = body.login ? `@${body.login}` : "a host account";
  const source =
    body.source === "gh_cli" ? "GitHub CLI" : body.source === "keychain" ? "sevn Keychain" : "host env";
  hostText.textContent = `Found ${login} on this Mac (${source}). Use it for sevn, or connect a different account below.`;
  hostOffer.hidden = false;
}

function showMySevnGithubBanner(message, kind) {
  const banner = document.getElementById("my-sevn-github-banner");
  if (!banner) return;
  banner.textContent = message;
  banner.className = `banner banner-${kind || "info"}`;
  banner.hidden = false;
}

let openaiOauthConnected = false;

async function refreshOpenAiOauthStatus() {
  const statusEl = document.getElementById("openai-oauth-status");
  const errEl = document.getElementById("openai-oauth-error");
  const { res, body } = await api("/api/openai/oauth/status");
  if (!res.ok) {
    openaiOauthConnected = false;
    if (errEl) errEl.textContent = body.detail || "Could not read OpenAI OAuth status";
    return;
  }
  openaiOauthConnected = Boolean(body.connected);
  if (statusEl) {
    statusEl.textContent = body.connected
      ? `ChatGPT connected (account ${body.account_id || "?"})`
      : "";
  }
  if (errEl) errEl.textContent = "";
  const openaiInput = document.querySelector('[data-field-id="wizard.provider_api_key.openai"]');
  if (openaiInput && openaiOauthConnected) {
    openaiInput.removeAttribute("required");
  }
  renderFieldSummary();
  renderSidebarChecks();
}

function wireOpenAiOAuthUi() {
  document.getElementById("btn-openai-oauth")?.addEventListener("click", async () => {
    const errEl = document.getElementById("openai-oauth-error");
    const statusEl = document.getElementById("openai-oauth-status");
    if (errEl) errEl.textContent = "";
    const { res, body } = await api("/api/openai/oauth/start");
    if (!res.ok) {
      if (errEl) errEl.textContent = body.detail || "Could not start ChatGPT OAuth";
      return;
    }
    if (body.authorize_url) {
      window.open(body.authorize_url, "_blank", "noopener,noreferrer");
    }
    if (statusEl) statusEl.textContent = "Waiting for ChatGPT sign-in…";
    const state = body.state;
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      const poll = await api(`/api/openai/oauth/poll?state=${encodeURIComponent(state)}`);
      if (!poll.res.ok) continue;
      if (poll.body.status === "success") {
        await refreshOpenAiOauthStatus();
        return;
      }
      if (poll.body.status === "failed") {
        if (errEl) errEl.textContent = poll.body.detail || "ChatGPT OAuth failed";
        if (statusEl) statusEl.textContent = "";
        return;
      }
    }
    if (errEl) errEl.textContent = "Timed out waiting for ChatGPT OAuth — try again";
    if (statusEl) statusEl.textContent = "";
  });
}

function wireMySevnUi() {
  document.getElementById("btn-github-oauth-save")?.addEventListener("click", () => {
    saveGithubOAuthCredentials();
  });

  document.getElementById("btn-github-oauth")?.addEventListener("click", async () => {
    const { res: statusRes, body: statusBody } = await api("/api/github/status");
    if (statusRes.ok && !statusBody.oauth_configured) {
      const saved = await saveGithubOAuthCredentials();
      if (!saved) return;
    }
    const { res, body } = await api("/api/github/oauth/start");
    if (!res.ok) {
      showMySevnGithubBanner(body.detail || "OAuth is not configured", "error");
      return;
    }
    if (body.authorize_url) {
      window.location.href = body.authorize_url;
    }
  });

  document.getElementById("btn-github-use-host")?.addEventListener("click", async () => {
    const { res, body } = await api("/api/github/use-host", { method: "POST", body: "{}" });
    if (!res.ok) {
      showMySevnGithubBanner(body.detail || "Could not use host GitHub account", "error");
      return;
    }
    await refreshGithubStatus();
    renderFieldSummary();
    showMySevnGithubBanner(
      body.login ? `Using host GitHub account @${body.login}` : "Host GitHub account linked",
      "success",
    );
  });

  document.getElementById("btn-github-disconnect")?.addEventListener("click", async () => {
    const { res, body } = await api("/api/github/disconnect", { method: "POST", body: "{}" });
    if (!res.ok) {
      showMySevnGithubBanner(body.detail || "Could not disconnect GitHub", "error");
      return;
    }
    document.getElementById("github_pat").value = "";
    await refreshGithubStatus();
    renderFieldSummary();
    showMySevnGithubBanner("GitHub disconnected — connect a different account below", "info");
  });

  document.getElementById("btn-github-pat-save")?.addEventListener("click", async () => {
    const errEl = document.getElementById("github-pat-error");
    const token = document.getElementById("github_pat")?.value?.trim() || "";
    if (!token) {
      if (errEl) errEl.textContent = "Enter a token first";
      return;
    }
    if (errEl) errEl.textContent = "";
    const { res, body } = await api("/api/github/token", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
    if (!res.ok) {
      if (errEl) errEl.textContent = body.detail || "Could not save token";
      return;
    }
    document.getElementById("github_pat").value = "";
    await refreshGithubStatus();
    renderFieldSummary();
    showMySevnGithubBanner(
      body.login ? `GitHub token saved for @${body.login}` : "GitHub token saved",
      "success",
    );
  });

  const backupModal = document.getElementById("backup-repo-modal");
  const showBackupModal = () => {
    if (!backupModal) return;
    backupModal.hidden = false;
    const errEl = document.getElementById("backup-repo-error");
    if (errEl) errEl.textContent = "";
  };
  const hideBackupModal = () => {
    if (backupModal) backupModal.hidden = true;
  };

  document.getElementById("btn-create-backup-repo")?.addEventListener("click", async () => {
    const nameInput = document.getElementById("backup-repo-name");
    const { res, body } = await api("/api/workspace-backup/default-name");
    if (res.ok && nameInput && body.name) {
      nameInput.value = body.name;
    }
    showBackupModal();
  });

  document.getElementById("btn-backup-cancel")?.addEventListener("click", hideBackupModal);
  backupModal?.addEventListener("click", (ev) => {
    if (ev.target?.classList?.contains("wizard-modal-backdrop")) hideBackupModal();
  });

  document.getElementById("btn-backup-create")?.addEventListener("click", async () => {
    const errEl = document.getElementById("backup-repo-error");
    const name = document.getElementById("backup-repo-name")?.value?.trim() || "";
    if (errEl) errEl.textContent = "";
    const { res, body } = await api("/api/workspace-backup/create", {
      method: "POST",
      body: JSON.stringify({ name, private: true }),
    });
    if (!res.ok) {
      if (errEl) errEl.textContent = body.detail || "Could not create repository";
      return;
    }
    const urlInput = document.getElementById("my_sevn_workspace_backup_url");
    if (urlInput && body.repo_url) {
      urlInput.value = body.repo_url;
      urlInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
    hideBackupModal();
    renderFieldSummary();
    showMySevnGithubBanner(`Created backup repo ${body.repo_url}`, "success");
  });
}

function handleGithubReturnQuery() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("github_connected") === "1") {
    showMySevnGithubBanner("GitHub connected successfully", "success");
    const stepIdx = STEPS.indexOf("my_sevn");
    if (stepIdx >= 0) showStep(stepIdx);
    params.delete("github_connected");
    const next = params.toString();
    const path = window.location.pathname + (next ? `?${next}` : "");
    window.history.replaceState({}, "", path);
  }
  const ghErr = params.get("github_error");
  if (ghErr) {
    showMySevnGithubBanner(`GitHub connection failed (${ghErr})`, "error");
    params.delete("github_error");
    const next = params.toString();
    const path = window.location.pathname + (next ? `?${next}` : "");
    window.history.replaceState({}, "", path);
  }
}

async function storeCredentials() {
  ensureGatewayTokenGenerated();
  const bot = document.getElementById("tg_bot_token")?.value || "";
  const apiId = document.getElementById("tg_api_id")?.value || "";
  const apiHash = document.getElementById("tg_api_hash")?.value || "";
  const phone = document.getElementById("tg_phone")?.value || "";
  const passphrase = document.getElementById("secrets_passphrase")?.value || "";
  const gatewayToken = document.getElementById("gateway_token_hidden")?.value || "";
  const payload = { bot_token: bot, gateway_token: gatewayToken };
  const providerKeys = collectProviderApiKeysForStore();
  if (providerKeys) {
    payload.provider_api_keys = providerKeys;
  }
  if (apiId.trim()) payload.telegram_api_id = apiId.trim();
  if (apiHash.trim()) payload.telegram_api_hash = apiHash.trim();
  if (phone.trim()) payload.telegram_phone = phone.trim();
  if (passphrase) payload.secrets_passphrase = passphrase;
  const { res, body } = await api("/api/credentials", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (res.ok) {
    await refreshCredentialsStatus();
  }
  return { res, body };
}

function wireSecretsUi() {
  const select = document.getElementById("secrets_type");
  const fileCard = document.getElementById("secrets-encrypted-file-panel");
  const baoCard = document.getElementById("secrets-openbao-panel");
  function updatePanels() {
    const v = select?.value || "encrypted_file";
    if (fileCard) fileCard.hidden = v !== "encrypted_file";
    if (baoCard) baoCard.hidden = v !== "openbao";
    renderFieldSummary();
  }
  select?.addEventListener("change", updatePanels);
  updatePanels();

  function updateResolvedPathHint() {
    const hint = document.getElementById("secrets_enc_path_resolved");
    if (!hint) return;
    const override = document.getElementById("secrets_enc_path")?.value?.trim();
    const workspace = document.getElementById("workspace_root")?.value?.trim() || ".";
    if (override) {
      hint.innerHTML = `Will be resolved to: <code>${escapeHtml(override.startsWith("/") || override.startsWith("~") ? override : workspace + "/" + override)}</code>`;
    } else {
      hint.innerHTML = `Default: <code>${escapeHtml(workspace)}/.sevn/secrets/store.enc</code>`;
    }
  }
  document.getElementById("secrets_enc_path")?.addEventListener("input", updateResolvedPathHint);
  document.getElementById("workspace_root")?.addEventListener("input", updateResolvedPathHint);
  updateResolvedPathHint();

  const pass = document.getElementById("secrets_passphrase");
  const confirm = document.getElementById("secrets_passphrase_confirm");
  const mismatch = document.getElementById("secrets_passphrase_mismatch");
  function checkMatch() {
    if (!pass || !confirm || !mismatch) return;
    const a = pass.value;
    const b = confirm.value;
    if (b && a !== b) {
      mismatch.style.display = "block";
      confirm.closest(".field")?.classList.add("invalid");
    } else {
      mismatch.style.display = "none";
      confirm.closest(".field")?.classList.remove("invalid");
    }
  }
  pass?.addEventListener("input", checkMatch);
  confirm?.addEventListener("input", checkMatch);
}

function computeNextStep() {
  if (currentStep >= STEPS.length - 1) return null;
  if (selectedProfile === "skip" || !selectedProfile) {
    return currentStep + 1;
  }
  for (let i = currentStep + 1; i < STEPS.length; i++) {
    const sid = STEPS[i];
    if (sid === "validate" || sid === "promote" || sid === "handoff") {
      return i;
    }
    if (!stepComplete(sid)) return i;
  }
  return STEPS.indexOf("validate");
}

async function validateCurrentStep() {
  const step = STEPS[currentStep];
  if (step === "my_sevn") {
    const name = fieldValue("agent.display_name");
    const { ok, message } = await validateField("agent.display_name", name);
    if (!ok) return { ok: false, message };
    const repo = fieldValue("my_sevn.repo_url");
    const repoCheck = await validateField("my_sevn.repo_url", repo);
    if (!repoCheck.ok) return repoCheck;
    const backupUrl = fieldValue("my_sevn.workspace_backup.repo_url");
    if (backupUrl) {
      const backupCheck = await validateField("my_sevn.workspace_backup.repo_url", backupUrl);
      if (!backupCheck.ok) return backupCheck;
    }
    const pat = document.getElementById("github_pat")?.value?.trim();
    if (pat) {
      const { res, body } = await api("/api/github/token", {
        method: "POST",
        body: JSON.stringify({ token: pat }),
      });
      if (!res.ok) return { ok: false, message: body.detail || "could not store GitHub token" };
      document.getElementById("github_pat").value = "";
      await refreshGithubStatus();
    }
  }
  if (step === "model") {
    const model = fieldValue("providers.tier_default.triager");
    const providers = collectAssignedProviderNames();
    const m = await validateField("providers.tier_default.triager", model);
    if (!m.ok) return m;
    if (!isUseMainModelForAll()) {
      for (const fieldId of MODEL_SLOT_FIELDS) {
        const v = fieldValue(fieldId);
        const r = await validateField(fieldId, v);
        if (!r.ok) return r;
      }
    }
    for (const name of providers) {
      const pKey = fieldValue(`wizard.provider_api_key.${name}`);
      if (name === "openai" && !String(pKey || "").trim() && openaiOauthConnected) {
        continue;
      }
      const pk = await validateField(`wizard.provider_api_key.${name}`, pKey);
      if (!pk.ok) return pk;
    }
    const credBody = { provider_api_keys: collectProviderApiKeysForStore() };
    const { res, body } = await api("/api/credentials", {
      method: "POST",
      body: JSON.stringify(credBody),
    });
    if (!res.ok) return { ok: false, message: body.detail || "could not store API key" };
    await refreshCredentialsStatus();
  }
  if (step === "channels") {
    if (!fieldValue("wizard.telegram_create_new_bot")) {
      const username = fieldValue("wizard.telegram_bot_username");
      const u = await validateField(
        "wizard.telegram_bot_username",
        username,
        channelsValidationContext(),
      );
      if (!u.ok) return u;
    }
    const token = fieldValue("wizard.telegram_bot_token");
    const t = await validateField("wizard.telegram_bot_token", token);
    if (!t.ok) return t;
    const owner = fieldValue("wizard.telegram_owner_user_id");
    const o = await validateField("wizard.telegram_owner_user_id", owner);
    if (!o.ok) return o;
    const { res, body } = await storeCredentials();
    if (!res.ok) return { ok: false, message: body.detail || "could not store secrets" };
  }
  if (step === "secrets") {
    const backend = fieldValue("secrets_backend.type") || "encrypted_file";
    if (backend === "encrypted_file") {
      const pass = document.getElementById("secrets_passphrase")?.value || "";
      const confirm = document.getElementById("secrets_passphrase_confirm")?.value || "";
      if (!pass) {
        return {
          ok: false,
          message: "Passphrase is required for the encrypted_file backend.",
        };
      }
      if (pass !== confirm) {
        return { ok: false, message: "Passphrase and confirmation do not match." };
      }
      const verified = await verifyPassphraseWithRetries(pass);
      if (!verified.ok) {
        return { ok: false, message: verified.message };
      }
      const { res, body } = await storeCredentials();
      if (!res.ok)
        return { ok: false, message: body.detail || "could not store passphrase" };
    }
  }
  return { ok: true, message: "" };
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function refreshInstallPlan() {
  const panel = document.getElementById("install-plan-panel");
  const summary = document.getElementById("install-plan-summary");
  const list = document.getElementById("install-plan-steps");
  if (!panel || !summary || !list) return;
  const { res, body } = await api("/api/install-plan", {
    method: "POST",
    body: JSON.stringify(buildPayload()),
  });
  if (!res.ok) {
    panel.hidden = true;
    return;
  }
  installPlanData = body;
  const steps = body.steps || [];
  const fatal = body.fatal_count || 0;
  const warn = body.warn_count || 0;
  if (!steps.length) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  summary.textContent = `${steps.length} install step${steps.length === 1 ? "" : "s"} (${fatal} required, ${warn} optional). Run validation first, then install before promoting.`;
  list.innerHTML = "";
  for (const step of steps) {
    const li = document.createElement("li");
    const action = step.action || {};
    const tag = action.fatal ? "required" : "optional";
    li.className = action.fatal ? "fatal" : "";
    li.textContent = `${step.capability_id} — ${action.id || "action"} (${tag})`;
    list.appendChild(li);
  }
}

function appendInstallLogLine(text) {
  const log = document.getElementById("install-progress-log");
  if (!log) return;
  log.hidden = false;
  log.textContent = log.textContent ? `${log.textContent}\n${text}` : text;
  log.scrollTop = log.scrollHeight;
}

function updatePromoteGate() {
  const saveBtn = document.getElementById("btn-save");
  const promoteBanner = document.getElementById("promote-banner");
  if (!saveBtn || !promoteBanner) return;
  if (fatalInstallFailed) {
    saveBtn.disabled = true;
    promoteBanner.textContent =
      "A required install failed — fix errors in the install log or adjust capabilities, then re-run installs.";
    promoteBanner.className = "banner banner-error";
    return;
  }
  saveBtn.disabled = false;
  if (validationPassed) {
    promoteBanner.textContent = installRunComplete
      ? "Validation and installs complete — ready to deploy."
      : "Validation passed. Run optional installs on the Validate step, then deploy.";
    promoteBanner.className = "banner banner-success";
  } else {
    promoteBanner.textContent = "Ready when validation passes.";
    promoteBanner.className = "banner banner-info";
  }
}

async function runInstallPlan() {
  const btn = document.getElementById("btn-run-installs");
  const log = document.getElementById("install-progress-log");
  if (log) {
    log.hidden = false;
    log.textContent = "Starting installs…";
  }
  if (btn) btn.disabled = true;
  fatalInstallFailed = false;
  installRunComplete = false;
  await storeCredentials();
  let res;
  try {
    res = await fetch("/api/install-run", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPayload()),
    });
  } catch (err) {
    appendInstallLogLine(String(err));
    if (btn) btn.disabled = false;
    updatePromoteGate();
    return;
  }
  if (!res.ok || !res.body) {
    appendInstallLogLine(`Install run failed: HTTP ${res.status}`);
    if (btn) btn.disabled = false;
    updatePromoteGate();
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      let event;
      try {
        event = JSON.parse(line);
      } catch (_e) {
        appendInstallLogLine(line);
        continue;
      }
      if (event.type === "log" && event.line) {
        appendInstallLogLine(`[${event.action_id || "install"}] ${event.line}`);
      } else if (event.type === "start") {
        appendInstallLogLine(`→ ${event.action_id || event.capability_id || "install"}`);
      } else if (event.type === "end") {
        const status = event.status || "unknown";
        appendInstallLogLine(
          `✓ ${event.action_id || "install"}: ${status}${event.fatal && status === "failed" ? " (required)" : ""}`,
        );
        if (status === "failed" && event.fatal) {
          fatalInstallFailed = true;
        }
      } else if (event.type === "error") {
        appendInstallLogLine(`ERROR: ${event.detail || JSON.stringify(event)}`);
        fatalInstallFailed = true;
      }
    }
  }
  installRunComplete = true;
  if (btn) btn.disabled = false;
  await refreshInstallPlan();
  updatePromoteGate();
}

async function runValidateAll() {
  const banner = document.getElementById("validate-banner");
  const list = document.getElementById("validation-results");
  list.classList.add("validation-results");
  banner.textContent = "Running schema + live validation…";
  banner.className = "banner banner-info";
  list.innerHTML = "";
  await storeCredentials();
  const { res, body } = await api("/api/validate-all", {
    method: "POST",
    body: JSON.stringify(buildPayload()),
  });
  if (!res.ok) {
    validationPassed = false;
    const count = (body.errors || []).length;
    banner.textContent = count
      ? `Validation failed — ${count} field${count === 1 ? "" : "s"} need fixing`
      : body.detail || "Validation failed";
    banner.className = "banner banner-error";
    for (const err of body.errors || []) {
      const rowEl = document.createElement("div");
      rowEl.className = "row fail";
      rowEl.innerHTML = `<strong>${escapeHtml(err.loc)}</strong> — ${escapeHtml(err.msg)}`;
      list.appendChild(rowEl);
    }
    if (!(body.errors || []).length) {
      const rowEl = document.createElement("div");
      rowEl.className = "row fail";
      rowEl.textContent = body.detail || "Unknown validation failure";
      list.appendChild(rowEl);
    }
    updatePromoteGate();
    return false;
  }
  validationPassed = Boolean(body.ok);
  banner.textContent = body.ok
    ? "Validation passed (warnings may remain)"
    : "Validation reported errors — see details below";
  banner.className = body.ok ? "banner banner-success" : "banner banner-error";
  for (const row of body.live_validation || []) {
    const rowEl = document.createElement("div");
    rowEl.className = `row ${row.ok ? "ok" : "fail"}`;
    const hint = row.hint ? ` <em>(${escapeHtml(row.hint)})</em>` : "";
    rowEl.innerHTML = `<strong>${escapeHtml(row.check_id)}</strong> — ${escapeHtml(row.detail)}${hint}`;
    list.appendChild(rowEl);
  }
  for (const row of body.install_status || []) {
    const rowEl = document.createElement("div");
    const pending = row.satisfied ? "installed" : "pending";
    rowEl.className = `row ${row.ok ? "ok" : "fail"}`;
    const hint = row.hint ? ` <em>(${escapeHtml(row.hint)})</em>` : "";
    rowEl.innerHTML = `<strong>${escapeHtml(row.capability_id)}</strong> — ${escapeHtml(row.detail)} (${pending})${hint}`;
    list.appendChild(rowEl);
  }
  await refreshInstallPlan();
  updatePromoteGate();
  return body.ok;
}

async function saveConfig() {
  if (fatalInstallFailed) {
    alert("A required install failed. Re-run installs on the Validate step before deploying.");
    return;
  }
  const banner = document.getElementById("promote-banner");
  banner.textContent = "Saving…";
  banner.className = "banner banner-info";
  await storeCredentials();
  const { res, body } = await api("/api/save", {
    method: "POST",
    body: JSON.stringify(buildPayload()),
  });
  if (!res.ok) {
    banner.textContent = body.detail || "Save failed";
    banner.className = "banner banner-error";
    return;
  }
  banner.textContent = body.message || "Saved";
  banner.className = "banner banner-success";
  configSaved = true;
  document.body.dataset.configSaved = "1";
  const handoff = document.getElementById("handoff-path");
  if (handoff) handoff.textContent = body.sevn_json || "";
  const log = document.getElementById("handoff-log");
  if (log) {
    if (body.services_restart_error) {
      log.textContent = `Service restart failed: ${body.services_restart_error}`;
    } else if (body.services_restart) {
      const lines = body.services_restart.lines || [];
      log.textContent = lines.length
        ? lines.join("\n")
        : body.services_restart.message || JSON.stringify(body.services_restart, null, 2);
    } else if (body.daemon_install_error) {
      log.textContent = `Daemon install: ${body.daemon_install_error}`;
    }
  }
  showStep(STEPS.indexOf("handoff"));
}

async function checkWorkspace() {
  const path = document.getElementById("workspace_root")?.value || ".";
  const { body } = await api(`/api/check-workspace?path=${encodeURIComponent(path)}`);
  const el = document.getElementById("workspace-status");
  if (!el) return;
  if (!body.exists) {
    el.textContent = "Directory does not exist yet — it will be created on promote.";
    return;
  }
  const md = (body.files?.md_files || []).join(", ") || "none";
  el.textContent = `Found sevn.json=${body.has_config}, draft=${body.has_draft}, markdown: ${md}`;
}

function updateSecretsKeystoreReuse() {
  const panel = document.getElementById("secrets-keystore-reuse");
  if (!panel) return;
  const show = reuseMode && hasKeystore;
  panel.hidden = !show;
}

async function replaceKeystore() {
  const { res, body } = await api("/api/replace-keystore", { method: "POST", body: "{}" });
  if (!res.ok) {
    alert(body.detail || "Failed to replace keystore");
    return;
  }
  hasKeystore = false;
  updateSecretsKeystoreReuse();
  alert("Keystore removed — re-enter credentials on the Channels step.");
}

function renderInstallCandidates(discover) {
  const banner = document.getElementById("install-gate-banner");
  const list = document.getElementById("install-candidate-list");
  if (!banner || !list) return;
  const homes = discover.candidates || [];
  selectedInstallHome =
    discover.active_has_config ? discover.active_home : homes[0]?.home || discover.active_home;
  const partial = Boolean(discover.active_has_workspace_artifacts && !discover.active_has_config);
  const keystoreNote = discover.active_has_keystore ? " Saved secrets were found." : "";
  banner.hidden = false;
  banner.textContent = homes.length
    ? `Found ${homes.length} installed operator home${homes.length === 1 ? "" : "s"}.`
    : partial
      ? `Found a previous onboarding workspace under ${discover.active_home}/workspace.${keystoreNote}`
      : `Found data under ${discover.active_home}.`;
  if (homes.length <= 1) {
    list.hidden = true;
    return;
  }
  list.hidden = false;
  list.innerHTML = "<p class=\"hint\" style=\"margin-bottom:8px\">Pick another home:</p>";
  homes.forEach((row, idx) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-ghost btn-sm";
    btn.style.display = "block";
    btn.style.marginBottom = "6px";
    btn.textContent = `${idx + 1}. ${row.home}`;
    btn.addEventListener("click", () => {
      selectedInstallHome = row.home;
      list.querySelectorAll("button").forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
    });
    list.appendChild(btn);
  });
}

async function saveGithubOAuthCredentials() {
  const errEl = document.getElementById("github-oauth-config-error");
  const clientId = document.getElementById("github_oauth_client_id")?.value?.trim() || "";
  const clientSecret = document.getElementById("github_oauth_client_secret")?.value?.trim() || "";
  if (!clientId || !clientSecret) {
    if (errEl) errEl.textContent = "Enter both OAuth client ID and secret";
    return false;
  }
  if (errEl) errEl.textContent = "";
  const { res, body } = await api("/api/github/oauth/credentials", {
    method: "POST",
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
  });
  if (!res.ok) {
    if (errEl) errEl.textContent = body.detail || "Could not save OAuth credentials";
    return false;
  }
  document.getElementById("github_oauth_client_secret").value = "";
  await refreshGithubStatus();
  showMySevnGithubBanner("GitHub OAuth app credentials saved for this session", "success");
  return true;
}

async function resolveInstall(action, confirm) {
  const payload = { action, home: selectedInstallHome };
  if (confirm) payload.confirm = confirm;
  const { res, body } = await api("/api/resolve-install", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    alert(body.detail || "Install resolution failed");
    return null;
  }
  reuseMode = Boolean(body.reuse);
  return body;
}

async function finishReuseLanding() {
  const existingBody = await loadExisting();
  const unlocked = await ensureKeystoreUnlocked(existingBody);
  if (!unlocked) {
    showStep(STEPS.indexOf("existing"));
    return;
  }
  await refreshCredentialsStatus();
  hasKeystore = Boolean(installGate?.has_keystore);
  updateSecretsKeystoreReuse();
  renderProfiles();
  await checkWorkspace();
  showStep(STEPS.indexOf("profile"));
}

async function onInstallReuse() {
  const body = await resolveInstall("reuse");
  if (!body) return;
  await finishReuseLanding();
}

async function onInstallWipeConfirm() {
  const typed = document.getElementById("install-wipe-input")?.value || "";
  if (typed.trim() !== "DELETE") {
    alert('Type DELETE to confirm wipe');
    return;
  }
  const body = await resolveInstall("wipe", "DELETE");
  if (!body) return;
  reuseMode = false;
  freshInstall = true;
  hasKeystore = false;
  updateSecretsKeystoreReuse();
  applyConfigToForm({}, { useFormDefaults: false });
  clearWizardCredentialFields();
  document.getElementById("github_pat").value = "";
  document.getElementById("github_oauth_client_id").value = "";
  document.getElementById("github_oauth_client_secret").value = "";
  const ghStatus = document.getElementById("github-status-text");
  if (ghStatus) {
    ghStatus.textContent = "Not connected";
    ghStatus.style.color = "var(--sevn-fg-muted)";
  }
  document.getElementById("install-wipe-confirm")?.setAttribute("hidden", "");
  showStep(STEPS.indexOf("profile"));
}

function wireInstallGateUi() {
  document.getElementById("btn-install-reuse")?.addEventListener("click", () => {
    onInstallReuse();
  });
  document.getElementById("btn-install-wipe")?.addEventListener("click", () => {
    document.getElementById("install-wipe-confirm")?.removeAttribute("hidden");
  });
  document.getElementById("btn-install-wipe-confirm")?.addEventListener("click", () => {
    onInstallWipeConfirm();
  });
  document.getElementById("btn-replace-keystore")?.addEventListener("click", () => {
    replaceKeystore();
  });
}

function configValueForField(cfg, fieldId) {
  if (fieldId === "secrets_backend.type") {
    const chain = cfg.secrets_backend?.chain;
    if (Array.isArray(chain) && chain[0]?.type) return chain[0].type;
    return undefined;
  }
  const parts = fieldId.split(".");
  let cur = cfg;
  for (const p of parts) {
    if (!cur || typeof cur !== "object") return undefined;
    cur = cur[p];
  }
  return cur;
}

function applyConfigToForm(cfg, options = {}) {
  const useFormDefaults = options.useFormDefaults === true;
  lastAppliedConfig = cfg && typeof cfg === "object" ? cfg : {};
  if (cfg.onboarding?.applied_profile) {
    selectedProfile = cfg.onboarding.applied_profile;
    applyProfileToModel(selectedProfile);
  } else if (reuseMode) {
    selectedProfile = "skip";
  }
  const defaults = meta?.defaults || {};
  for (const el of document.querySelectorAll("[data-field-id]")) {
    const id = el.getAttribute("data-field-id");
    if (!id || id.startsWith("wizard.")) continue;
    let cur = configValueForField(cfg, id);
    if ((cur === undefined || cur === null) && useFormDefaults) {
      cur = configValueForField(defaults, id);
    }
    if (cur === undefined || cur === null) continue;
    if (el.type === "checkbox") el.checked = Boolean(cur);
    else if (el.type !== "password") el.value = cur;
  }
  // ``wizard.*`` fields are derived (the wizard collects one value, the
  // backend fans it into a richer config shape). The main loop above
  // skips them on prefill, so reverse-map any with a known config path
  // back into the form so reuse / existing-config flows don't ask the
  // operator to re-enter values that are already in ``sevn.json``.
  // Reference: operator chat 2026-05-27 — Telegram owner user id was not
  // extracted from existing ``channels.telegram.allowed_users`` on reuse.
  const ownerInput = document.querySelector(
    '[data-field-id="wizard.telegram_owner_user_id"]',
  );
  if (ownerInput && (ownerInput.value === "" || ownerInput.value === undefined)) {
    const allowedUsers = cfg.channels?.telegram?.allowed_users;
    if (Array.isArray(allowedUsers) && allowedUsers.length > 0) {
      const first = allowedUsers[0];
      if (first !== null && first !== undefined) {
        ownerInput.value = String(first);
      }
    }
  }
  const tunnelMode = cfg.infrastructure?.tunnel?.mode || "none";
  const hidden = document.getElementById("tunnel_mode");
  if (hidden) hidden.value = tunnelMode;
  document.querySelectorAll('input[name="tunnel_mode_ui"]').forEach((r) => {
    r.checked = r.value === tunnelMode;
    r.closest(".tunnel-option")?.classList.toggle("selected", r.checked);
  });
  const sandboxMode = cfg.sandbox?.mode || "";
  const sbHidden = document.getElementById("sandbox_mode");
  if (sbHidden) sbHidden.value = sandboxMode;
  document.querySelectorAll('input[name="sandbox_mode_ui"]').forEach((r) => {
    r.checked = r.value === sandboxMode;
    r.closest(".sandbox-option")?.classList.toggle("selected", r.checked);
  });
  const prefRaw = configValueForField(cfg, "onboarding.personality.preferences");
  if (prefRaw !== undefined && prefRaw !== null) {
    applyPersonalityPreferencesToCheckboxes(prefRaw);
  }
  document.getElementById("secrets_type")?.dispatchEvent(new Event("change"));
  document.getElementById("secrets_enc_path")?.dispatchEvent(new Event("input"));
  const unify = document.getElementById("use_main_model_for_all");
  if (unify && useFormDefaults) {
    const providers = cfg.providers || {};
    if (providers.use_main_model_for_all === false) unify.checked = false;
    else unify.checked = true;
    modelSlotsWereUnified = unify.checked;
  } else if (unify) {
    modelSlotsWereUnified = unify.checked;
  }
  updateModelSlotsPanel();
  renderProfiles();
  if (capabilitiesData) {
    renderCapabilitiesPanel();
  }
  renderFieldSummary();
}

function wireModelUnifyUi() {
  const unify = document.getElementById("use_main_model_for_all");
  const triager = document.getElementById("triager_model");
  if (unify) {
    unify.addEventListener("change", () => updateModelSlotsPanel());
  }
  if (triager) {
    triager.addEventListener("input", () => {
      if (isUseMainModelForAll()) syncMainModelToSlots(false);
      updateProviderKeyFields();
      renderFieldSummary();
    });
  }
  document.querySelectorAll(".model-slot-input").forEach((el) => {
    el.addEventListener("input", () => updateProviderKeyFields());
  });
  updateModelSlotsPanel();
}

async function loadExisting() {
  const { res, body } = await api("/api/existing-config");
  if (!res.ok) {
    alert(body.detail || "Could not load existing configuration");
    return body;
  }
  reuseMode = Boolean(body.reuse);
  hasKeystore = Boolean(body.has_keystore);
  updateSecretsKeystoreReuse();
  const hasPromoted = Boolean(body.exists);
  const resumeDraft = Boolean(body.draft_exists) && !reuseMode;
  const prefill = shouldPrefillFromExisting(body);
  const useFormDefaults = reuseMode || hasPromoted;
  let cfg = {};
  if (reuseMode && body.config && Object.keys(body.config).length) {
    cfg = body.config;
  } else if (resumeDraft) {
    cfg = body.draft || {};
  } else if (hasPromoted) {
    cfg = body.config || {};
  }
  applyConfigToForm(cfg, { useFormDefaults });
  if (prefill && body.wizard_secrets && Object.keys(body.wizard_secrets).length) {
    applySecretsToForm(body.wizard_secrets);
  } else if (!prefill) {
    clearWizardCredentialFields();
  }
  return body;
}

function buildSidebar() {
  const nav = document.getElementById("stepsNav");
  if (!nav) return;
  nav.innerHTML = "";
  STEPS.forEach((name, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "wizard-nav-step";
    btn.innerHTML = `
      <span class="wizard-nav-num">${String(i + 1).padStart(2, "0")}</span>
      <span class="wizard-nav-name">${STEP_LABELS[name] || name}</span>
      <svg class="wizard-nav-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>`;
    btn.addEventListener("click", () => showStep(i));
    nav.appendChild(btn);
  });
}

async function init() {
  if (document.body.dataset.onboardingExited === "1") return;
  if (typeof initSevnTheme === "function") {
    initSevnTheme({ cycleButtonSelector: "#themeToggle" });
  }
  wireTunnelUi();
  wireSandboxUi();
  wireSecretsUi();
  wireGatewayTokenUi();
  wireInstallGateUi();
  wireExitConfirmUi();
  wireModelUnifyUi();
  wirePersonalityUi();

  document.querySelectorAll("[data-field-id]").forEach((el) => {
    el.addEventListener("blur", onBlurValidate);
    el.addEventListener("input", () => renderFieldSummary());
    el.addEventListener("change", () => renderFieldSummary());
  });

  document.getElementById("btn-prev")?.addEventListener("click", () => {
    if (currentStep > 0) showStep(currentStep - 1);
  });
  document.getElementById("btn-next")?.addEventListener("click", async () => {
    const v = await validateCurrentStep();
    if (!v.ok) {
      alert(v.message || "Complete required fields on this step");
      return;
    }
    const next = computeNextStep();
    if (next !== null) showStep(next);
  });
  document.getElementById("btn-profile-next")?.addEventListener("click", () => {
    document.getElementById("btn-next")?.click();
  });
  document.getElementById("btn-validate")?.addEventListener("click", runValidateAll);
  document.getElementById("btn-run-installs")?.addEventListener("click", runInstallPlan);
  document.getElementById("btn-save")?.addEventListener("click", saveConfig);
  document.getElementById("btn-store-credentials")?.addEventListener("click", async () => {
    const { res, body } = await storeCredentials();
    if (!res.ok) alert(body.detail || "Failed to store secrets");
    else await refreshCredentialsStatus();
  });
  document.getElementById("btn-run-doctor")?.addEventListener("click", async () => {
    const log = document.getElementById("handoff-log");
    log.textContent = "Running sevn doctor…";
    const { body } = await api("/api/run-doctor", { method: "POST", body: "{}" });
    log.textContent = body.stdout || body.stderr || JSON.stringify(body, null, 2);
  });
  document.getElementById("btn-run-gateway")?.addEventListener("click", async () => {
    const log = document.getElementById("handoff-log");
    log.textContent = configSaved ? "Restarting gateway and proxy…" : "Starting gateway…";
    const { res, body } = await api("/api/run-gateway", { method: "POST", body: "{}" });
    if (!res.ok) {
      log.textContent = body.detail || JSON.stringify(body, null, 2);
      return;
    }
    if (body.mode === "daemon" && Array.isArray(body.lines) && body.lines.length) {
      log.textContent = body.lines.join("\n");
      return;
    }
    const lines = [body.message || "proxy + gateway restart requested"];
    for (const part of ["proxy", "gateway"]) {
      const row = body[part];
      if (!row || typeof row !== "object") continue;
      if (row.message) lines.push(`${part}: ${row.message}`);
      if (row.pid) lines.push(`${part} pid ${row.pid}`);
      if (row.log_path) lines.push(`${part} log ${row.log_path}`);
    }
    log.textContent = lines.join("\n");
  });
  document.getElementById("workspace_root")?.addEventListener("change", checkWorkspace);

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.target.matches("textarea") && STEPS[currentStep] !== "handoff") {
      if (currentStep < STEPS.length - 1) {
        ev.preventDefault();
        document.getElementById("btn-next")?.click();
      }
    }
  });

  const [{ body: metaBody }, { body: helpBody }, { body: discoverBody }] = await Promise.all([
    api("/api/meta"),
    api("/api/field-help"),
    api("/api/discover-install"),
  ]);
  meta = metaBody;
  fieldHelp = helpBody.fields || {};
  freshInstall = Boolean(metaBody.fresh_install);
  installGate = discoverBody;
  if (discoverBody.show_gate) {
    STEPS = ["existing", ...BASE_STEPS];
    renderInstallCandidates(discoverBody);
  } else {
    STEPS = [...BASE_STEPS];
  }
  buildSidebar();
  if (metaBody.sevn_json_path) {
    const badge = document.getElementById("configPathBadge");
    if (badge) badge.textContent = metaBody.sevn_json_path;
  }
  const oauthCallbackHint = document.getElementById("github_oauth_callback_hint");
  if (oauthCallbackHint && metaBody.onboard_port) {
    oauthCallbackHint.textContent =
      `http://127.0.0.1:${metaBody.onboard_port}/api/github/oauth/callback`;
  }
  if (metaBody.defaults) {
    const wr = document.getElementById("workspace_root");
    if (wr && metaBody.defaults.workspace_root) wr.value = metaBody.defaults.workspace_root;
  }
  wireFieldHelp();
  wireMySevnUi();
  wireOpenAiOAuthUi();
  wireProfileInspectorModal();
  wireChannelsUi();
  handleGithubReturnQuery();
  await refreshCapabilitiesUi();
  await refreshOpenAiOauthStatus();
  if (selectedProfile === "skip") {
    const def = pickDefaultValueProfile();
    if (def && def !== "skip") {
      selectedProfile = def;
      if (!freshInstall) {
        applyProfileToModel(def);
      }
    }
  }
  renderProfiles();
  if (discoverBody.show_gate) {
    showStep(0);
    document.body.dataset.wizardReady = "1";
    return;
  }
  const existingBody = await loadExisting();
  const unlocked = await ensureKeystoreUnlocked(existingBody);
  if (!unlocked) {
    showStep(0);
    document.body.dataset.wizardReady = "1";
    return;
  }
  await refreshCredentialsStatus();
  await refreshGithubStatus();
  const handoff = document.getElementById("handoff-path");
  if (handoff && !handoff.textContent && metaBody.sevn_json_path) {
    handoff.textContent = metaBody.sevn_json_path;
  }
  await checkWorkspace();
  if (reuseMode) {
    showStep(STEPS.indexOf("profile"));
  } else {
    showStep(0);
  }
  document.body.dataset.wizardReady = "1";
}

init();
