// Mission Control — Schema & Ontology tab (MC W3d, read-only).
// @mc-e2e-contract

import { test } from "../fixtures";

import { runTabSpec } from "../_tab-spec";

test("schema-ontology — ontology payload", async ({ page }) => {
  await runTabSpec(page, "schema-ontology");
});
