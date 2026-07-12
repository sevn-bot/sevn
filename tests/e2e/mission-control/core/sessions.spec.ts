// Mission Control — Sessions tab (MC W3a).
// @mc-e2e-contract — G8 api-calls session (data-path: E1)

import { expect, test } from "../fixtures";

import { isMcDataPathSeedEnabled, isMcFixtureMode } from "../_data-path";
import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("sessions — list, api-calls sub-view", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "sessions", {
    viewHooks: {
      list: async (p) => {
        await expect(p.locator("#content > article.card")).toBeVisible();
      },
      "api-calls": async (p) => {
        const apiLink = p.locator('a[href*="/api-calls"]').first();
        if (await apiLink.isVisible()) {
          await apiLink.click();
        } else {
          await p.goto("/mission/sessions/e2e-mc-session/api-calls");
        }
        await expect(p.locator("#content > article.card")).toContainText("API calls", {
          timeout: 15_000,
        });
        if (isMcFixtureMode() && isMcDataPathSeedEnabled()) {
          const resp = await p.request.get("/api/v1/sessions/e2e-mc-session/api-calls?limit=10");
          expect(resp.ok()).toBeTruthy();
          const body = (await resp.json()) as { items?: { kind?: string }[] };
          const kinds = (body.items ?? []).map((row) => row.kind);
          expect(kinds).toContain("provider.call");
        }
      },
    },
  });
  gate.assertNoErrors();
});
