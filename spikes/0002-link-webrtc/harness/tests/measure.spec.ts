import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFile, rm } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";

import { harnessDir, LIBS, spikeDir } from "./support/session.ts";

const FIELDS = [
  "connect_p50_ms",
  "connect_p95_ms",
  "mbps_10mb",
  "ice_restart_ms",
  "first_frame_ms",
  "rss_mb",
  "cpu_pct",
] as const;

test("s-lan results have twenty runs and the D5 fields", async () => {
  const resultsDir = path.join(spikeDir, "results");
  for (const lib of LIBS) {
    await rm(path.join(resultsDir, `s-lan-${lib}.json`), { force: true });
  }

  await runMeasure();

  for (const lib of LIBS) {
    const file = path.join(resultsDir, `s-lan-${lib}.json`);
    const text = await readFile(file, "utf8");
    assert.doesNotMatch(text, /\b(?:\d{1,3}\.){3}\d{1,3}\b/, `${lib} has an IP address`);
    assert.doesNotMatch(text, /turn:/i, `${lib} has a TURN url`);
    assert.doesNotMatch(text, /credential/i, `${lib} has a credential`);

    const json = JSON.parse(text) as Record<string, unknown>;
    assert.equal(json.scenario, "s-lan", lib);
    assert.equal(json.lib, lib);
    assert.equal(json.runs, 20, lib);
    for (const field of FIELDS) {
      assert.equal(typeof json[field], "number", `${lib} ${field}`);
      assert.ok(Number.isFinite(json[field]), `${lib} ${field}`);
    }
    const p50 = json.connect_p50_ms;
    const p95 = json.connect_p95_ms;
    if (typeof p50 === "number" && typeof p95 === "number") {
      assert.ok(p50 <= p95, `${lib} p50 ${p50} > p95 ${p95}`);
    }
  }
});

function runMeasure(): Promise<void> {
  const script = path.join(harnessDir, "measure.ts");
  const child = spawn(process.execPath, [script, "--scenario", "s-lan"], {
    cwd: harnessDir,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stderr = "";
  child.stderr?.on("data", (chunk: Buffer) => {
    stderr = `${stderr}${chunk.toString("utf8")}`.slice(-4096);
  });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error("measure.ts timed out"));
    }, 15 * 60 * 1000);
    child.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`measure.ts exited ${code}\n${stderr}`));
    });
  });
}
