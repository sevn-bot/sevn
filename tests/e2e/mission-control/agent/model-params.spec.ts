// Mission Control — Model Params tab (MC W3b).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { ensureAuth, mcE2ePanelTimeout, shot } from "../_helpers";
import { apiGetJson, apiPutJson, gotoTabReady, runTabViews, setupTabTest, tabSchema } from "../_tabRunner";

test("model-params — PUT save and restore", async ({ page }) => {
  test.setTimeout(60_000);
  const gate = await setupTabTest(page);
  const slug = "model-params";
  tabSchema(slug);

  const original = await apiGetJson<{ doc: Record<string, Record<string, unknown>> }>(
    page,
    "/api/v1/agent/llm-params",
  );
  const originalDoc = structuredClone(original.doc);

  await runTabViews(page, slug);

  const probe = page.locator('.mp-input[data-agent="tier_b"][data-scope="base"][data-field="temperature"]');
  await expect(probe).toBeVisible();
  const prior = await probe.inputValue();
  await probe.fill("0.42");

  await page.locator("#model-params-save-btn").click();
  await expect(page.locator("#model-params-status")).toContainText("Saved", { timeout: 15_000 });
  await shot(page, slug, "saved");

  await apiPutJson(page, "/api/v1/agent/llm-params", { doc: originalDoc });
  await page.reload();
  await ensureAuth(page);
  await gotoTabReady(page, slug);
  await expect(probe).toHaveValue(prior || "", { timeout: mcE2ePanelTimeout() });

  gate.assertNoErrors();
});
