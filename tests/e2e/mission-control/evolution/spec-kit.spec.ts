// Mission Control — Spec-Kit tab (MC W3c).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { mcApiGet, mcApiPut } from "../_api-seed";
import { shot } from "../_helpers";
import { runTabSpec, type TabSpecContext } from "../_tab-spec";

test("spec-kit — constitution/options edit+restore, test invoke", async ({ page }) => {
  let savedConstitution = "";
  let savedOptions: Record<string, unknown> = {};

  await runTabSpec(page, "spec-kit", {
    skipActions: ["save-constitution", "reset-template", "save-options", "test-invoke"],
    beforeActions: async (ctx: TabSpecContext) => {
      const constitution = await mcApiGet<{ text?: string }>(
        ctx.page,
        "/api/v1/spec-kit/constitution",
      );
      savedConstitution = constitution.text || "";
      savedOptions = await mcApiGet<Record<string, unknown>>(
        ctx.page,
        "/api/v1/spec-kit/options",
      );
    },
    visitViews: async (ctx: TabSpecContext) => {
      const { page: p, slug } = ctx;

      const textarea = p.locator("#spec-kit-constitution");
      await textarea.fill(`${savedConstitution}\n\n<!-- mc-e2e throwaway -->\n`);
      await p.locator("#spec-kit-save").click();
      await p.waitForTimeout(400);
      await shot(p, slug, "constitution-saved");
      await textarea.fill(savedConstitution);
      await p.locator("#spec-kit-save").click();
      await p.waitForTimeout(400);
      await shot(p, slug, "constitution-restored");

      const dryRun = p.locator('[name="dry_run_default"]');
      const wasChecked = await dryRun.isChecked();
      await dryRun.setChecked(!wasChecked);
      await p.locator("#spec-kit-options-save").click();
      await p.waitForTimeout(400);
      await shot(p, slug, "options-saved");
      await dryRun.setChecked(wasChecked);
      await p.locator("#spec-kit-options-save").click();
      await p.waitForTimeout(400);
      await shot(p, slug, "options-restored");

      await p.locator("#spec-kit-test-plan").click();
      await p.waitForTimeout(1500);
      await shot(p, slug, "test-invoke");

      await mcApiPut(p, "/api/v1/spec-kit/constitution", { text: savedConstitution });
      await mcApiPut(p, "/api/v1/spec-kit/options", savedOptions);
    },
  });
});
