// Playwright config — wired per specs/25-cicd-full.md §3.2 + §10.4
// and specs/22-onboarding.md §9.
//
// Three journey families share one chromium runtime:
//
//   * "webchat"         — tests against the Phase-3 gateway shell (`/webapp/`,
//                         `/login`, `/ws/webchat`). The webServer boots the gateway
//                         with the seeded workspace in `infra/e2e-workspace/`.
//
//   * "onboarding"      — tests against `sevn onboard --web`. The webServer boots
//                         the onboarding wizard with a pinned `SEVN_ONBOARD_TOKEN`
//                         so each spec hits `/?onboard_token=…` deterministically.
//
//   * "mission-control" — tests against Mission Control (`/mission/`). The webServer
//                         boots an isolated gateway on `:13004` (or `SEVN_MC_PORT`)
//                         with the fixture workspace unless `SEVN_MC_WORKSPACE` /
//                         `.env.mc-e2e` override (`make mc-e2e-local`). Remote-only
//                         mode uses `SEVN_MC_BASE_URL` (no local webServer).
//
// External-target mode (`SEVN_E2E_BASE_URL`) still bypasses local webServers
// for the webchat project only — onboarding journeys always boot locally.

import fs from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

/** Load a simple KEY=VALUE env file without overriding existing vars. */
function loadEnvFile(filePath: string): void {
  if (!fs.existsSync(filePath)) return;
  const text = fs.readFileSync(filePath, "utf8");
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    if (key in process.env) continue;
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    process.env[key] = value;
  }
}

// Optional operator workspace overrides — never loaded for default `make mc-e2e`.
if (process.env.SEVN_MC_E2E_LOCAL === "1" || process.env.SEVN_MC_LOAD_DOTENV === "1") {
  loadEnvFile(path.resolve(".env.mc-e2e"));
}

function expandTilde(value: string): string {
  if (value.startsWith("~/")) {
    return path.join(process.env.HOME || "", value.slice(2));
  }
  return value;
}

/** Derive operator home when workspace is `<SEVN_HOME>/workspace`. */
function deriveMcHomeFromWorkspace(workspace: string): string {
  const resolved = path.resolve(workspace);
  if (path.basename(resolved) === "workspace") {
    return path.dirname(resolved);
  }
  return resolved;
}

const isCI = !!process.env.CI;
const e2eWorkspace = path.resolve("infra/e2e-workspace");
const e2eWebchatHome = path.resolve("infra/e2e-webchat-home");
const onboardingWorkspace = path.resolve("infra/e2e-onboarding-workspace");
const onboardingHome = path.resolve("infra/e2e-onboarding-home");
const defaultMcWorkspace = path.resolve("infra/e2e-mission-control-workspace");
const defaultMcHome = path.resolve("infra/e2e-mission-control-home");
const defaultMcPort = 13004;
const webchatPort = 13002;
const onboardingPort = 13003;

const mcWorkspaceOverride = process.env.SEVN_MC_WORKSPACE;
const mcWorkspace = mcWorkspaceOverride
  ? path.resolve(expandTilde(mcWorkspaceOverride))
  : defaultMcWorkspace;
const mcHome = process.env.SEVN_MC_HOME
  ? path.resolve(expandTilde(process.env.SEVN_MC_HOME))
  : mcWorkspaceOverride
    ? deriveMcHomeFromWorkspace(mcWorkspace)
    : defaultMcHome;
const mcPort = process.env.SEVN_MC_PORT
  ? Number.parseInt(process.env.SEVN_MC_PORT, 10)
  : defaultMcPort;

const webchatBase = `http://127.0.0.1:${webchatPort}`;
const onboardingBase = `http://127.0.0.1:${onboardingPort}`;
const mcBase = process.env.SEVN_MC_BASE_URL || `http://127.0.0.1:${mcPort}`;
const externalBase = process.env.SEVN_E2E_BASE_URL;
const mcExternalBase = process.env.SEVN_MC_BASE_URL;
const mcOnlyProject = process.env.SEVN_MC_E2E_PROJECT === "1";
const mcSecretsMasterKey =
  process.env.SEVN_SECRETS_MASTER_KEY || "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const repoRoot = path.resolve(".");
/** Operator workspaces live outside the checkout — `uv run` needs the repo root as cwd. */
const mcWebServerCwd = mcWorkspaceOverride ? repoRoot : mcWorkspace;

function mcProjectTimeoutMs(): number {
  const env = process.env.SEVN_MC_E2E_TIMEOUT_MS?.trim();
  if (env) {
    const parsed = Number.parseInt(env, 10);
    if (!Number.isNaN(parsed) && parsed > 0) {
      return parsed * 2;
    }
  }
  return process.env.SEVN_MC_E2E_LOCAL === "1" ? 120_000 : 90_000;
}

const reporters: [string, object?][] = [
  ["list"],
  ["html", { open: "never", outputFolder: "playwright-report" }],
  ["json", { outputFile: "playwright-report/results.json" }],
  ["junit", { outputFile: "playwright-report/junit.xml" }],
];
if (process.env.SEVN_MC_E2E_SUMMARY === "1") {
  reporters.push(["./tests/e2e/mission-control/reporters/mc-e2e-summary-reporter.ts"]);
}

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: 1,

  reporter: reporters,

  outputDir: "test-results",

  use: {
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  webServer: [
    ...(externalBase || mcOnlyProject
      ? []
      : [
          {
            command: `uv run uvicorn sevn.gateway.http_server:create_app --factory --host 127.0.0.1 --port ${webchatPort}`,
            cwd: e2eWorkspace,
            env: {
              ...process.env,
              SEVN_HOME: e2eWebchatHome,
              SEVN_WORKSPACE: e2eWorkspace,
              SEVN_E2E_ECHO_TURN: "1",
            },
            url: `${webchatBase}/health`,
            reuseExistingServer: !isCI,
            timeout: 120_000,
          },
        ]),
    ...(mcOnlyProject
      ? []
      : [
          {
            command: `uv run sevn onboard --web --host 127.0.0.1 --port ${onboardingPort} --no-open`,
            cwd: onboardingWorkspace,
            env: {
              ...process.env,
              SEVN_HOME: onboardingHome,
              SEVN_WORKSPACE: onboardingWorkspace,
              SEVN_ONBOARD_TOKEN: "playwright-onboard-token",
              SEVN_ONBOARD_SKIP_INSTALL_DISCOVERY: "1",
            },
            url: `${onboardingBase}/healthz`,
            reuseExistingServer: !isCI,
            timeout: 120_000,
          },
        ]),
    ...(mcExternalBase
      ? []
      : [
          {
            command: `uv run uvicorn sevn.gateway.http_server:create_app --factory --host 127.0.0.1 --port ${mcPort}`,
            cwd: mcWebServerCwd,
            env: {
              ...process.env,
              SEVN_HOME: mcHome,
              SEVN_WORKSPACE: mcWorkspace,
              SEVN_SECRETS_MASTER_KEY: mcSecretsMasterKey,
            },
            url: `http://127.0.0.1:${mcPort}/health`,
            reuseExistingServer: !isCI,
            timeout: 120_000,
          },
        ]),
  ],

  projects: [
    {
      name: "webchat",
      testIgnore: "**/onboarding*.spec.ts",
      use: {
        ...devices["Desktop Chrome"],
        baseURL: externalBase || webchatBase,
      },
    },
    {
      name: "onboarding",
      testMatch: "**/onboarding*.spec.ts",
      use: {
        ...devices["Desktop Chrome"],
        baseURL: onboardingBase,
      },
    },
    {
      name: "mission-control",
      testDir: "./tests/e2e/mission-control",
      testMatch: /.*\.spec\.ts/,
      fullyParallel: false,
      timeout: mcProjectTimeoutMs(),
      use: {
        ...devices["Desktop Chrome"],
        baseURL: mcBase,
      },
    },
  ],
});
