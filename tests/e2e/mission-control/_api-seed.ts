// Mission Control E2E API seed helpers (MC W3 — create-before-delete via browser fetch).

import { expect, type Page } from "@playwright/test";

import { mcE2ePanelTimeout } from "./_helpers";
import { csrfHeaders } from "./_tabRunner";

async function mcFetch<T>(
  page: Page,
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers = { ...(await csrfHeaders(page)) };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const resp = await page.request.fetch(path, {
    method,
    headers,
    data: body === undefined ? undefined : body,
  });
  const text = await resp.text();
  if (!resp.ok()) {
    throw new Error(`${method} ${path} → ${resp.status()}: ${text.slice(0, 400)}`);
  }
  return (text ? JSON.parse(text) : null) as T;
}

/** GET `/api/v1/*` from the authenticated dashboard session. */
export async function mcApiGet<T = Record<string, unknown>>(
  page: Page,
  path: string,
): Promise<T> {
  return mcFetch<T>(page, "GET", path);
}

/** POST `/api/v1/*` from the authenticated dashboard session. */
export async function mcApiPost<T = Record<string, unknown>>(
  page: Page,
  path: string,
  body?: unknown,
): Promise<T> {
  return mcFetch<T>(page, "POST", path, body);
}

/** PUT `/api/v1/*` from the authenticated dashboard session. */
export async function mcApiPut<T = Record<string, unknown>>(
  page: Page,
  path: string,
  body?: unknown,
): Promise<T> {
  return mcFetch<T>(page, "PUT", path, body);
}

type EvolutionIssue = { id: string };

type ApprovalRow = { id: string; issue_id?: string };

type ApprovalsPage = { items?: ApprovalRow[] };

/** Create a throwaway local evolution issue for pipeline / issues specs. */
export async function seedEvolutionIssue(
  page: Page,
  suffix: string,
  kind: "bug" | "feature" = "bug",
): Promise<EvolutionIssue> {
  return mcApiPost<EvolutionIssue>(page, "/api/v1/evolution/issues", {
    kind,
    title: `mc-e2e-${suffix}-${Date.now()}`,
    body: "Mission Control E2E throwaway issue.",
  });
}

/** Ensure operator workspaces block bug pipelines at HITL before seeding. */
async function ensureBugApprovalRequired(page: Page): Promise<void> {
  const full = await mcApiGet<{ config?: Record<string, unknown> }>(page, "/api/v1/config/full");
  const config = full.config ?? {};
  const mySevn = (config.my_sevn as Record<string, unknown> | undefined) ?? {};
  const bugs = (mySevn.bugs as Record<string, unknown> | undefined) ?? {};
  if (bugs.require_approval === true) {
    return;
  }
  await mcApiPut(page, "/api/v1/config/full", {
    ...config,
    my_sevn: {
      ...mySevn,
      bugs: { ...bugs, require_approval: true },
    },
  });
}

async function waitForPendingApproval(
  page: Page,
  issueId: string,
): Promise<string> {
  const deadline = Date.now() + mcE2ePanelTimeout();
  while (Date.now() < deadline) {
    const pageBody = await mcApiGet<ApprovalsPage>(
      page,
      "/api/v1/evolution/approvals?pending_only=true&limit=50",
    );
    const match = (pageBody.items || []).find((row) => row.issue_id === issueId);
    if (match?.id) {
      return match.id;
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`no pending approval seeded for issue ${issueId}`);
}

/** Run a bug pipeline until HITL approval is queued (409 blocked is OK). */
export async function seedPendingApproval(
  page: Page,
  suffix: string,
): Promise<{ issueId: string; approvalId: string }> {
  await ensureBugApprovalRequired(page);
  const issue = await seedEvolutionIssue(page, suffix, "bug");
  try {
    await mcApiPost(page, `/api/v1/evolution/pipelines/${encodeURIComponent(issue.id)}/run`, {
      stage: "auto",
    });
  } catch {
    // PipelineBlockedError at awaiting_approval is the expected path.
  }
  const approvalId = await waitForPendingApproval(page, issue.id);
  return { issueId: issue.id, approvalId };
}
