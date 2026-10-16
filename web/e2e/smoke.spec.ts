import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { red } from "../tests/support/red.ts";
import { statePath } from "./global-setup.ts";

type SmokePage = {
  goto: (url: string) => Promise<unknown>;
  getByRole: (
    role: "button",
    options: { name: string },
  ) => { click: () => Promise<unknown> };
  getByText: (text: RegExp) => unknown;
};

type ExpectVisible = (actual: unknown) => {
  toBeVisible: (options: { timeout: number }) => Promise<unknown>;
};

const nodeRequire = createRequire(import.meta.url);

async function runSmoke(page: SmokePage, expect: ExpectVisible): Promise<void> {
  const state = JSON.parse(readFileSync(statePath, "utf8")) as {
    baseURL: string;
    token: string;
  };
  await page.goto(
    `${state.baseURL}/auth/login?token=${encodeURIComponent(state.token)}`,
  );
  await page.getByRole("button", { name: "Ping" }).click();
  await expect(page.getByText(/event #\d+/)).toBeVisible({ timeout: 2000 });
}

if (process.env.VITEST) {
  red("W6")("click Ping shows event # and a number", async () => {
    const playwrightPackage = "@playwright/test";
    const playwright = (await import(playwrightPackage)) as {
      chromium: {
        launch: () => Promise<{
          newPage: () => Promise<SmokePage>;
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
      await runSmoke(await browser.newPage(), playwright.expect);
    } finally {
      await browser.close();
      await teardown();
    }
  });
} else {
  const playwrightPackage = ["@playwright", "test"].join("/");
  const playwright = nodeRequire(playwrightPackage) as {
    test: {
      (name: string, fn: (args: { page: SmokePage }) => Promise<void>): void;
      skip: (condition: boolean, description: string) => void;
    };
    expect: ExpectVisible;
  };
  playwright.test(
    "click Ping shows event # and a number [green after W6]",
    async ({ page }) => {
      playwright.test.skip(
        process.env.SEVN_RUN_MARKED !== "1",
        "green after W6",
      );
      await runSmoke(page, playwright.expect);
    },
  );
}
