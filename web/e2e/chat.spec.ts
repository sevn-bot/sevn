import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { statePath } from "./global-setup.ts";

type ChatPage = {
  goto: (url: string) => Promise<unknown>;
  getByRole: (
    role: "button" | "textbox",
    options: { name: string },
  ) => {
    click: () => Promise<unknown>;
    fill: (value: string) => Promise<unknown>;
    isVisible: () => Promise<boolean>;
  };
  getByText: (text: string) => {
    click: () => Promise<unknown>;
  };
};

type ExpectVisible = (actual: unknown) => {
  toBeVisible: (options: { timeout: number }) => Promise<unknown>;
};

const nodeRequire = createRequire(import.meta.url);

async function runChat(page: ChatPage, expect: ExpectVisible): Promise<void> {
  const state = JSON.parse(readFileSync(statePath, "utf8")) as {
    baseURL: string;
    token: string;
  };
  await page.goto(
    `${state.baseURL}/auth/login?token=${encodeURIComponent(state.token)}`,
  );
  await page.getByRole("button", { name: "Create bot" }).click();
  await page.getByRole("textbox", { name: "Name" }).fill("Echo chat");
  await page.getByRole("button", { name: "Create" }).click();
  const message = page.getByRole("textbox", { name: "Message" });
  if (!(await message.isVisible())) {
    await page.getByText("Echo chat").click();
  }
  await message.fill("hi");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("echo: hi")).toBeVisible({ timeout: 10_000 });
}

if (process.env.VITEST) {
  const { test } = (await import("vitest")) as {
    test: (name: string, fn: () => Promise<void>) => void;
  };
  test("create a bot, send hi, see echo: hi", async () => {
    const playwrightPackage = "@playwright/test";
    const playwright = (await import(playwrightPackage)) as {
      chromium: {
        launch: () => Promise<{
          newPage: () => Promise<ChatPage>;
          close: () => Promise<void>;
        }>;
      };
      expect: ExpectVisible;
    };
    const { default: setup } = await import("./global-setup.ts");
    const { default: teardown } = await import("./global-teardown.ts");
    await setup();
    const browser = await playwright.chromium.launch();
    try {
      await runChat(await browser.newPage(), playwright.expect);
    } finally {
      await browser.close();
      await teardown();
    }
  });
} else {
  const playwrightPackage = ["@playwright", "test"].join("/");
  const playwright = nodeRequire(playwrightPackage) as {
    test: (
      name: string,
      fn: (args: { page: ChatPage }) => Promise<void>,
    ) => void;
    expect: ExpectVisible;
  };
  playwright.test("create a bot, send hi, see echo: hi", async ({ page }) => {
    await runChat(page, playwright.expect);
  });
}
