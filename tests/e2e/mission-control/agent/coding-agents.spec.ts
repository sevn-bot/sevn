// Mission Control — Coding Agents hub (CA1).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("coding-agents — wired hub panel", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "coding-agents", {
    afterPanel: async (p) => {
      const panel = p.locator("#coding-agents-panel");
      await expect(panel).toBeVisible();
      await expect(panel.getByText(/Coding Agents hub/i)).toBeVisible();
      await expect(panel.locator("#coding-agents-save")).toBeVisible();
    },
  });
  gate.assertNoErrors();
});
