// Mission Control — Secrets tab (MC W3d + W4 show/hide toggle).
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

test("secrets — create, reveal, delete throwaway alias", async ({ page }) => {
  test.setTimeout(60_000);

  await openDashboard(page);
  await ensureAuth(page);
  await gotoTab(page, "secrets");

  const gate = installErrorGate(page);
  await expect(page.locator("#secrets-save-btn")).toBeVisible();
  const toggle = page.getByRole("checkbox", { name: "Show values" });
  const banner = page.locator("#secrets-exposed-banner");
  await expect(toggle).toBeVisible();
  await expect(toggle).not.toBeChecked();
  await expect(banner).toBeHidden();
  const masked = page.locator(".secrets-value-cell").first();
  if ((await masked.count()) > 0) {
    await expect(masked).toContainText("•");
  }
  await toggle.check();
  await expect(banner).toBeVisible();
  await toggle.uncheck();
  await expect(banner).toBeHidden();
  await shot(page, "secrets", "view");

  const alias = `mc.e2e.${Date.now()}`;
  const plaintext = "mc-e2e-throwaway-secret";
  await page.locator("#secrets-alias").fill(alias);
  await page.locator("#secrets-value").fill(plaintext);
  await page.locator("#secrets-save-btn").click();
  await expect(page.locator("#secrets-output")).not.toBeEmpty({ timeout: 15_000 });
  await shot(page, "secrets", "action-save");

  const saved = JSON.parse((await page.locator("#secrets-output").textContent()) || "{}");
  const fingerprint = saved.fingerprint_sha256_hex as string;
  expect(fingerprint).toBeTruthy();

  await page.locator("#secrets-reveal-btn").click();
  await expect(page.locator("#secrets-output")).toContainText(plaintext, { timeout: 15_000 });
  await shot(page, "secrets", "action-reveal");

  await page.locator("#secrets-fingerprint").fill(fingerprint);
  await acceptConfirmDialog(page, () => page.locator("#secrets-delete-btn").click());
  await page.waitForTimeout(400);
  await shot(page, "secrets", "action-delete");

  gate.assertNoErrors();
});
