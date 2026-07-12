// Mission Control — MCP Servers tab (MC W3b).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { shot } from "../_helpers";
import { apiGetJson, apiPutJson, gotoTabReady, runTabViews, setupTabTest, tabSchema } from "../_tabRunner";

type McpServersBody = {
  mcp_enabled: string[];
  servers: Array<{ server_id: string; workspace_enabled: boolean }>;
};

test("mcp-servers — PUT enablement save and restore", async ({ page }) => {
  test.setTimeout(60_000);
  const gate = await setupTabTest(page);
  const slug = "mcp-servers";
  tabSchema(slug);

  const original = await apiGetJson<McpServersBody>(page, "/api/v1/agent/mcp-servers");
  const originalEnabled = [...(original.mcp_enabled || [])];

  await runTabViews(page, slug);

  const checkbox = page.locator("#mcp-servers-form input[data-mcp-server]").first();
  if (!(await checkbox.count())) {
    gate.assertNoErrors();
    return;
  }

  const wasChecked = await checkbox.isChecked();
  await checkbox.setChecked(!wasChecked);
  await page.locator("#mcp-servers-form button[type='submit']").click();
  await gotoTabReady(page, slug);
  await shot(page, slug, "saved");

  await apiPutJson(page, "/api/v1/agent/mcp-servers", { mcp_enabled: originalEnabled });
  await gotoTabReady(page, slug);
  await expect(checkbox).toHaveJSProperty("checked", wasChecked);

  gate.assertNoErrors();
});
