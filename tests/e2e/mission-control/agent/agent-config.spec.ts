// Mission Control — Agent Config tab (MC W3b).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { ensureAuth, mcE2eSkipSnapshot, normalizedDom, shot } from "../_helpers";
import {
  apiPutJson,
  assertSchemaContract,
  gotoTab,
  setupTabTest,
  tabSchema,
} from "../_tabRunner";

test("agent-config — unified/slot toggle, save and restore", async ({ page }) => {
  test.setTimeout(60_000);
  const gate = await setupTabTest(page);
  const slug = "agent-config";
  tabSchema(slug);

  await apiPutJson(page, "/api/v1/agent/config", { use_main_model_for_all: true });
  await page.reload();
  await ensureAuth(page);
  await gotoTab(page, slug);
  await expect(page.locator("#agent-unified-model")).toBeVisible({ timeout: 30_000 });

  const unified = page.locator("#agent-unified-model");
  const originalUnified = await unified.isChecked();
  const panel = page.locator("#content > article.card");
  const slotEditor = page.locator("#agent-slot-editor");

  await expect(panel).toBeVisible();
  await shot(page, slug, "view");
  if (!mcE2eSkipSnapshot()) {
    await expect(await normalizedDom(panel)).toMatchSnapshot(`${slug}-view.txt`);
  }

  if (await unified.isChecked()) {
    await unified.setChecked(false);
  }
  await expect(slotEditor).toBeVisible();
  await shot(page, slug, "main");
  if (!mcE2eSkipSnapshot()) {
    await expect(await normalizedDom(slotEditor)).toMatchSnapshot(`${slug}-main.txt`);
  }
  await assertSchemaContract(page, slug);

  const wasUnified = await unified.isChecked();
  await unified.setChecked(!wasUnified);
  if (wasUnified) {
    await expect(slotEditor).toBeVisible();
  } else {
    await expect(slotEditor).toBeHidden();
  }
  await shot(page, slug, "toggle");

  await page.locator("#agent-config-save-btn").click();
  await expect(page.locator("#agent-unified-model")).toBeVisible({ timeout: 15_000 });
  await shot(page, slug, "saved");

  await apiPutJson(page, "/api/v1/agent/config", { use_main_model_for_all: originalUnified });
  gate.assertNoErrors();
});
