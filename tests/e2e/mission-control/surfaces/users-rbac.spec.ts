// Mission Control — Users & RBAC tab (MC W3d, read-only).
// @mc-e2e-contract

import { test } from "../fixtures";

import { runTabSpec } from "../_tab-spec";

test("users-rbac — RBAC snapshot", async ({ page }) => {
  await runTabSpec(page, "users-rbac");
});
