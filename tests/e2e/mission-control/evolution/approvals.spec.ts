// Mission Control — Approvals tab (MC W3c).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { seedPendingApproval } from "../_api-seed";
import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  openDashboard,
  shot,
} from "../_helpers";
import { mcSchema } from "../_schema";

test("approvals — seed, approve pending HITL row", async ({ page }) => {
  await openDashboard(page);
  await ensureAuth(page);

  const seeded = await seedPendingApproval(page, "approvals");
  const gate = installErrorGate(page);

  await gotoTab(page, "approvals");
  const panel = page.locator("#content > article.card");
  await expect(panel).toBeVisible();
  await shot(page, "approvals", "view");

  const approveBtn = page.locator(`.approval-approve[data-id="${seeded.approvalId}"]`);
  await expect(approveBtn).toBeVisible();
  await approveBtn.click();
  await page.waitForTimeout(400);
  await shot(page, "approvals", "action-approve");
  await expect(page.locator(`.approval-approve[data-id="${seeded.approvalId}"]`)).toHaveCount(0);

  gate.assertNoErrors();
  expect(mcSchema.tabs["approvals"].actions?.length).toBeGreaterThan(0);
});
