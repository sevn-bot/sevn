// Mission Control — Web Apps tab (MC W3d).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  openDashboard,
  shot,
} from "../_helpers";

test("web-apps — PUT edit and restore", async ({ page }) => {
  test.setTimeout(60_000);

  await openDashboard(page);
  await ensureAuth(page);
  await gotoTab(page, "web-apps");

  const gate = installErrorGate(page);
  const form = page.locator("#web-apps-form");
  await expect(form).toBeVisible();
  await shot(page, "web-apps", "view");

  const probe = form.locator('input[data-webchat-key="public"]');
  await expect(probe).toBeVisible();
  const wasChecked = await probe.isChecked();
  await probe.setChecked(!wasChecked);
  await form.locator('button[type="submit"]').click();
  await page.waitForTimeout(400);
  await shot(page, "web-apps", "action-save");

  await probe.setChecked(wasChecked);
  await form.locator('button[type="submit"]').click();
  await page.waitForTimeout(400);
  await expect(probe).toHaveJSProperty("checked", wasChecked);

  gate.assertNoErrors();
});
