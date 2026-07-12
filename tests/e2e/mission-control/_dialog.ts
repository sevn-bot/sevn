// Safe confirm/prompt dialog handling for shared MC E2E sessions.
//
// Race `waitForEvent("dialog")` with the triggering action — never register persistent
// `page.on("dialog")` handlers; they leak across shared-session tests.

import type { Page } from "@playwright/test";

import { mcE2ePanelTimeout } from "./_helpers";

/** Accept the next browser dialog fired by `trigger`. */
export async function acceptNextDialog(
  page: Page,
  trigger: () => Promise<void>,
  promptText?: string,
): Promise<void> {
  const timeout = mcE2ePanelTimeout();
  await Promise.all([
    (async () => {
      const dialog = await page.waitForEvent("dialog", { timeout });
      if (promptText !== undefined && dialog.type() === "prompt") {
        await dialog.accept(promptText);
        return;
      }
      await dialog.accept();
    })(),
    trigger(),
  ]);
}

/** Accept a confirm/alert dialog triggered by `trigger`. */
export async function acceptConfirmDialog(
  page: Page,
  trigger: () => Promise<void>,
): Promise<void> {
  await acceptNextDialog(page, trigger);
}

/** Accept a prompt dialog with fixed input text. */
export async function acceptPromptDialog(
  page: Page,
  promptText: string,
  trigger: () => Promise<void>,
): Promise<void> {
  await acceptNextDialog(page, trigger, promptText);
}
