// Login journey — specs/25-cicd-full.md §10.4 (Web UI channel, Wave 6).

import { test, expect } from "@playwright/test";

import { E2E_GATEWAY_TOKEN, openWebchat } from "./helpers";

test.describe("login journey", () => {
  test("operator can open webchat shell", async ({ page }) => {
    await openWebchat(page);
    await expect(page).toHaveTitle(/sevn\.bot/i);
    await expect(page.locator(".navbar__name")).toContainText(/sevn\.bot/i);
    await expect(page.locator("#composer")).toBeVisible();
  });

  test("login page redirects to webchat after token submit", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator("h1")).toContainText(/login/i);
    await page.locator("#token").fill(E2E_GATEWAY_TOKEN);
    await page.getByRole("button", { name: /continue/i }).click();
    await expect(page).toHaveURL(/\/webapp\/?/);
    await expect(page.locator("#status")).toContainText(/connected/i, { timeout: 15_000 });
  });
});
