import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { statePath } from "./global-setup.ts";

test("two requests run as two lanes at once", async ({ page }) => {
  const state = JSON.parse(readFileSync(statePath, "utf8")) as {
    baseURL: string;
    token: string;
  };
  await page.goto(
    `${state.baseURL}/auth/login?token=${encodeURIComponent(state.token)}`,
  );
  await page.getByRole("button", { name: "Create bot" }).click();
  await page.getByRole("textbox", { name: "Name" }).fill("Echo lanes");
  await page.getByRole("button", { name: "Create" }).click();
  const message = page.getByRole("textbox", { name: "Message" });
  if (!(await message.isVisible())) {
    await page.getByText("Echo lanes").click();
  }
  await message.fill("one-lane-marker");
  await page.getByRole("button", { name: "Send" }).click();
  await message.fill("/new two-lane-marker");
  await page.getByRole("button", { name: "Send" }).click();
  const lanes = page.locator("details").filter({ hasNotText: "Settings" });
  await expect(lanes).toHaveCount(2, { timeout: 10_000 });
  await expect(
    page.getByText("echo: one-lane-marker", { exact: true }),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.getByText("echo: /new two-lane-marker", { exact: true }),
  ).toBeVisible({ timeout: 10_000 });
});
