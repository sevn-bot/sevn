// @mc-e2e-data-path — G3 experiments bucket (positive when SEVN_MC_DATA_PATH_SEED=1)
// Mission Control — Experiments & Metrics tab (MC W3c, read-only).

import { expect, test } from "../fixtures";

import { isMcDataPathSeedEnabled, isMcFixtureMode } from "../_data-path";
import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

const DATA_PATH_EXPERIMENT_ID = "e2e-mc-experiment";

test("experiments-metrics — experiment aggregates", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "experiments-metrics", {
    afterPanel: async (p) => {
      if (!isMcFixtureMode() || !isMcDataPathSeedEnabled()) {
        return;
      }
      const expResp = await p.request.get("/api/v1/self_improve/experiments?limit=10");
      expect(expResp.ok()).toBeTruthy();
      const expBody = (await expResp.json()) as {
        experiments?: {
          experiment_id?: string;
          latest_job_id?: string;
          job_count?: number;
          eval_passed?: boolean | null;
        }[];
      };
      const experiments = expBody.experiments ?? [];
      expect(experiments.length).toBeGreaterThan(0);
      const match = experiments.find((row) => row.experiment_id === DATA_PATH_EXPERIMENT_ID);
      expect(match).toBeTruthy();
      expect((match?.job_count ?? 0)).toBeGreaterThan(0);
      const jobId = match?.latest_job_id;
      expect(jobId).toBeTruthy();
      const reportResp = await p.request.get(`/api/v1/self_improve/jobs/${jobId}/eval_report`);
      expect(reportResp.ok()).toBeTruthy();
      const reportBody = (await reportResp.json()) as {
        job_id?: string;
        report?: { passed?: boolean };
      };
      expect(reportBody.job_id).toBe(jobId);
      expect(reportBody.report?.passed).toBe(true);
    },
  });
  gate.assertNoErrors();
});
