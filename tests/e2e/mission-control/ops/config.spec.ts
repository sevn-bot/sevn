// Mission Control — Config tab (MC W3d).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { acceptConfirmDialog } from "../_dialog";
import { mcApiGet, mcApiPut } from "../_api-seed";
import {
  ensureAuth,
  gotoTab,
  installErrorGate,
  mcE2ePanelTimeout,
  openDashboard,
  shot,
  waitForPanelReady,
} from "../_helpers";

test("config — tree/text toggle, validate, save and restore", async ({ page }) => {
  test.setTimeout(90_000);

  await openDashboard(page);
  await ensureAuth(page);

  const original = await mcApiGet<{ config?: Record<string, unknown> }>(page, "/api/v1/config/full");
  const originalConfig = structuredClone(original.config || {});

  await gotoTab(page, "config");

  const gate = installErrorGate(page);
  await expect(page.locator("#config-tree-panel")).toBeVisible();
  await shot(page, "config", "tree");

  await page.locator("#config-mode-text").click();
  const editor = page.locator("#config-editor");
  await expect(editor).toBeVisible();
  await shot(page, "config", "text");

  await page.locator("#config-mode-tree").click();
  await expect(page.locator("#config-tree-panel")).toBeVisible();
  await shot(page, "config", "tree-again");

  await page.locator("#config-validate-btn").click();
  await expect(page.locator("#config-editor-status")).toContainText("Validation passed", {
    timeout: 15_000,
  });
  await shot(page, "config", "action-validate");

  const probe = page.locator('input[data-config-path="channels.telegram.show_routing"]');
  await expect(probe).toBeVisible();
  const wasChecked = await probe.isChecked();
  await probe.setChecked(!wasChecked);

  await acceptConfirmDialog(page, () => page.locator("#config-save-btn").click());
  await expect(probe).toHaveJSProperty("checked", !wasChecked, { timeout: mcE2ePanelTimeout() });
  await shot(page, "config", "action-save");

  await mcApiPut(page, "/api/v1/config/full", originalConfig);
  await page.goto("/mission/config");
  await waitForPanelReady(page);
  const restoredProbe = page.locator('input[data-config-path="channels.telegram.show_routing"]');
  await expect(restoredProbe).toHaveJSProperty("checked", wasChecked, {
    timeout: mcE2ePanelTimeout(),
  });

  gate.assertNoErrors();
});
