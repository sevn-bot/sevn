// @mc-e2e-data-path — G2 trajectories list (positive when SEVN_MC_DATA_PATH_SEED=1)
// Mission Control — Trajectories tab (MC W3c, read-only).

import { test } from "../fixtures";

import {
  assertTrajectoriesEmpty,
  assertTrajectoriesNonEmpty,
  isMcDataPathSeedEnabled,
  isMcFixtureMode,
} from "../_data-path";
import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("trajectories — list + eval report context", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "trajectories", {
    afterPanel: async (p) => {
      if (!isMcFixtureMode()) {
        return;
      }
      if (isMcDataPathSeedEnabled()) {
        await assertTrajectoriesNonEmpty(p);
        return;
      }
      await assertTrajectoriesEmpty(p);
    },
  });
  gate.assertNoErrors();
});
