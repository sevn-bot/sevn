// Mission Control — Egress proxy tab (MC W3d).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { runTabSpec } from "../_tab-spec";

test("egress-proxy — refresh logs; restart gated unless disruptive", async ({ page }) => {
  await runTabSpec(page, "egress-proxy", {
    handleAction: async (ctx, action) => {
      if (action.id === "refresh-logs") {
        await ctx.page.locator("#proxy-refresh-logs-btn").click();
        await expect(ctx.page.locator("#proxy-log-tail")).toBeVisible({ timeout: 15_000 });
        return;
      }
      if (action.destructive && process.env.SEVN_MC_E2E_ALLOW_DISRUPTIVE !== "1") {
        await expect(ctx.page.locator(action.selector).first()).toBeVisible();
        return;
      }
      await ctx.page.locator(action.selector).first().click();
      await ctx.page.waitForTimeout(300);
    },
  });
});
