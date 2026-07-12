// @mc-e2e-data-path — G11 jobs enqueue/cycle (E6, requires #2 proposer)
// Mission Control — Jobs tab (MC W3c).

import { expect, test } from "../fixtures";

import { isMcDataPathSeedEnabled, isMcFixtureMode } from "../_data-path";
import { runTabSpec } from "../_tab-spec";

test("jobs — list view, enqueue and cycle controls", async ({ page }) => {
  const skipActions =
    isMcFixtureMode() && !isMcDataPathSeedEnabled() ? ["enqueue", "cycle"] : undefined;
  await runTabSpec(page, "jobs", {
    skipActions,
    afterPanel: async (p) => {
      if (!isMcFixtureMode() || !isMcDataPathSeedEnabled()) {
        return;
      }
      const resp = await p.request.get("/api/v1/self_improve/jobs?limit=5");
      expect(resp.ok()).toBeTruthy();
      const body = (await resp.json()) as { items?: { job_id?: string }[] };
      expect((body.items ?? []).length).toBeGreaterThan(0);
      const jobId = body.items?.[0]?.job_id;
      expect(jobId).toBeTruthy();
      const patchResp = await p.request.get(`/api/v1/self_improve/jobs/${jobId}/patch`);
      if (patchResp.ok()) {
        const patchBody = await patchResp.text();
        expect(patchBody).not.toContain("self_improve_deterministic_stub");
      }
    },
  });
});
