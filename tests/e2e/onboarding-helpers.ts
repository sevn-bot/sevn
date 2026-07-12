// Shared helpers for the onboarding wizard Playwright journeys
// (specs/22-onboarding.md §9).

import { expect, type Page } from "@playwright/test";

/** Token pinned via SEVN_ONBOARD_TOKEN env var on the webServer (see playwright.config). */
export const E2E_ONBOARD_TOKEN = "playwright-onboard-token";

/**
 * Map of wizard `data-step` ids to the human-readable sidebar labels the
 * `#stepsNav` buttons render. Specs navigate by stable `data-step` id; the
 * sidebar only exposes display names, so nav clicks resolve through this map.
 */
export const STEP_LABELS: Record<string, string> = {
  existing: "Existing",
  profile: "Profile",
  workspace: "Workspace",
  my_sevn: "My Sevn.bot",
  model: "Main model",
  channels: "Channels",
  features: "Features",
  secrets: "Secrets",
  sandbox: "Sandbox",
  tunnel: "Public access",
  validate: "Validate",
  promote: "Promote",
  handoff: "Handoff",
};

const LABEL_TO_STEP: Record<string, string> = Object.fromEntries(
  Object.entries(STEP_LABELS).map(([step, label]) => [label, step]),
);

/** Open the wizard root with the pinned onboard token. */
export async function openWizard(page: Page): Promise<void> {
  await page.goto(`/?onboard_token=${E2E_ONBOARD_TOKEN}`);
  await expect(page.locator(".wizard-shell")).toBeVisible({ timeout: 15_000 });
  await page.waitForFunction(
    () => !!document.getElementById("profile-list")?.children.length,
    { timeout: 10_000 },
  );
  await page.waitForFunction(
    () => document.body.dataset.wizardReady === "1",
    { timeout: 15_000 },
  );
}

/** Switch to a step by clicking its sidebar entry (addressed by `data-step`). */
export async function gotoStep(page: Page, step: string): Promise<void> {
  const label = STEP_LABELS[step] ?? step;
  await page
    .locator(`#stepsNav button.wizard-nav-step:has(.wizard-nav-name:text-is("${label}"))`)
    .click();
  await expect(page.locator(`.wizard-step[data-step="${step}"]`)).toHaveClass(/active/);
}

/** Read the data-step value of the currently active wizard section. */
export async function activeStep(page: Page): Promise<string | null> {
  return page.evaluate(
    () => document.querySelector(".wizard-step.active")?.getAttribute("data-step") ?? null,
  );
}

/** Return the list of sidebar step entries (as `data-step` ids) carrying `.done`. */
export async function completedSteps(page: Page): Promise<string[]> {
  return page.evaluate((labelToStep) =>
    Array.from(document.querySelectorAll("#stepsNav .wizard-nav-step.done")).map((el) => {
      const name = el.querySelector(".wizard-nav-name")?.textContent?.trim() ?? "";
      return labelToStep[name] ?? name;
    }),
  LABEL_TO_STEP);
}
