// Mission Control — Feedback tab (MC W3c, read-only).
// @mc-e2e-contract

import { test } from "../fixtures";

import { runTabSpec } from "../_tab-spec";

test("feedback — events and structured tables", async ({ page }) => {
  await runTabSpec(page, "feedback");
});
