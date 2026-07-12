// Mission Control — Code Understanding tab (MC W3b, read-only).
// @mc-e2e-contract

import { test } from "../fixtures";

import { runTabViews, setupTabTest, tabSchema } from "../_tabRunner";

test("code-understanding — read-only views and screenshots", async ({ page }) => {
  test.setTimeout(60_000);
  const gate = await setupTabTest(page);
  const slug = "code-understanding";
  tabSchema(slug);

  await runTabViews(page, slug);

  gate.assertNoErrors();
});
