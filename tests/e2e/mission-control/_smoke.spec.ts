// Mission Control harness smoke — nav groups, schema tab count, overview (MC W2).
// @mc-e2e-contract

import { expect, test } from "./fixtures";

import { ensureAuth, gotoTab, installErrorGate, openDashboard, shot } from "./_helpers";
import { mcSchema } from "./_schema";

test("mission control smoke — nav groups, tab count, overview", async ({ page }) => {
  const gate = installErrorGate(page);

  await openDashboard(page);
  await ensureAuth(page);

  await expect(page.locator(".sidebar__group")).toHaveCount(mcSchema.nav.groups.length);
  await expect(page.locator(".sidebar__item")).toHaveCount(mcSchema.tab_count);

  for (const group of mcSchema.nav.groups) {
    await expect(page.getByRole("button", { name: group.name })).toBeVisible();
  }

  await gotoTab(page, "overview");
  await shot(page, "overview", "view");
  await expect(page.locator("#content > article.card")).toBeVisible();

  gate.assertNoErrors();
});
