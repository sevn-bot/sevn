// Mission Control — RLM Training tab (MC W3c, read-only).
// @mc-e2e-contract — G12 read-only STUB

import { test } from "../fixtures";

import { runTabSpec } from "../_tab-spec";

test("rlm-training — config and job summary", async ({ page }) => {
  await runTabSpec(page, "rlm-training");
});
