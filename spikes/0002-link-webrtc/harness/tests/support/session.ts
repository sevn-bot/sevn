import { type ChildProcess, spawn } from "node:child_process";
import { createInterface } from "node:readline";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** `spikes/0002-link-webrtc`. */
export const spikeDir = path.resolve(here, "../../..");

export const harnessDir = path.resolve(here, "../..");

export const LIBS = ["webrtcrs", "str0m"] as const;

export type BrowserName = "chromium" | "webkit";
export type Scenario = "channels" | "file" | "video";

type SpikePage = {
  goto(url: string, opts: { waitUntil: "domcontentloaded"; timeout: number }): Promise<unknown>;
  waitForFunction(
    pageFunction: (arg: number) => boolean,
    arg: number | undefined,
    opts: { timeout: number },
  ): Promise<unknown>;
  evaluate<T, A = undefined>(
    pageFunction: (arg: A) => T | Promise<T>,
    arg?: A,
  ): Promise<T>;
};

type Launched = {
  newPage(): Promise<SpikePage>;
  close(): Promise<void>;
};

type PlaywrightModule = {
  chromium: { launch(opts: { headless: boolean }): Promise<Launched> };
  webkit: { launch(opts: { headless: boolean }): Promise<Launched> };
};

/**
 * Starts `spike-peer`, opens the READY url in Playwright, then tears both down.
 *
 * The binary is `cargo run --quiet --bin spike-peer -- --lib <lib> --scenario <scenario>`
 * with cwd `spikes/0002-link-webrtc`. It prints `READY <url>` and serves the harness
 * page. The page sets `window.sevnSpike`:
 * - `channels`: `{id, label}[]` — ids 0/1/2, labels rpc/events/files
 * - `receivedBytes` and `receivedSha256` (lowercase hex) after the 10 MiB
 *   file whose byte i is `i % 251`
 * - a `<video>` element for scenario `video` (1280×720 H.264)
 */
export async function withPeer(
  browserName: BrowserName,
  lib: string,
  scenario: Scenario,
  run: (page: SpikePage) => Promise<void>,
): Promise<void> {
  const started = await startPeer(lib, scenario);
  let browser: Launched | undefined;
  try {
    const pw = (await import("playwright")) as PlaywrightModule;
    const launcher = browserName === "chromium" ? pw.chromium : pw.webkit;
    browser = await launcher.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto(started.url, { waitUntil: "domcontentloaded", timeout: 15_000 });
    await run(page);
  } finally {
    await browser?.close().catch(() => undefined);
    if (!started.proc.killed) {
      started.proc.kill("SIGTERM");
    }
  }
}

async function startPeer(
  lib: string,
  scenario: Scenario,
): Promise<{ url: string; proc: ChildProcess }> {
  const proc = spawn(
    "cargo",
    ["run", "--quiet", "--bin", "spike-peer", "--", "--lib", lib, "--scenario", scenario],
    { cwd: spikeDir, stdio: ["ignore", "pipe", "pipe"] },
  );
  let stderr = "";
  proc.stderr?.on("data", (chunk: Buffer) => {
    stderr = `${stderr}${chunk.toString("utf8")}`.slice(-4096);
  });

  const stdout = proc.stdout;
  if (!stdout) {
    proc.kill("SIGTERM");
    throw new Error("spike-peer has no stdout");
  }
  const url = await new Promise<string>((resolve, reject) => {
    const lines = createInterface({ input: stdout });
    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      lines.close();
      fn();
    };
    const timer = setTimeout(() => {
      finish(() => {
        proc.kill("SIGTERM");
        reject(new Error(`spike-peer did not print READY (${lib} ${scenario})\n${stderr}`));
      });
    }, 120_000);
    proc.on("error", (err) => {
      finish(() => reject(err));
    });
    proc.on("exit", (code) => {
      finish(() => reject(new Error(`spike-peer exited ${code} before READY\n${stderr}`)));
    });
    lines.on("line", (line) => {
      if (line.startsWith("READY ")) {
        finish(() => resolve(line.slice("READY ".length).trim()));
      }
    });
  });
  return { url, proc };
}
