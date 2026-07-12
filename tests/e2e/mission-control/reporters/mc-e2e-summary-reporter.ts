// Mission Control E2E structured run summary (`make mc-e2e-local-headed`).
//
// Enabled when `SEVN_MC_E2E_SUMMARY=1`. Writes JSON to `SEVN_MC_E2E_REPORT_PATH`
// (default `reports/mc-e2e-local-run.json`) and prints a human-readable table.

import fs from "node:fs/promises";
import path from "node:path";

import type {
  FullConfig,
  FullResult,
  Reporter,
  TestCase,
  TestResult,
} from "@playwright/test/reporter";

type McE2eTestEntry = {
  name: string;
  file: string;
  status: "passed" | "failed" | "skipped" | "timedOut" | "interrupted";
  reason: string;
  durationMs: number;
};

type McE2eRunReport = {
  runAt: string;
  mode: string;
  workspace: string;
  contractOnly: boolean;
  skipSnapshot: boolean;
  seedSkipped: boolean;
  summary: {
    passed: number;
    failed: number;
    skipped: number;
    timedOut: number;
    interrupted: number;
    total: number;
  };
  tests: McE2eTestEntry[];
};

function relSpecPath(test: TestCase): string {
  const file = test.location.file;
  const marker = `${path.sep}tests${path.sep}e2e${path.sep}mission-control${path.sep}`;
  const idx = file.indexOf(marker);
  if (idx >= 0) {
    return file.slice(idx + marker.length);
  }
  return path.basename(file);
}

function firstLine(text: string): string {
  return text.split("\n").map((line) => line.trim()).find(Boolean) || text.trim();
}

function extractFailureReason(result: TestResult): string {
  if (result.status === "passed") {
    return "";
  }
  if (result.status === "skipped") {
    return result.error?.message?.trim() || "skipped";
  }

  const parts: string[] = [];
  for (const err of result.errors) {
    const msg = err.message?.trim();
    if (msg) {
      parts.push(firstLine(msg));
    }
  }
  if (parts.length === 0 && result.error?.message) {
    parts.push(firstLine(result.error.message));
  }
  if (parts.length === 0 && result.stderr.length > 0) {
    parts.push(firstLine(result.stderr.join("\n")));
  }
  const joined = parts.join(" | ");
  if (joined.includes("console errors:")) {
    const match = joined.match(/console \([^)]+\): [^|]+/);
    if (match) {
      return match[0];
    }
  }
  if (joined.includes("api errors:")) {
    const match = joined.match(/api \([^)]+\): \d+ \S+/);
    if (match) {
      return match[0];
    }
  }
  return joined || `status=${result.status}`;
}

function summarizeCounts(entries: McE2eTestEntry[]): McE2eRunReport["summary"] {
  const summary = {
    passed: 0,
    failed: 0,
    skipped: 0,
    timedOut: 0,
    interrupted: 0,
    total: entries.length,
  };
  for (const entry of entries) {
    summary[entry.status] += 1;
  }
  return summary;
}

function printHumanSummary(report: McE2eRunReport, reportPath: string): void {
  const { summary } = report;
  const line = "─".repeat(72);
  console.log(`\n${line}`);
  console.log("Mission Control E2E — run summary");
  console.log(line);
  console.log(
    `Totals: ${summary.passed} passed, ${summary.failed} failed, ${summary.skipped} skipped`
      + (summary.timedOut ? `, ${summary.timedOut} timed out` : "")
      + (summary.interrupted ? `, ${summary.interrupted} interrupted` : "")
      + ` (${summary.total} tests)`,
  );
  console.log(`Report: ${reportPath}`);
  console.log(line);

  const failed = report.tests.filter((row) => row.status !== "passed" && row.status !== "skipped");
  if (failed.length === 0) {
    console.log("All executed tests passed.");
    console.log(`${line}\n`);
    return;
  }

  console.log("Failures:");
  for (const row of failed) {
    console.log(`  ✗ ${row.name}`);
    console.log(`    file: ${row.file}`);
    console.log(`    reason: ${row.reason}`);
  }
  console.log(`${line}\n`);
}

class McE2eSummaryReporter implements Reporter {
  private entries: McE2eTestEntry[] = [];
  private startedAt = new Date().toISOString();

  onTestEnd(test: TestCase, result: TestResult): void {
    const project = test.parent?.project()?.name;
    if (project && project !== "mission-control") {
      return;
    }

    this.entries.push({
      name: test.title,
      file: relSpecPath(test),
      status: result.status,
      reason: extractFailureReason(result),
      durationMs: result.duration,
    });
  }

  async onEnd(result: FullResult): Promise<void> {
    if (process.env.SEVN_MC_E2E_SUMMARY !== "1") {
      return;
    }

    const reportPath = path.resolve(
      process.env.SEVN_MC_E2E_REPORT_PATH || "reports/mc-e2e-local-run.json",
    );
    const mode = process.env.SEVN_MC_E2E_SHARED_SESSION === "1" ? "local-headed" : "local";
    const report: McE2eRunReport = {
      runAt: this.startedAt,
      mode,
      workspace: process.env.SEVN_MC_WORKSPACE || "infra/e2e-mission-control-workspace",
      contractOnly: process.env.SEVN_MC_E2E_DATA_PATH !== "1",
      skipSnapshot: process.env.SEVN_MC_E2E_SNAPSHOT !== "1" && process.env.SEVN_MC_E2E_LOCAL === "1",
      seedSkipped: process.env.SEVN_MC_SEED !== "1",
      summary: summarizeCounts(this.entries),
      tests: this.entries,
    };

    await fs.mkdir(path.dirname(reportPath), { recursive: true });
    await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    printHumanSummary(report, reportPath);

    if (result.status !== "passed" && report.summary.failed + report.summary.timedOut > 0) {
      // Preserve Playwright exit code; summary is additive diagnostics only.
    }
  }

  printsToStdio(): boolean {
    return true;
  }
}

export default McE2eSummaryReporter;
