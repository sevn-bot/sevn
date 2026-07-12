// Dispatch-a-turn journey — specs/25-cicd-full.md §10.4 (Web UI channel, Wave 6).

import { test, expect } from "@playwright/test";

import { openWebchat } from "./helpers";

test.describe("dispatch-turn → webchat", () => {
  test("a user message receives an assistant echo", async ({ page }) => {
    await openWebchat(page);

    const input = page.locator("#text");
    await input.fill("hello from e2e");
    await page.getByRole("button", { name: /send/i }).click();

    await expect(page.locator(".msg--user .msg__body")).toContainText("hello from e2e");
    await expect(page.locator(".msg--assistant .msg__body")).toContainText("echo: hello from e2e", {
      timeout: 15_000,
    });
  });
});
