// Mission Control E2E data-path assertion helpers (plan #11 Wave E0).

import { expect, type Page } from "@playwright/test";

/** Fetch budget summary and assert non-empty provider-backed regimes. */
export async function assertBudgetNonEmpty(page: Page): Promise<void> {
  const resp = await page.request.get("/api/v1/budget/summary");
  expect(resp.ok()).toBeTruthy();
  const body = (await resp.json()) as { by_regime?: unknown[] };
  expect(Array.isArray(body.by_regime)).toBeTruthy();
  expect((body.by_regime ?? []).length).toBeGreaterThan(0);
}

/** Fetch trajectories API and assert at least one ingested row. */
export async function assertTrajectoriesNonEmpty(page: Page): Promise<void> {
  const resp = await page.request.get("/api/v1/self_improve/trajectories?limit=10");
  expect(resp.ok()).toBeTruthy();
  const body = (await resp.json()) as { items?: unknown[] };
  expect(Array.isArray(body.items)).toBeTruthy();
  expect((body.items ?? []).length).toBeGreaterThan(0);
}

/** Negative baseline: budget summary has no provider.call regimes on fixture workspace. */
export async function assertBudgetEmpty(page: Page): Promise<void> {
  const resp = await page.request.get("/api/v1/budget/summary");
  expect(resp.ok()).toBeTruthy();
  const body = (await resp.json()) as { by_regime?: unknown[] };
  expect(body.by_regime ?? []).toEqual([]);
}

/** Negative baseline: trajectories list is empty without ingest hook. */
export async function assertTrajectoriesEmpty(page: Page): Promise<void> {
  const resp = await page.request.get("/api/v1/self_improve/trajectories?limit=10");
  expect(resp.ok()).toBeTruthy();
  const body = (await resp.json()) as { items?: unknown[] };
  expect(body.items ?? []).toEqual([]);
}

/** True when Playwright runs against the fixture MC workspace (not operator local). */
export function isMcFixtureMode(): boolean {
  return process.env.SEVN_MC_E2E_LOCAL !== "1";
}

/** True when fixture seed wrote provider.call rows for data-path specs (E1). */
export function isMcDataPathSeedEnabled(): boolean {
  return process.env.SEVN_MC_DATA_PATH_SEED === "1";
}

/** Fetch channel status and assert at least one connected runtime row. */
export async function assertChannelsRuntimeNonEmpty(page: Page): Promise<void> {
  const resp = await page.request.get("/api/v1/channels/status");
  expect(resp.ok()).toBeTruthy();
  const body = (await resp.json()) as {
    channels?: { name?: string; connected?: boolean }[];
  };
  const rows = body.channels ?? [];
  expect(rows.length).toBeGreaterThan(0);
  expect(rows.some((row) => row.connected === true)).toBeTruthy();
}

/** Assert provider-backed budget telemetry is present (proxy for provider stats). */
export async function assertProvidersStatsNonEmpty(page: Page): Promise<void> {
  await assertBudgetNonEmpty(page);
}
