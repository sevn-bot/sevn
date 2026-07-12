// Mission Control — Channels tab (MC W3a).
// @mc-e2e-contract — G4 channels runtime health (data-path: E1)

import { expect, test } from "../fixtures";

import { assertChannelsRuntimeNonEmpty, isMcDataPathSeedEnabled, isMcFixtureMode } from "../_data-path";
import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("channels — save channel settings and restore", async ({ page }) => {
  test.setTimeout(60_000);
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "channels", {
    afterPanel: async (p) => {
      if (isMcFixtureMode() && isMcDataPathSeedEnabled()) {
        await assertChannelsRuntimeNonEmpty(p);
      }
    },
    actionHooks: {
      "save-config": async (p) => {
        const form = p.locator("#channels-config-form");
        const publicCheckbox = form.locator('input[data-channels-path="webchat.public"]');
        await expect(publicCheckbox).toBeVisible({ timeout: 15_000 });
        const original = await publicCheckbox.isChecked();
        await publicCheckbox.setChecked(!original);
        await form.locator('button[type="submit"]').click();
        await expect(p.locator("#content > article.card")).toBeVisible();
        await publicCheckbox.setChecked(original);
        await form.locator('button[type="submit"]').click();
        await expect(p.locator("#content > article.card")).toBeVisible();
      },
    },
  });
  gate.assertNoErrors();
});
