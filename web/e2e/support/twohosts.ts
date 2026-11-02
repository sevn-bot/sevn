/** Two `sevn serve` hosts for multi-host e2e specs (plan 0055). Host B is `host-b.sevn.test`. */
import { type ChildProcess, execFileSync, spawn } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";

export const TEST_HOSTNAME = "host-b.sevn.test";
export const RESOLVER_ARGS = [
  `--host-resolver-rules=MAP *.sevn.test 127.0.0.1`,
];
const CROCKFORD_CODE = /\b[0-9A-HJKMNP-TV-Z]{8}\b/;

export type Host = {
  home: string;
  port: number;
  base: string;
  token: string;
  child: ChildProcess;
};

const repo = path.resolve(import.meta.dirname, "../../..");

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address === null || typeof address === "string") {
        reject(new Error("no port"));
        return;
      }
      const { port } = address;
      server.close(() => resolve(port));
    });
  });
}

async function waitForHealth(port: number): Promise<void> {
  const url = `http://127.0.0.1:${port}/health`;
  for (let attempt = 0; attempt < 300; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // Still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`sevn serve did not become healthy on ${url}`);
}

function env(home: string): NodeJS.ProcessEnv {
  const clean = { ...process.env };
  delete clean.SEVN_DEV;
  delete clean.SEVN_ALLOWED_HOSTS;
  return {
    ...clean,
    SEVN_HOME: home,
    SEVN_WEB_DIST: path.join(repo, "web", "dist"),
    SEVN_SECRETS__BACKEND: "age-file",
    SEVN_TEST_MODEL: "echo",
    SEVN_WORKSPACES: path.join(home, "workspaces"),
  };
}

async function startHost(
  name: string,
  port: number,
  http: string,
): Promise<Host> {
  const home = path.join(tmpdir(), `sevn-0055-${name}-${process.pid}`);
  rmSync(home, { recursive: true, force: true });
  mkdirSync(home, { recursive: true });
  writeFileSync(
    path.join(home, "config.toml"),
    `[secrets]\nbackend = "age-file"\n\n[http]\nport = ${port}\n${http}`,
    "utf8",
  );
  const child = spawn(
    "uv",
    [
      "run",
      "sevn",
      "serve",
      "--home",
      home,
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    { cwd: repo, detached: true, stdio: "ignore", env: env(home) },
  );
  child.unref();
  await waitForHealth(port);
  const token = readFileSync(path.join(home, "run", "token"), "utf8").trim();
  return { home, port, base: `http://127.0.0.1:${port}`, token, child };
}

export function stopHost(host: Host | undefined): void {
  if (host === undefined) {
    return;
  }
  try {
    if (host.child.pid !== undefined) {
      process.kill(-host.child.pid, "SIGTERM");
    }
  } catch {
    // Already gone.
  }
  rmSync(host.home, { recursive: true, force: true });
}

export function sevn(host: Host, args: string[]): string {
  return execFileSync("uv", ["run", "sevn", ...args, "--home", host.home], {
    cwd: repo,
    env: env(host.home),
    encoding: "utf8",
  });
}

export function probe(
  host: Host,
  method: string,
  params: Record<string, unknown>,
): Record<string, unknown> {
  const out = sevn(host, ["probe", "call", method, JSON.stringify(params)]);
  return JSON.parse(out) as Record<string, unknown>;
}

/** A tests the SPA on A, which may dial B as `ws://host-b.sevn.test:<port>`. */
export async function startTwoHosts(
  tag: string,
): Promise<{ a: Host; b: Host }> {
  const portA = await freePort();
  const portB = await freePort();
  const nameB = `${TEST_HOSTNAME}:${portB}`;
  const a = await startHost(
    `${tag}-a`,
    portA,
    `connect_src = ["ws://${nameB}"]\n`,
  );
  const b = await startHost(
    `${tag}-b`,
    portB,
    `allowed_hosts = ["${nameB}"]\nallowed_origins = ["http://127.0.0.1:${portA}"]\n`,
  );
  return { a, b };
}

/** Mint a member ticket on `host` with `sevn pair` and return its short code. */
export function shortCode(host: Host): string {
  const minted = sevn(host, ["pair", "--scope", "member"]);
  const withoutUri = minted
    .split("\n")
    .filter((line) => !line.includes("sevn://"))
    .join("\n");
  const code = CROCKFORD_CODE.exec(withoutUri)?.[0];
  if (code === undefined) {
    throw new Error(`no short code in:\n${minted}`);
  }
  return code;
}
