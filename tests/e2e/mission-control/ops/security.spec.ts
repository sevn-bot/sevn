// Mission Control — Security tab (MC W3d).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  openDashboard,
  shot,
} from "../_helpers";

test("security — PUT toggle and restore", async ({ page }) => {
  test.setTimeout(60_000);

  await openDashboard(page);
  await ensureAuth(page);
  await gotoTab(page, "security");

  const gate = installErrorGate(page);
  const form = page.locator("#security-toggles-form");
  await expect(form).toBeVisible();
  await shot(page, "security", "view");

  const probe = form.locator('input[data-security-key="heuristic_only"]');
  await expect(probe).toBeVisible();
  const wasChecked = await probe.isChecked();
  await probe.setChecked(!wasChecked);
  await form.locator('button[type="submit"]').click();
  await page.waitForTimeout(400);
  await shot(page, "security", "action-save");

  await probe.setChecked(wasChecked);
  await form.locator('button[type="submit"]').click();
  await page.waitForTimeout(400);
  await expect(probe).toHaveJSProperty("checked", wasChecked);

  gate.assertNoErrors();
});
