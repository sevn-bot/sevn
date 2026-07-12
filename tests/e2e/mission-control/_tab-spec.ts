// Schema-driven Mission Control tab spec runner (MC W3).

import { expect, type Locator, type Page } from "@playwright/test";

import { acceptConfirmDialog } from "./_dialog";
import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  openDashboard,
  shot,
} from "./_helpers";
import { mcSchema, type McSchemaTab } from "./_schema";

export type McSchemaAction = {
  id: string;
  label: string;
  selector: string;
  method: string;
  endpoint: string;
  destructive?: boolean;
  needs_seed?: boolean;
};

export type TabSpecContext = {
  page: Page;
  slug: string;
  tab: McSchemaTab;
  panel: Locator;
};

export type TabSpecOptions = {
  /** Runs after the tab loads and before actions (seed throwaway entities). */
  beforeActions?: (ctx: TabSpecContext) => Promise<void>;
  /** Per-view navigation beyond the default panel (e.g. eval-report sub-view). */
  visitViews?: (ctx: TabSpecContext) => Promise<void>;
  /** Override default click handler for schema actions. */
  handleAction?: (ctx: TabSpecContext, action: McSchemaAction) => Promise<void>;
  /** Skip schema action ids (external deps, lane-specific). */
  skipActions?: string[];
};

function tabActions(tab: McSchemaTab): McSchemaAction[] {
  return (tab.actions || []) as McSchemaAction[];
}

async function assertContract(ctx: TabSpecContext): Promise<void> {
  const { page, tab, panel } = ctx;
  await expect(panel).toBeVisible();
  await expect(page.locator("#login-panel")).toBeHidden();
  for (const view of tab.views) {
    await expect(page.locator(view.selector)).toBeVisible();
  }
  for (const selector of Object.values(tab.key_selectors || {})) {
    await expect(page.locator(selector).first()).toBeVisible();
  }
}

async function defaultHandleAction(
  ctx: TabSpecContext,
  action: McSchemaAction,
): Promise<void> {
  const { page, slug } = ctx;
  const target = page.locator(action.selector).first();

  if (action.destructive && process.env.SEVN_MC_E2E_ALLOW_DISRUPTIVE !== "1") {
    await expect(target).toBeVisible();
    await shot(page, slug, `action-${action.id}-reachable`);
    return;
  }

  if (action.id === "cycle") {
    await acceptConfirmDialog(page, () => target.click());
    await page.waitForTimeout(300);
    await shot(page, slug, `action-${action.id}`);
    return;
  }

  await expect(target).toBeVisible();
  await target.click();
  await page.waitForTimeout(300);
  await shot(page, slug, `action-${action.id}`);
}

/** Drive one dashboard tab: views, snapshots, schema actions, error gate. */
export async function runTabSpec(
  page: Page,
  slug: string,
  options: TabSpecOptions = {},
): Promise<void> {
  const gate = installErrorGate(page);
  const tab = mcSchema.tabs[slug];
  expect(tab, `schema tab ${slug}`).toBeTruthy();

  await openDashboard(page);
  await ensureAuth(page);
  await gotoTab(page, slug);

  const ctx: TabSpecContext = {
    page,
    slug,
    tab,
    panel: page.locator("#content > article.card"),
  };

  await assertContract(ctx);
  await shot(page, slug, "view");

  if (options.visitViews) {
    await options.visitViews(ctx);
  } else {
    for (const view of tab.views) {
      if (view.id === "main" || view.id === "list") continue;
      await shot(page, slug, view.id);
    }
  }

  if (options.beforeActions) {
    await options.beforeActions(ctx);
  }

  const handler = options.handleAction || defaultHandleAction;
  for (const action of tabActions(tab)) {
    if (options.skipActions?.includes(action.id)) continue;
    await handler(ctx, action);
  }

  gate.assertNoErrors();
}
