import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  globalSetup: "./global-setup.ts",
  globalTeardown: "./global-teardown.ts",
  timeout: 30_000,
  globalTimeout: 120_000,
  outputDir: "../../.ignorelocal/playwright-output",
  use: {
    headless: true,
  },
});
