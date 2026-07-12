// Mission Control — Terminal tab (MC W3d).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  openDashboard,
  shot,
} from "../_helpers";

test("terminal — connect and disconnect when disruptive allowed", async ({ page }) => {
  test.setTimeout(60_000);

  await openDashboard(page);
  await ensureAuth(page);
  await gotoTab(page, "terminal");

  const gate = installErrorGate(page);
  await expect(page.locator("#terminal-connect-btn")).toBeVisible();
  await expect(page.locator("#terminal-disconnect-btn")).toBeVisible();
  await shot(page, "terminal", "view");

  if (process.env.SEVN_MC_E2E_ALLOW_DISRUPTIVE === "1") {
    await page.locator("#terminal-connect-btn").click();
    await expect(page.locator("#terminal-status")).not.toHaveText("idle", { timeout: 15_000 });
    await shot(page, "terminal", "connected");
    await page.locator("#terminal-disconnect-btn").click();
    await expect(page.locator("#terminal-status")).toHaveText("idle", { timeout: 15_000 });
    await shot(page, "terminal", "disconnected");
  }

  gate.assertNoErrors();
});
