import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const harnessDir = path.dirname(fileURLToPath(import.meta.url));
const spikeDir = path.resolve(harnessDir, "..");
const resultsDir = path.join(spikeDir, "results");
const libs = ["webrtcrs", "str0m"];

const scenarioFlag = process.argv.indexOf("--scenario");
const scenario = scenarioFlag === -1 ? "s-lan" : process.argv[scenarioFlag + 1];

if (scenario === "s-lan") {
  await runCargo(["--scenario", "s-lan"]);
} else if (scenario === "s-turn") {
  await skipTurn();
} else if (scenario === "s-ios") {
  await skipIos();
} else {
  console.error(`measure: unknown scenario ${scenario}`);
  process.exit(2);
}

function runCargo(args) {
  return new Promise((resolve, reject) => {
    const child = spawn("cargo", ["run", "--release", "--quiet", "--bin", "spike-measure", "--", ...args], {
      cwd: spikeDir,
      stdio: "inherit",
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`spike-measure exited ${code}`));
    });
  });
}

async function skipTurn() {
  const id = process.env.CF_TURN_KEY_ID;
  const token = process.env.CF_TURN_API_TOKEN;
  if (id && token) {
    console.error("s-turn: credentials are set; this spike has no measured relay run");
    process.exit(1);
  }
  await mkdir(resultsDir, { recursive: true });
  for (const lib of libs) {
    const body = {
      scenario: "s-turn",
      lib,
      skipped: true,
      reason: "no live gate",
      detail: "CF_TURN_KEY_ID and CF_TURN_API_TOKEN are unset",
    };
    await writeFile(path.join(resultsDir, `s-turn-${lib}.json`), `${JSON.stringify(body, null, 2)}\n`);
  }
  console.error("s-turn skipped: no live gate");
}

async function skipIos() {
  await mkdir(resultsDir, { recursive: true });
  for (const lib of libs) {
    const body = {
      scenario: "s-ios",
      lib,
      skipped: true,
      reason: "no live gate",
      detail: "no operator iPhone confirmed",
    };
    await writeFile(path.join(resultsDir, `s-ios-${lib}.json`), `${JSON.stringify(body, null, 2)}\n`);
  }
  console.error("s-ios skipped: no live gate");
}
