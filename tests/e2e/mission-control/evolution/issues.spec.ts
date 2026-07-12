// Mission Control — Issues tab (MC W3c).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { seedEvolutionIssue } from "../_api-seed";
import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  openDashboard,
  shot,
} from "../_helpers";

test("issues — create, run pipeline modal, cancel", async ({ page }) => {
  await openDashboard(page);
  await ensureAuth(page);

  const created = await seedEvolutionIssue(page, "issues", "bug");
  const gate = installErrorGate(page);

  await gotoTab(page, "issues");
  const panel = page.locator("#content > article.card");
  await expect(panel).toBeVisible();
  await expect(panel.locator("code").filter({ hasText: created.id })).toBeVisible();
  await shot(page, "issues", "view");

  const runBtn = page.locator(`.issue-run-pipeline[data-issue-id="${created.id}"]`);
  await expect(runBtn).toBeVisible();
  await runBtn.click();
  await expect(page.locator("#issues-run-form")).toBeVisible();
  await shot(page, "issues", "run-form");
  await page.locator("#run-cancel-btn").click();
  await expect(page.locator("#issues-run-form")).toBeHidden();

  gate.assertNoErrors();
});
