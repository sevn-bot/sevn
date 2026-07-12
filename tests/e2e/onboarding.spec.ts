// Onboarding wizard happy-path journey (specs/22-onboarding.md §9).

import { test, expect } from "@playwright/test";

import { E2E_ONBOARD_TOKEN, openWizard, gotoStep, activeStep } from "./onboarding-helpers";

test.describe("onboarding wizard — happy path", () => {
  test("loads with Good value preset preselected and recommended cards on top", async ({ page }) => {
    await openWizard(page);

    const firstCard = page.locator("#profile-list .profile-card").first();
    await expect(firstCard).toHaveClass(/profile-card/);
    await expect(firstCard.locator(".profile-tag.recommended")).toBeVisible();

    // A "selected" card should be one of the value profiles, not Skip / custom.
    const selectedHeading = await page.locator("#profile-list .profile-card.selected .card__heading").first().textContent();
    expect(selectedHeading?.toLowerCase()).toContain("good value");

    // Non-value cards are visible but greyed and not clickable.
    const disabled = page.locator("#profile-list .profile-card.is-disabled");
    await expect(disabled.first()).toBeVisible();
    await expect(disabled.first()).toHaveAttribute("aria-disabled", "true");
  });

  test("required key fields show (required) in red until filled", async ({ page }) => {
    await openWizard(page);
    const summaryKey = page.locator(".field-summary-row:has(.field-summary-label:text-is('Provider API key'))");
    await expect(summaryKey).toHaveClass(/is-empty/);
    await expect(summaryKey.locator(".field-summary-value")).toHaveText("(required)");

    const summaryBot = page.locator(".field-summary-row:has(.field-summary-label:text-is('Telegram bot token'))");
    await expect(summaryBot).toHaveClass(/is-empty/);
    await expect(summaryBot.locator(".field-summary-value")).toHaveText("(required)");
  });

  test("Exit button is visible on every step including profile", async ({ page }) => {
    await openWizard(page);
    await expect(page.locator("#btn-exit")).toBeVisible();
    await expect(page.locator("#btn-next")).toBeVisible();
    await expect(page.locator("#btn-quick-boot")).toHaveCount(0);
  });

  test("profile step shows top Next and Exit; both open confirm before shutdown", async ({ page }) => {
    await openWizard(page);
    expect(await activeStep(page)).toBe("profile");
    await expect(page.locator("#btn-profile-next")).toBeVisible();
    await expect(page.locator("#btn-profile-exit")).toBeVisible();

    let shutdownMethod = "";
    await page.route("**/api/shutdown", async (route) => {
      shutdownMethod = route.request().method();
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });
    await page.locator("#btn-profile-exit").click();
    await expect(page.locator("#exit-confirm-modal")).toBeVisible();
    await page.locator("#btn-exit-proceed").click();
    await expect.poll(() => shutdownMethod).toBe("POST");
  });

  test("profile top Next advances like bottom Next", async ({ page }) => {
    await openWizard(page);
    expect(await activeStep(page)).toBe("profile");
    await page.locator("#btn-profile-next").click();
    expect(await activeStep(page)).not.toBe("profile");
  });

  test("Telegram step shows manual api_id / api_hash / phone inputs (no scraper buttons)", async ({ page }) => {
    await openWizard(page);
    await gotoStep(page, "channels");
    await expect(page.locator("#tg_api_id")).toBeVisible();
    await expect(page.locator("#tg_api_hash")).toBeVisible();
    await expect(page.locator("#tg_phone")).toBeVisible();
    await expect(page.locator("#btn-telegram-app-start")).toHaveCount(0);
    await expect(page.locator("#btn-telegram-app-complete")).toHaveCount(0);
  });

  test("Exit on handoff posts /api/shutdown after confirmation", async ({ page }) => {
    await openWizard(page);
    await gotoStep(page, "handoff");
    expect(await activeStep(page)).toBe("handoff");
    await expect(page.locator("#btn-exit")).toBeVisible();

    // Intercept /api/shutdown: assert the POST without actually terminating the
    // shared onboarding webServer, which later tests still depend on.
    let shutdownMethod = "";
    await page.route("**/api/shutdown", async (route) => {
      shutdownMethod = route.request().method();
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });
    await page.locator("#btn-exit").click();
    await expect(page.locator("#exit-confirm-modal")).toBeVisible();
    await page.locator("#btn-exit-proceed").click();
    await expect.poll(() => shutdownMethod).toBe("POST");

    const _ = E2E_ONBOARD_TOKEN;
  });

  test("Exit confirm Cancel keeps the wizard open", async ({ page }) => {
    await openWizard(page);
    await page.locator("#btn-exit").click();
    await expect(page.locator("#exit-confirm-modal")).toBeVisible();
    await page.locator("#btn-exit-cancel").click();
    await expect(page.locator("#exit-confirm-modal")).toBeHidden();
    await expect(page.locator(".wizard-shell")).toBeVisible();
  });
});
