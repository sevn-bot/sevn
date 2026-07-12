// Mission Control — Stats tab (MC W3c, read-only).
// @mc-e2e-contract

import { test } from "../fixtures";

import { runTabSpec } from "../_tab-spec";

test("stats — evolution counters", async ({ page }) => {
  await runTabSpec(page, "stats");
});
