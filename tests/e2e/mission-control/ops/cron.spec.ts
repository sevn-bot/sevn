// Mission Control — Cron tab (MC W3d).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { acceptConfirmDialog } from "../_dialog";
import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  openDashboard,
  shot,
} from "../_helpers";

test("cron — create, run, toggle, delete", async ({ page }) => {
  test.setTimeout(60_000);

  await openDashboard(page);
  await ensureAuth(page);
  await gotoTab(page, "cron");

  const gate = installErrorGate(page);
  const panel = page.locator("#content > article.card");
  await expect(panel).toBeVisible();
  await expect(page.locator("#cron-create-form")).toBeVisible();
  await shot(page, "cron", "view");

  const jobId = `mc-e2e-${Date.now()}`;
  await page.locator("#cron-new-id").fill(jobId);
  await page.locator("#cron-new-expr").fill("0 0 * * *");
  await page.locator("#cron-new-tz").fill("UTC");
  await page.locator("#cron-create-form").locator('button[type="submit"]').click();
  await expect(page.locator(`.cron-run-btn[data-job-id="${jobId}"]`)).toBeVisible({
    timeout: 15_000,
  });
  await shot(page, "cron", "action-create");

  await acceptConfirmDialog(page, () => page.locator(`.cron-run-btn[data-job-id="${jobId}"]`).click());
  await page.waitForTimeout(400);
  await shot(page, "cron", "action-run");

  await page.locator(`.cron-toggle-btn[data-job-id="${jobId}"]`).click();
  await page.waitForTimeout(400);
  await shot(page, "cron", "action-toggle");

  await acceptConfirmDialog(page, () => page.locator(`.cron-delete-btn[data-job-id="${jobId}"]`).click());
  await expect(page.locator(`.cron-run-btn[data-job-id="${jobId}"]`)).toHaveCount(0, {
    timeout: 15_000,
  });
  await shot(page, "cron", "action-delete");

  gate.assertNoErrors();
});
