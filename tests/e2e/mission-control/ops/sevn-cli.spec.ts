// Mission Control — sevn CLI tab (MC W3d).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  openDashboard,
  shot,
} from "../_helpers";

test("sevn-cli — run safe doctor command", async ({ page }) => {
  test.setTimeout(120_000);

  await openDashboard(page);
  await ensureAuth(page);
  await gotoTab(page, "sevn-cli");

  const gate = installErrorGate(page);
  await expect(page.locator("#cli-run-btn")).toBeVisible();
  await shot(page, "sevn-cli", "view");

  await page.locator("#cli-args").fill("doctor --json");
  await page.locator("#cli-run-btn").click();
  await expect(page.locator("#cli-output")).toContainText("exit=", { timeout: 120_000 });
  await shot(page, "sevn-cli", "action-run");

  gate.assertNoErrors();
});
