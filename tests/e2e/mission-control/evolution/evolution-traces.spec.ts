// Mission Control — Evolution Traces tab (MC W3c, read-only).
// @mc-e2e-contract

import { test } from "../fixtures";

import { runTabSpec } from "../_tab-spec";

test("evolution-traces — filtered trace list", async ({ page }) => {
  await runTabSpec(page, "evolution-traces");
});
