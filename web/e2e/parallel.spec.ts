import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { statePath } from "./global-setup.ts";

const run = process.env.SEVN_RUN_MARKED === "1" ? test : test.skip;

run(
  "two requests run as two lanes at once [green after W8]",
  async ({ page }) => {
    const state = JSON.parse(readFileSync(statePath, "utf8")) as {
      baseURL: string;
      token: string;
    };
    await page.goto(
      `${state.baseURL}/auth/login?token=${encodeURIComponent(state.token)}`,
    );
    await page.getByRole("button", { name: "Create bot" }).click();
    await page.getByRole("textbox", { name: "Name" }).fill("Echo");
    await page.getByRole("button", { name: "Create" }).click();
    const message = page.getByRole("textbox", { name: "Message" });
    if (!(await message.isVisible())) {
      await page.getByText("Echo").click();
    }
    const started = Date.now();
    await message.fill("one-lane-marker");
    await page.getByRole("button", { name: "Send" }).click();
    await message.fill("/new two-lane-marker");
    await page.getByRole("button", { name: "Send" }).click();
    const deadline = started + 2500;
    await expect(page.getByText("one-lane-marker")).toBeVisible({
      timeout: Math.max(deadline - Date.now(), 1),
    });
    await expect(page.getByText("two-lane-marker")).toBeVisible({
      timeout: Math.max(deadline - Date.now(), 1),
    });
    const lanes = page.locator("details").filter({ hasNotText: "Settings" });
    await expect(lanes).toHaveCount(2, {
      timeout: Math.max(deadline - Date.now(), 1),
    });
    const elapsed = Date.now() - started;
    expect(elapsed).toBeGreaterThanOrEqual(1500);
    expect(elapsed).toBeLessThanOrEqual(2500);
  },
);
