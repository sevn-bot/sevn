// Mission Control — Tools & Permissions tab (MC W3b).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { shot } from "../_helpers";
import { apiGetJson, apiPutJson, gotoTabReady, runTabViews, setupTabTest, tabSchema } from "../_tabRunner";

test("tools-permissions — PUT save and restore", async ({ page }) => {
  test.setTimeout(60_000);
  const gate = await setupTabTest(page);
  const slug = "tools-permissions";
  tabSchema(slug);

  const original = await apiGetJson<{ permissions: Record<string, unknown>; tools: Record<string, unknown> }>(
    page,
    "/api/v1/agent/permissions",
  );

  await runTabViews(page, slug);

  const permsEditor = page.locator("#permissions-editor");
  const toolsEditor = page.locator("#tools-editor");
  await expect(permsEditor).toBeVisible();
  await expect(toolsEditor).toBeVisible();

  const mutatedPerms = {
    ...original.permissions,
    "mc-e2e-w3b-probe": true,
  };
  await permsEditor.fill(JSON.stringify(mutatedPerms, null, 2));

  await page.locator("#permissions-form button[type='submit']").click();
  await gotoTabReady(page, slug);
  await shot(page, slug, "saved");

  await apiPutJson(page, "/api/v1/agent/permissions", {
    permissions: original.permissions,
    tools: original.tools,
  });

  gate.assertNoErrors();
});
