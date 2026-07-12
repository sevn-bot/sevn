// Mission Control — Overview tab (MC W3a).
// @mc-e2e-contract — G9 budget badges (data-path: E1)

import { test } from "../fixtures";

import { assertBudgetNonEmpty, isMcDataPathSeedEnabled, isMcFixtureMode } from "../_data-path";
import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("overview — views and contract", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "overview", {
    afterPanel: async (p) => {
      if (isMcFixtureMode() && isMcDataPathSeedEnabled()) {
        await assertBudgetNonEmpty(p);
      }
    },
  });
  gate.assertNoErrors();
});
