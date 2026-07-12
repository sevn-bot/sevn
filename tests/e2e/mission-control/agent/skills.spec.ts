// Mission Control — Skills tab (MC W3b).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { acceptConfirmDialog } from "../_dialog";
import { shot } from "../_helpers";
import {
  apiDeleteJson,
  apiGetJson,
  gotoTabReady,
  runTabViews,
  setupTabTest,
  tabSchema,
} from "../_tabRunner";

type BundledSkillsBody = { skills: string[] };
type SkillsBody = { skills: Array<{ id: string; provenance: string }> };

test("skills — install, toggle, uninstall throwaway skill", async ({ page }) => {
  test.setTimeout(60_000);
  const gate = await setupTabTest(page);
  const slug = "skills";
  tabSchema(slug);

  const listed = await apiGetJson<SkillsBody>(page, "/api/v1/agent/skills");
  for (const row of listed.skills.filter((skill) => skill.provenance === "user")) {
    await apiDeleteJson(page, `/api/v1/agent/skills/${encodeURIComponent(row.id)}`, {
      confirm_token: "confirm",
    });
  }

  const bundled = await apiGetJson<BundledSkillsBody>(page, "/api/v1/agent/skills/bundled");
  const skillName = bundled.skills[0];
  test.skip(!skillName, "no bundled skills available");

  await runTabViews(page, slug);

  await page.locator("#skill-install-select").selectOption(skillName);
  await acceptConfirmDialog(page, () =>
    page.locator("#skill-install-form button[type='submit']").click(),
  );
  await expect(page.locator("table").getByText(skillName, { exact: true }).first()).toBeVisible({
    timeout: 15_000,
  });
  await shot(page, slug, "installed");

  const toggle = page.locator(`.skill-toggle-btn[data-skill="${skillName}"]`);
  if (await toggle.count()) {
    await toggle.first().click();
    await shot(page, slug, "toggled");
    await gotoTabReady(page, slug);
  }

  const uninstall = page.locator(`.skill-uninstall-btn[data-skill="${skillName}"]`);
  await expect(uninstall.first()).toBeVisible({ timeout: 15_000 });
  await acceptConfirmDialog(page, () => uninstall.first().click());
  await gotoTabReady(page, slug);

  const listedAfter = await apiGetJson<SkillsBody>(page, "/api/v1/agent/skills");
  const installed = listedAfter.skills.filter(
    (row) => row.id === skillName && row.provenance === "user",
  );
  expect(installed).toHaveLength(0);
  await shot(page, slug, "uninstalled");

  gate.assertNoErrors();
});
