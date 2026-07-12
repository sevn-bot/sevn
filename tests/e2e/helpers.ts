// Shared helpers for Playwright journeys (specs/25-cicd-full.md §10.4).

import { expect, type Page } from "@playwright/test";

/** Gateway bearer used by `infra/ci-workspace/sevn.json` compose seed. */
export const E2E_GATEWAY_TOKEN = "e2e-dev-token";

/** Open webchat, logging in when the gateway bearer gate redirects to `/login`. */
export async function openWebchat(page: Page): Promise<void> {
  await page.goto("/webapp/");
  // `/webapp/` loads first; `app.js` fetches `/api/webchat/config` then may redirect
  // to `/login` client-side. Do not probe `#token` until that gate settles.
  await page.waitForFunction(
    () =>
      location.pathname.startsWith("/login") ||
      (document.querySelector("#status")?.textContent ?? "")
        .toLowerCase()
        .includes("connected"),
    { timeout: 15_000 },
  );

  const tokenField = page.locator("#token");
  if (await tokenField.isVisible()) {
    await tokenField.fill(E2E_GATEWAY_TOKEN);
    await page.getByRole("button", { name: /continue/i }).click();
    await expect(page).toHaveURL(/\/webapp\/?/);
  }
  await expect(page.locator("#status")).toContainText(/connected/i, { timeout: 15_000 });
}
