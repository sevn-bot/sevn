// Mission Control — Onboarding tab (MC W3d, read-only).
// @mc-e2e-contract

import { test } from "../fixtures";

import { runTabSpec } from "../_tab-spec";

test("onboarding — surface snapshot", async ({ page }) => {
  await runTabSpec(page, "onboarding");
});
