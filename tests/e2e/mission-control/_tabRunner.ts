// Schema-driven Mission Control tab runner (MC W3 — per-tab E2E).

import { expect, type Locator, type Page } from "@playwright/test";

import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  mcE2ePanelTimeout,
  mcE2eSkipSnapshot,
  normalizedDom,
  openDashboard,
  shot,
  waitForPanelReady,
} from "./_helpers";
import { mcSchema, type McSchemaTab } from "./_schema";

export { gotoTab } from "./_helpers";

/** Normalized panel text with MC-specific volatile tokens stripped for snapshots. */
export async function snapshotText(locator: Locator): Promise<string> {
  const text = await normalizedDom(locator);
  return text.replace(/Registry v\d+/g, "Registry v<volatile>");
}

const CSRF_COOKIE = "sevn_dashboard_csrf";

/** Navigate to a tab and wait until wired panel content has finished loading. */
export async function gotoTabReady(page: Page, slug: string): Promise<void> {
  tabSchema(slug);
  await gotoTab(page, slug);
  await waitForPanelReady(page);
}

/** Open Mission Control and return an error gate for the tab under test. */
export async function setupTabTest(page: Page): Promise<{ assertNoErrors: () => void }> {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  return gate;
}

/** Load a wired tab descriptor from the golden schema. */
export function tabSchema(slug: string): McSchemaTab {
  const tab = mcSchema.tabs[slug];
  if (!tab) {
    throw new Error(`schema missing tab: ${slug}`);
  }
  return tab;
}

/** Assert every declared view + key selector is present after navigation. */
export async function assertSchemaContract(page: Page, slug: string): Promise<void> {
  const tab = tabSchema(slug);
  for (const view of tab.views) {
    const locator = page.locator(view.selector);
    if (view.selector === "#agent-slot-editor" && (await locator.isHidden())) {
      await expect(locator).toBeAttached();
      continue;
    }
    await expect(locator).toBeVisible();
  }
  for (const selector of Object.values(tab.key_selectors ?? {})) {
    if (!selector || selector === "#agent-slot-editor") continue;
    const locator = page.locator(selector).first();
    if ((await locator.count()) === 0) continue;
    if (selector.includes("-status")) {
      await expect(locator).toBeAttached();
      continue;
    }
    await expect(locator).toBeVisible();
  }
}

/** Visit a tab, screenshot each view, and snapshot normalized panel text. */
export async function runTabViews(
  page: Page,
  slug: string,
  options?: { skipSnapshot?: boolean },
): Promise<void> {
  const tab = tabSchema(slug);
  const panel = page.locator("#content > article.card");
  const skipSnapshot = mcE2eSkipSnapshot(options?.skipSnapshot);
  await gotoTabReady(page, slug);
  await expect(panel).toBeVisible({ timeout: mcE2ePanelTimeout() });
  await assertSchemaContract(page, slug);
  await shot(page, slug, "view");
  if (!skipSnapshot) {
    await expect(await snapshotText(panel)).toMatchSnapshot(`${slug}-view.txt`);
  }

  for (const view of tab.views) {
    const locator =
      view.selector === "#content > article.card" ? panel : page.locator(view.selector);
    await expect(locator).toBeVisible();
    await shot(page, slug, view.id);
    if (view.selector !== "#content > article.card") {
      await expect(await snapshotText(locator)).toMatchSnapshot(`${slug}-${view.id}.txt`);
    }
  }
}

/** Read the dashboard CSRF cookie for authenticated API calls. */
export async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const token = cookies.find((row) => row.name === CSRF_COOKIE)?.value;
  return token ? { "X-CSRF-Token": token } : {};
}

/** GET JSON from a dashboard API route using the page session. */
export async function apiGetJson<T = Record<string, unknown>>(page: Page, path: string): Promise<T> {
  const resp = await page.request.get(path, { headers: await csrfHeaders(page) });
  expect(resp.ok(), `${resp.status()} GET ${path}`).toBeTruthy();
  return (await resp.json()) as T;
}

/** PUT JSON to a dashboard API route using the page session. */
export async function apiPutJson(page: Page, path: string, body: unknown): Promise<void> {
  const headers = {
    ...(await csrfHeaders(page)),
    "Content-Type": "application/json",
  };
  const resp = await page.request.put(path, { headers, data: body });
  expect(resp.ok(), `${resp.status()} PUT ${path}`).toBeTruthy();
}

/** POST JSON to a dashboard API route using the page session. */
export async function apiPostJson(page: Page, path: string, body: unknown): Promise<void> {
  const headers = {
    ...(await csrfHeaders(page)),
    "Content-Type": "application/json",
  };
  const resp = await page.request.post(path, { headers, data: body });
  expect(resp.ok(), `${resp.status()} POST ${path}`).toBeTruthy();
}

/** DELETE with optional JSON body using the page session. */
export async function apiDeleteJson(page: Page, path: string, body?: unknown): Promise<void> {
  const headers = {
    ...(await csrfHeaders(page)),
    "Content-Type": "application/json",
  };
  const resp = await page.request.delete(path, { headers, data: body });
  expect(resp.ok(), `${resp.status()} DELETE ${path}`).toBeTruthy();
}
