// Mission Control — Telegram Menu tab (MC W3d).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  openDashboard,
  shot,
} from "../_helpers";

test("telegram-menu — PUT edit and restore", async ({ page }) => {
  test.setTimeout(60_000);

  await openDashboard(page);
  await ensureAuth(page);
  await gotoTab(page, "telegram-menu");

  const gate = installErrorGate(page);
  const form = page.locator("#telegram-menu-form");
  await expect(form).toBeVisible();
  await shot(page, "telegram-menu", "view");

  const probe = form.locator('input[data-telegram-key="reply_keyboard_enabled"]');
  await expect(probe).toBeVisible();
  const wasChecked = await probe.isChecked();
  await probe.setChecked(!wasChecked);
  await form.locator('button[type="submit"]').click();
  await page.waitForTimeout(400);
  await shot(page, "telegram-menu", "action-save");

  await probe.setChecked(wasChecked);
  await form.locator('button[type="submit"]').click();
  await page.waitForTimeout(400);
  await expect(probe).toHaveJSProperty("checked", wasChecked);

  gate.assertNoErrors();
});
