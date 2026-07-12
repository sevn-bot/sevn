// Mission Control — Providers & LLMs tab (MC W3a).
// @mc-e2e-contract — G5 provider stats (data-path: E1)

import { expect, test } from "../fixtures";

import { assertProvidersStatsNonEmpty, isMcDataPathSeedEnabled, isMcFixtureMode } from "../_data-path";
import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("providers-llms — health table and oauth reauth hint", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "providers-llms", {
    afterPanel: async (p) => {
      await expect(p.getByText(/oauth login/i).first()).toBeVisible({ timeout: 15_000 });
      if (isMcFixtureMode() && isMcDataPathSeedEnabled()) {
        await assertProvidersStatsNonEmpty(p);
      }
    },
  });
  gate.assertNoErrors();
});
