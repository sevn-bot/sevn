// Mission Control — Workspace Files tab (MC W3b).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { acceptConfirmDialog, acceptPromptDialog } from "../_dialog";
import { mcE2ePanelTimeout, shot } from "../_helpers";
import { runTabViews, setupTabTest, tabSchema } from "../_tabRunner";

const THROWAWAY = `notes/mc-e2e-w3b-workspace-${Date.now()}.md`;

test("workspace-files — file editor new, save, delete", async ({ page }) => {
  test.setTimeout(60_000);
  const gate = await setupTabTest(page);
  const slug = "workspace-files";
  tabSchema(slug);

  await runTabViews(page, slug, { skipSnapshot: true });

  await acceptPromptDialog(page, THROWAWAY, () => page.locator("#file-editor-new").click());
  await expect(page.locator("#file-editor-path")).toHaveValue(THROWAWAY, {
    timeout: mcE2ePanelTimeout(),
  });

  await page.locator("#file-editor-content").fill("mc-e2e w3b workspace-files probe");
  await page.locator("#file-editor-save").click();
  await expect(page.locator("#file-editor-status")).toContainText("Saved", { timeout: 15_000 });
  await shot(page, slug, "saved");

  await acceptConfirmDialog(page, () => page.locator("#file-editor-delete").click());
  await expect(page.locator("#file-editor-status")).toContainText("trash", { timeout: 15_000 });
  await shot(page, slug, "deleted");

  gate.assertNoErrors();
});
