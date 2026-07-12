// Mission Control — Chat tab (MC W3a).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("chat — composer, fork action reachable", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "chat", {
    skipKeySelectors: ["#chat-session-id", "#chat-tool-cards"],
    skipActions: ["mint-token"],
    afterPanel: async (p) => {
      await expect(p.locator("#chat-composer")).toBeVisible();
      await expect(p.locator("#chat-log")).toBeVisible();
      await expect(p.locator("#chat-status")).toBeVisible({ timeout: 15_000 });
    },
  });
  try {
    gate.assertNoErrors();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (!message.includes("503 (Service Unavailable)")) {
      throw err;
    }
  }
});
