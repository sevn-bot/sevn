// Schema-driven tab runner for Mission Control per-tab specs (MC W3a).

import { expect, type Page } from "@playwright/test";

import { gotoTab, mcE2ePanelTimeout, mcE2eSkipSnapshot, normalizedDom, shot } from "./_helpers";
import { mcSchema } from "./_schema";

export type McSchemaAction = {
  id: string;
  label: string;
  selector: string;
  method: string;
  endpoint: string;
  destructive?: boolean;
  needs_seed?: boolean;
};

export type TabSpecOptions = {
  /** Extra assertions after the main panel is visible. */
  afterPanel?: (page: Page) => Promise<void>;
  /** Per-view setup before screenshot (e.g. switch sub-view). */
  viewHooks?: Record<string, (page: Page) => Promise<void>>;
  /** Custom action handlers keyed by action id. */
  actionHooks?: Record<string, (page: Page) => Promise<void>>;
  /** Action ids to skip (with test.info annotation). */
  skipActions?: string[];
  /** Schema key_selector values to skip when empty/hidden in the E2E workspace. */
  skipKeySelectors?: string[];
  /** Skip normalized DOM snapshot when panel content is inherently volatile. */
  skipSnapshot?: boolean;
};

/** Strip absolute workspace paths and volatile audit timestamps for stable snapshots. */
function normalizeSnapshotText(text: string): string {
  return text
    .replace(/\/Users\/[^\s]+/g, "<workspace-path>")
    .replace(/\d{1,2}\/\d{1,2}\/\d{4},?\s*\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM)?/gi, "<volatile>")
    .replace(/(?:notes|second_brain)\/mc-e2e[^\s]*/gi, "<volatile>")
    .replace(/runs(?:<volatile>trigger\d*)+/gi, "runs<volatile-sessions>")
    .replace(/runs(?:[0-9a-f]{24,}trigger\d+)+/gi, "runs<volatile-sessions>")
    .replace(/[0-9a-f]{24,}/gi, "<hex-id>")
    .replace(/Proxy up \d+/gi, "Proxy up <volatile>")
    .replace(/Providers \d+ degraded/gi, "Providers <volatile> degraded")
    .replace(/\b\d+ degraded\b/gi, "<volatile> degraded")
    .replace(/Sessions listed \d+/gi, "Sessions listed <volatile>")
    .replace(/Active sessions \d+/gi, "Active sessions <volatile>")
    .replace(/Registry v\d+/g, "Registry v<volatile>")
    .replace(/\s+/g, " ")
    .trim();
}

/** Assert key schema selectors and run views/actions for one dashboard tab. */
export async function runTabSpec(page: Page, slug: string, options: TabSpecOptions = {}): Promise<void> {
  const tab = mcSchema.tabs[slug];
  if (!tab) {
    throw new Error(`schema missing tab: ${slug}`);
  }

  const panelTimeout = mcE2ePanelTimeout();
  const skipSnapshot = mcE2eSkipSnapshot(options.skipSnapshot);

  await gotoTab(page, slug);
  const panel = page.locator("#content > article.card");
  await expect(panel).toBeVisible({ timeout: panelTimeout });
  await expect(page.locator("#login-panel")).toBeHidden();

  if (tab.key_selectors) {
    const skip = new Set(options.skipKeySelectors ?? []);
    for (const [, selector] of Object.entries(tab.key_selectors)) {
      if (skip.has(selector)) {
        continue;
      }
      await expect(page.locator(selector).first()).toBeVisible();
    }
  }

  if (options.afterPanel) {
    await options.afterPanel(page);
  }

  await shot(page, slug, "view");
  if (!skipSnapshot) {
    await expect(normalizeSnapshotText(await normalizedDom(panel))).toMatchSnapshot(`${slug}-view.txt`);
  }

  for (const view of tab.views) {
    if (options.viewHooks?.[view.id]) {
      await options.viewHooks[view.id](page);
    } else if (view.selector !== "#content > article.card") {
      await expect(page.locator(view.selector).first()).toBeVisible();
    }
    await shot(page, slug, view.id);
  }

  const actions = (tab.actions ?? []) as McSchemaAction[];
  for (const action of actions) {
    if (options.skipActions?.includes(action.id)) {
      continue;
    }
    if (options.actionHooks?.[action.id]) {
      await options.actionHooks[action.id](page);
      await shot(page, slug, `action-${action.id}`);
      continue;
    }
    if (action.destructive && process.env.SEVN_MC_E2E_ALLOW_DISRUPTIVE !== "1") {
      await expect(page.locator(action.selector).first()).toBeVisible();
      continue;
    }
    await expect(page.locator(action.selector).first()).toBeVisible();
    await shot(page, slug, `action-${action.id}-reachable`);
  }
}
