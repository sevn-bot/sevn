// Mission Control Playwright fixtures — optional shared browser session for headed debug.
//
// Session reuse:
// - `make mc-e2e-headed` / `make mc-e2e-local-headed` set `SEVN_MC_E2E_SHARED_SESSION=1`
//   so every spec shares one worker-scoped BrowserContext + Page for the full suite.
// - The first test opens `/mission/` and completes auth; later tests reuse the same
//   window and navigate tab-to-tab via `gotoTab` (no full reload — `openDashboard` no-ops).
// - Headless `make mc-e2e` leaves the env unset — each test gets an isolated
//   context/page (Playwright default isolation) so CI stays deterministic.
//
// Requires `--workers=1` when sharing (enforced in headed Makefile targets).

import { test as base, expect, type Page } from "@playwright/test";

import { ensureAuth, openDashboard, resetErrorGate } from "./_helpers";

const shareSession = process.env.SEVN_MC_E2E_SHARED_SESSION === "1";

function mcBaseUrl(): string {
  const port = process.env.SEVN_MC_PORT?.trim() || "13004";
  return (process.env.SEVN_MC_BASE_URL || `http://127.0.0.1:${port}`).replace(/\/$/, "");
}

export const test = base.extend<{}, { workerPage: Page }>({
  workerPage: [
    async ({ browser }, use) => {
      const context = await browser.newContext({ baseURL: mcBaseUrl() });
      const page = await context.newPage();
      await openDashboard(page);
      await ensureAuth(page);
      try {
        await use(page);
      } finally {
        await context.close();
      }
    },
    { scope: "worker", auto: shareSession },
  ],

  page: async ({ browser, workerPage }, use) => {
    if (shareSession) {
      resetErrorGate(workerPage);
      await use(workerPage);
      return;
    }
    const context = await browser.newContext({ baseURL: mcBaseUrl() });
    const page = await context.newPage();
    try {
      await use(page);
    } finally {
      await context.close();
    }
  },
});

export { expect };
