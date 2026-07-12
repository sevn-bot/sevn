// Mission Control — Claude Agent post-v1 placeholder (MC W3a).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("claude-agent — post-v1 placeholder copy only", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "claude-agent", {
    afterPanel: async (p) => {
      const panel = p.locator(".post-v1-panel");
      await expect(panel.getByRole("heading", { name: /Claude Agent \(post-v1\)/i })).toBeVisible();
      await expect(panel.getByText(/not shipped in v1/i)).toBeVisible();
      await expect(panel.getByText(/tier-C executor/i)).toBeVisible();
    },
  });
  gate.assertNoErrors();
});
