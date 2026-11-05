/** Two `sevn serve` hosts for multi-host e2e specs (plan 0055). Host B is `host-b.sevn.test`. */
import { type ChildProcess, execFileSync, spawn } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
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

type ReservedPort = { port: number; release: () => Promise<void> };

function reservePort(): Promise<ReservedPort> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address === null || typeof address === "string") {
        reject(new Error("no port"));
        return;
      }
      const { port } = address;
      resolve({
        port,
        release: () => new Promise<void>((done) => server.close(() => done())),
      });
    });
  });
}

/** A successful token login proves that the responder belongs to this test home. */
async function waitForHost(
  child: ChildProcess,
  home: string,
  port: number,
): Promise<string> {
  const base = `http://127.0.0.1:${port}`;
  const tokenFile = path.join(home, "run", "token");
  for (let attempt = 0; attempt < 300; attempt += 1) {
    if (
      child.exitCode !== null ||
      child.signalCode !== null ||
      child.pid === undefined
    ) {
      throw new Error(`sevn serve exited before becoming ready on ${base}`);
    }
    if (existsSync(tokenFile)) {
      const token = readFileSync(tokenFile, "utf8").trim();
      try {
        const response = await fetch(
          `${base}/auth/login?token=${encodeURIComponent(token)}`,
          {
            redirect: "manual",
            signal: AbortSignal.timeout(500),
          },
        );
        if (
          response.status === 303 &&
          response.headers.get("set-cookie")?.includes("sevn_session=")
        ) {
          // The process may have failed to bind while another listener answered the request.
          if (child.exitCode === null && child.signalCode === null) {
            return token;
          }
        }
      } catch {
        // Still starting; an unrelated listener cannot authenticate this home's token.
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`sevn serve did not authenticate this home on ${base}`);
}

function env(home: string): NodeJS.ProcessEnv {
  const clean = { ...process.env };
  delete clean.SEVN_ALLOWED_HOSTS;
  return {
    ...clean,
    SEVN_HOME: home,
    SEVN_WEB_DIST: path.join(repo, "web", "dist"),
    SEVN_SECRETS__BACKEND: "age-file",
    // The echo test model needs both flags (sevn.runtime.models.echo_enabled).
    SEVN_DEV: "1",
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
  child.on("error", () => {
    // waitForHost observes the missing pid and reports startup failure.
  });
  child.unref();
  const host = {
    home,
    port,
    base: `http://127.0.0.1:${port}`,
    token: "",
    child,
  };
  try {
    host.token = await waitForHost(child, home, port);
    return host;
  } catch (error) {
    stopHost(host);
    throw error;
  }
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
  let failure: unknown;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const reservedA = await reservePort();
    const reservedB = await reservePort();
    let a: Host | undefined;
    let b: Host | undefined;
    try {
      // Keep B reserved while A starts, so the two hosts cannot pick the same port.
      const nameB = `${TEST_HOSTNAME}:${reservedB.port}`;
      await reservedA.release();
      a = await startHost(
        `${tag}-${attempt}-a`,
        reservedA.port,
        `connect_src = ["ws://${nameB}"]\n`,
      );
      await reservedB.release();
      b = await startHost(
        `${tag}-${attempt}-b`,
        reservedB.port,
        `allowed_hosts = ["${nameB}"]\nallowed_origins = ["http://127.0.0.1:${reservedA.port}"]\n`,
      );
      return { a, b };
    } catch (error) {
      failure = error;
      stopHost(a);
      stopHost(b);
    } finally {
      await reservedA.release();
      await reservedB.release();
    }
  }
  throw failure;
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
