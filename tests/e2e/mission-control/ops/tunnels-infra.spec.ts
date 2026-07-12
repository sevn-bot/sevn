// Mission Control — Tunnels & Infra tab (MC W3d, read-only).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  openDashboard,
  shot,
} from "../_helpers";

test("tunnels-infra — doctor probes and daemon controls (read-only)", async ({ page }) => {
  await openDashboard(page);
  await ensureAuth(page);
  await gotoTab(page, "tunnels-infra");

  const gate = installErrorGate(page);
  const panel = page.locator("#content > article.card");
  await expect(panel).toBeVisible();
  await expect(page.locator("#ops-reload-config-btn")).toBeVisible();
  await expect(page.locator(".daemon-action-btn").first()).toBeVisible();
  await shot(page, "tunnels-infra", "view");

  gate.assertNoErrors();
});
