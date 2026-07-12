// Mission Control — Backup & Snapshots tab (MC W3d, read-only).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  openDashboard,
  shot,
} from "../_helpers";

test("backup-snapshots — manifest panels (read-only)", async ({ page }) => {
  await openDashboard(page);
  await ensureAuth(page);
  await gotoTab(page, "backup-snapshots");

  const gate = installErrorGate(page);
  const panel = page.locator("#content > article.card");
  await expect(panel).toBeVisible();
  await expect(page.locator("#backup-export-btn")).toBeVisible();
  await expect(page.locator("#snapshot-create-btn")).toBeVisible();
  await shot(page, "backup-snapshots", "view");

  gate.assertNoErrors();
});
