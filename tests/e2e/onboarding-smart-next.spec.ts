// Smart Next + clickable sidebar (specs/22-onboarding.md §4.1).

import { test, expect } from "@playwright/test";

import { openWizard, gotoStep, activeStep, completedSteps } from "./onboarding-helpers";

test.describe("onboarding wizard — smart navigation", () => {
  test("Next from profile jumps past tabs satisfied by Good value defaults", async ({ page }) => {
    await openWizard(page);
    expect(await activeStep(page)).toBe("profile");
    await page.locator("#btn-next").click();
    // Good value preset satisfies workspace/features/sandbox/tunnel; bot name is still required.
    expect(await activeStep(page)).toBe("my_sevn");
  });

  test("filling required inputs flips sidebar checkmarks live", async ({ page }) => {
    await openWizard(page);
    await gotoStep(page, "my_sevn");
    await page.locator("#agent_name").fill("My sevn assistant");
    await page.locator("#agent_name").blur();
    const done = await completedSteps(page);
    expect(done).toContain("my_sevn");
  });

  test("Skip / custom mode advances one step at a time", async ({ page }) => {
    await openWizard(page);
    await page.locator("#profile-list .profile-card", { hasText: /skip\s*\/\s*custom/i }).click();
    await page.locator("#btn-next").click();
    expect(await activeStep(page)).toBe("workspace");
    await page.locator("#btn-next").click();
    expect(await activeStep(page)).toBe("my_sevn");
  });

  test("every sidebar entry is clickable (no maxVisited gating)", async ({ page }) => {
    await openWizard(page);
    await gotoStep(page, "tunnel");
    expect(await activeStep(page)).toBe("tunnel");
    await gotoStep(page, "features");
    expect(await activeStep(page)).toBe("features");
  });
});
