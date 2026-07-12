// Mission Control — Pipelines tab (MC W3c).
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

test("pipelines — poll and kill seeded issue", async ({ page }) => {
  await openDashboard(page);
  await ensureAuth(page);

  const created = await seedEvolutionIssue(page, "pipelines", "bug");
  const gate = installErrorGate(page);

  await gotoTab(page, "pipelines");
  const panel = page.locator("#content > article.card");
  await expect(panel).toBeVisible();
  await expect(panel.locator("code").filter({ hasText: created.id })).toBeVisible();
  await shot(page, "pipelines", "view");

  const pollBtn = page.locator(`.pipeline-poll[data-issue-id="${created.id}"]`);
  await expect(pollBtn).toBeVisible();
  await pollBtn.click();
  await page.waitForTimeout(400);
  await shot(page, "pipelines", "action-poll");

  const killBtn = page.locator(`.pipeline-kill[data-issue-id="${created.id}"]`);
  await expect(killBtn).toBeVisible();
  await killBtn.click();
  await page.waitForTimeout(400);
  await shot(page, "pipelines", "action-kill");

  gate.assertNoErrors();
});
