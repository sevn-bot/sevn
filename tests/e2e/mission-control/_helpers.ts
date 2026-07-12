// Mission Control Playwright helpers (MC W2 — login/skip, nav, screenshots, error gate).
//
// Headed debug reuses one browser session via `fixtures.ts` when
// `SEVN_MC_E2E_SHARED_SESSION=1` (`make mc-e2e-headed`). Helpers stay session-agnostic;
// `openDashboard` / `gotoTab` / `waitForPanelReady` work on whichever `page` the fixture
// provides (shared or per-test).

import fs from "node:fs/promises";
import path from "node:path";

import { expect, type Locator, type Page } from "@playwright/test";

const DEFAULT_PANEL_TIMEOUT_MS = 45_000;
const DEFAULT_LOCAL_PANEL_TIMEOUT_MS = 60_000;

/** True when running against an operator workspace (`make mc-e2e-local*`). */
export function isMcLocalMode(): boolean {
  return process.env.SEVN_MC_E2E_LOCAL === "1";
}

/** Panel/action timeout — override with `SEVN_MC_E2E_TIMEOUT_MS`; local mode defaults higher. */
export function mcE2ePanelTimeout(fallbackMs = DEFAULT_PANEL_TIMEOUT_MS): number {
  const env = process.env.SEVN_MC_E2E_TIMEOUT_MS?.trim();
  if (env) {
    const parsed = Number.parseInt(env, 10);
    if (!Number.isNaN(parsed) && parsed > 0) {
      return parsed;
    }
  }
  if (isMcLocalMode()) {
    return Math.max(fallbackMs, DEFAULT_LOCAL_PANEL_TIMEOUT_MS);
  }
  return fallbackMs;
}

/** Default snapshot policy: fixture CI runs compare; local operator workspaces skip. */
export function mcE2eSkipSnapshot(explicit?: boolean): boolean {
  if (explicit !== undefined) {
    return explicit;
  }
  if (process.env.SEVN_MC_E2E_SNAPSHOT === "1") {
    return false;
  }
  return isMcLocalMode();
}

/** Harness report: local operator runs are contract-only smoke (data-path deferred). */
export function mcE2eContractOnlyMode(): boolean {
  return isMcLocalMode();
}

/** Harness report: operator workspace seed skipped unless `SEVN_MC_SEED=1`. */
export function mcE2eSeedSkipped(): boolean {
  return isMcLocalMode() && process.env.SEVN_MC_SEED !== "1";
}

/** True when the page is already on an authenticated Mission Control shell. */
export async function isDashboardReady(page: Page): Promise<boolean> {
  try {
    const url = new URL(page.url());
    if (!url.pathname.startsWith("/mission")) {
      return false;
    }
    const tabs = page.locator("#tabs");
    if ((await tabs.count()) === 0 || !(await tabs.isVisible())) {
      return false;
    }
    const loginPanel = page.locator("#login-panel");
    if (await loginPanel.isVisible()) {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

/** Open the Mission Control SPA entrypoint (no-op when already authenticated on `/mission/`). */
export async function openDashboard(page: Page): Promise<void> {
  if (await isDashboardReady(page)) {
    return;
  }
  await page.goto("/mission/");
  await page.waitForSelector("#tabs");
}

/** Skip login on loopback (`local_open`) or password-login when `SEVN_MC_PASSWORD` is set. */
export async function ensureAuth(page: Page): Promise<void> {
  const password = process.env.SEVN_MC_PASSWORD;
  const loginPanel = page.locator("#login-panel");

  if (await isDashboardReady(page)) {
    return;
  }

  if (password) {
    await page.waitForFunction(
      () => {
        const panel = document.querySelector("#login-panel") as HTMLElement | null;
        return panel && !panel.hidden;
      },
      { timeout: 15_000 },
    );
    await page.locator("#login-password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(loginPanel).toBeHidden({ timeout: 15_000 });
    await page.waitForSelector("#tabs");
    return;
  }

  await page.waitForFunction(
    () => {
      const panel = document.querySelector("#login-panel") as HTMLElement | null;
      return !panel || panel.hidden;
    },
    { timeout: 15_000 },
  );
  await expect(loginPanel).toBeHidden();
}

async function assertPanelNoError(panel: Locator, timeout: number): Promise<void> {
  const errorEl = panel.locator("p.error");
  try {
    await expect(errorEl).toHaveCount(0, { timeout });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (message.includes("has been closed") || message.includes("Target page")) {
      throw err;
    }
    try {
      if ((await errorEl.count()) > 0) {
        const text = (await errorEl.first().textContent())?.trim() || "(empty error panel)";
        throw new Error(`panel error: ${text}`);
      }
    } catch (inner) {
      const innerMessage = inner instanceof Error ? inner.message : String(inner);
      if (innerMessage.includes("has been closed") || innerMessage.includes("Target page")) {
        throw err;
      }
      throw inner;
    }
    throw err;
  }
}

/** Wait until the active tab panel has finished loading (card visible, no spinners/errors). */
export async function waitForPanelReady(
  page: Page,
  options?: { timeout?: number },
): Promise<Locator> {
  const timeout = options?.timeout ?? mcE2ePanelTimeout();
  const panel = page.locator("#content > article.card");

  await expect(panel).toBeVisible({ timeout });
  await expect(panel.locator("h2")).toBeVisible({ timeout });
  await expect(panel).not.toContainText("Loading…", { timeout });
  await expect(panel).not.toContainText("Loading span…", { timeout });
  await assertPanelNoError(panel, timeout);

  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {
    // MC may keep long-lived connections; networkidle is best-effort.
  });

  // Overview badges refresh after the card shell renders — wait for stable health text.
  const badges = page.locator(".mission-overview-badges");
  if (await badges.count()) {
    await expect(badges).not.toContainText("Loading", { timeout });
    await page.waitForFunction(
      () => {
        const el = document.querySelector(".mission-overview-badges");
        if (!el) return true;
        const text = el.textContent || "";
        return !text.includes("Loading") && !/\d{2,} degraded degraded/.test(text);
      },
      { timeout: 10_000 },
    ).catch(() => undefined);
  }

  await page.waitForTimeout(250);

  return panel;
}

/** Normalize `/mission/…` pathnames for tab comparisons. */
function missionPathname(url: string): string {
  const path = new URL(url).pathname.replace(/\/$/, "");
  return path || "/mission";
}

/** True when `page` is already routed to the dashboard tab slug. */
function isOnMissionTab(url: string, slug: string): boolean {
  const path = missionPathname(url);
  const target = `/mission/${slug}`.replace(/\/$/, "");
  if (path === target) {
    return true;
  }
  if (slug === "overview" && (path === "/mission" || path === "/mission/overview")) {
    return true;
  }
  return false;
}

/** Client-side tab switch — avoids full reload so `/ws/dashboard` stays connected. */
async function navigateMissionTab(page: Page, href: string): Promise<void> {
  await page.evaluate((path) => {
    history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, href);
}

/** Navigate to a dashboard tab by slug and wait for the active panel. */
export async function gotoTab(page: Page, slug: string): Promise<void> {
  const href = `/mission/${slug}`;
  if (isOnMissionTab(page.url(), slug)) {
    await waitForPanelReady(page);
    return;
  }

  const link = page.locator(`.sidebar__item[href="${href}"]`);
  if (!(await link.isVisible())) {
    const group = page.locator(`.sidebar__group:has(.sidebar__item[href="${href}"])`);
    const header = group.locator(".sidebar__group-header");
    if (await header.isVisible()) {
      await header.click();
    }
  }
  await navigateMissionTab(page, href);
  await expect(link).toHaveAttribute("aria-current", "page");
  await waitForPanelReady(page);
}

/** Capture a full-page PNG under `test-results/mission-control/<slug>/`. */
export async function shot(page: Page, slug: string, step: string): Promise<void> {
  const dir = path.join("test-results", "mission-control", slug);
  await fs.mkdir(dir, { recursive: true });
  await page.screenshot({
    path: path.join(dir, `${step}.png`),
    fullPage: true,
  });
}

type ApiError = { url: string; status: number };

type ErrorGateState = {
  consoleErrors: string[];
  apiErrors: ApiError[];
  installed: boolean;
  sinceMs: number;
};

const errorGates = new WeakMap<Page, ErrorGateState>();

function gateState(page: Page): ErrorGateState {
  let state = errorGates.get(page);
  if (!state) {
    state = { consoleErrors: [], apiErrors: [], installed: false, sinceMs: Date.now() };
    errorGates.set(page, state);
  }
  return state;
}

/** Clear accumulated console/API errors — call at the start of each shared-session test. */
export function resetErrorGate(page: Page): void {
  const state = gateState(page);
  state.consoleErrors.length = 0;
  state.apiErrors.length = 0;
  state.sinceMs = Date.now();
}

function formatErrorGateFailure(state: ErrorGateState): string {
  const parts: string[] = [];
  if (state.consoleErrors.length > 0) {
    parts.push(`console (${state.consoleErrors.length}): ${state.consoleErrors[0]}`);
  }
  if (state.apiErrors.length > 0) {
    const first = state.apiErrors[0];
    parts.push(`api (${state.apiErrors.length}): ${first.status} ${first.url}`);
  }
  return parts.join(" | ") || "unknown error-gate failure";
}

/** Collect console errors and `/api/v1/*` responses with status ≥ 400. */
export function installErrorGate(page: Page): { assertNoErrors: () => void } {
  const state = gateState(page);
  resetErrorGate(page);

  if (!state.installed) {
    state.installed = true;
    page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const text = msg.text();
      // Mission Control CSP blocks CDN fonts/xterm in headless runs — not app failures.
      if (text.includes("Refused to load") && text.includes("Content Security Policy")) {
        return;
      }
      gateState(page).consoleErrors.push(text);
    });

    page.on("response", (resp) => {
      const url = resp.url();
      if (!url.includes("/api/v1/") || resp.status() < 400) {
        return;
      }
      gateState(page).apiErrors.push({ url, status: resp.status() });
    });
  }

  return {
    assertNoErrors() {
      const detail = formatErrorGateFailure(state);
      expect(
        state.consoleErrors,
        state.consoleErrors.length
          ? `console errors: ${detail}\n${state.consoleErrors.join("\n")}`
          : "console errors",
      ).toEqual([]);
      expect(
        state.apiErrors,
        state.apiErrors.length
          ? `api errors: ${detail}\n${JSON.stringify(state.apiErrors, null, 2)}`
          : "api errors",
      ).toEqual([]);
    },
  };
}

const VOLATILE_TEXT = /\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}|UUID:[a-f0-9-]{36}|[0-9a-f]{24,}/gi;
const VOLATILE_ATTRS = ["data-span-id", "data-session-id", "data-turn-id", "id"];

/** Strip volatile attributes/text for deterministic `toMatchSnapshot` comparisons. */
export async function normalizedDom(locator: Locator): Promise<string> {
  return locator.evaluate(
    (el, attrNames) => {
      const clone = el.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("*").forEach((node) => {
        if (!(node instanceof HTMLElement)) return;
        for (const name of attrNames) {
          node.removeAttribute(name);
        }
      });
      for (const name of attrNames) {
        clone.removeAttribute(name);
      }
      return clone.innerText.replace(/\s+/g, " ").trim();
    },
    VOLATILE_ATTRS,
  ).then((text) => text.replace(VOLATILE_TEXT, "<volatile>"));
}
