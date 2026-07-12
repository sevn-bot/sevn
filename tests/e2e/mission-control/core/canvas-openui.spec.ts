// Mission Control — Canvas (OpenUI) tab (MC W3a).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("canvas-openui — unconfigured or iframe frame contract", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "canvas-openui", {
    skipKeySelectors: [".mission-canvas-frame", ".mission-canvas-iframe"],
    afterPanel: async (p) => {
      const panel = p.locator("#content > article.card");
      const frame = p.locator(".mission-canvas-frame");
      const iframe = p.locator(".mission-canvas-iframe");
      if (await frame.isVisible()) {
        await expect(iframe).toBeVisible();
        return;
      }
      await expect(panel.getByText(/OpenUI/i).first()).toBeVisible();
    },
  });
  gate.assertNoErrors();
});
