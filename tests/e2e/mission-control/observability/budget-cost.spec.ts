// @mc-e2e-data-path — G1 budget panel (positive when SEVN_MC_DATA_PATH_SEED=1)
// Mission Control — Budget & Cost tab (MC W3a).

import { expect, test } from "../fixtures";

import { assertBudgetEmpty, assertBudgetNonEmpty, isMcDataPathSeedEnabled, isMcFixtureMode } from "../_data-path";
import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("budget-cost — read-only summary", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "budget-cost", {
    afterPanel: async (p) => {
      if (!isMcFixtureMode()) {
        return;
      }
      if (isMcDataPathSeedEnabled()) {
        await assertBudgetNonEmpty(p);
        return;
      }
      await assertBudgetEmpty(p);
      const panel = p.locator("#content > article.card");
      await expect(panel).toContainText("No provider calls in the recent trace window");
      await expect(panel).toContainText("Provider calls (recent trace window): 0");
    },
  });
  gate.assertNoErrors();
});
