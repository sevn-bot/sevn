import { type ChildProcess, execFileSync, spawn } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { expect, test } from "@playwright/test";

/**
 * Plan 0055 W1.6: two `sevn serve` hosts, one SPA.
 *
 * Host B is reached as `host-b.sevn.test` (Chromium maps it to 127.0.0.1), so its Host
 * header is not loopback and every session must pass pairing and the D3 handshake — the
 * same shape as `tailscale serve`.
 */
const TEST_HOSTNAME = "host-b.sevn.test";
const CROCKFORD_CODE = /\b[0-9A-HJKMNP-TV-Z]{8}\b/;

test.use({
  launchOptions: {
    args: [`--host-resolver-rules=MAP *.sevn.test 127.0.0.1`],
  },
});

type Host = {
  home: string;
  port: number;
  base: string;
  token: string;
  child: ChildProcess;
};

const repo = path.resolve(import.meta.dirname, "../..");

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

function stopHost(host: Host | undefined): void {
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

function sevn(host: Host, args: string[]): string {
  return execFileSync("uv", ["run", "sevn", ...args, "--home", host.home], {
    cwd: repo,
    env: env(host.home),
    encoding: "utf8",
  });
}

function probe(
  host: Host,
  method: string,
  params: Record<string, unknown>,
): Record<string, unknown> {
  const out = sevn(host, ["probe", "call", method, JSON.stringify(params)]);
  return JSON.parse(out) as Record<string, unknown>;
}

test.describe("direct multi-host", () => {
  test.setTimeout(90_000);

  let hostA: Host | undefined;
  let hostB: Host | undefined;

  test.beforeAll(async () => {
    const portA = await freePort();
    const portB = await freePort();
    const nameB = `${TEST_HOSTNAME}:${portB}`;
    hostA = await startHost("a", portA, `connect_src = ["ws://${nameB}"]\n`);
    hostB = await startHost(
      "b",
      portB,
      `allowed_hosts = ["${nameB}"]\nallowed_origins = ["http://127.0.0.1:${portA}"]\n`,
    );
    probe(hostA, "bots.create", { name: "Alpha on A", op_id: "op_e2e_a" });
    probe(hostB, "bots.create", { name: "Beta on B", op_id: "op_e2e_b" });
  });

  test.afterAll(() => {
    stopHost(hostA);
    stopHost(hostB);
  });

  test("pair the second host from the first SPA, see both hosts' bots, revoke, see it drop", async ({
    page,
  }) => {
    if (hostA === undefined || hostB === undefined) {
      throw new Error("hosts did not start");
    }
    const minted = sevn(hostB, ["pair", "--scope", "member"]);
    const withoutUri = minted
      .split("\n")
      .filter((line) => !line.includes("sevn://"))
      .join("\n");
    const code = CROCKFORD_CODE.exec(withoutUri)?.[0];
    expect(code, minted).toBeDefined();

    await page.goto(
      `${hostA.base}/auth/login?token=${encodeURIComponent(hostA.token)}`,
    );
    await page.goto(`${hostA.base}/pairing`);
    await page
      .getByLabel("Host address")
      .fill(`ws://${TEST_HOSTNAME}:${hostB.port}/ws`);
    await page.getByLabel("Short code").fill(code ?? "");
    await page.getByRole("button", { name: "Pair" }).click();
    // A hostname over plain ws:// is refused by the client until the owner opts in (D7).
    await page.getByLabel("Allow plain ws:// for this host").check();
    await page.getByRole("button", { name: "Pair" }).click();
    await expect(page.getByText(/^Paired with /)).toBeVisible({
      timeout: 15_000,
    });

    await page.goto(`${hostA.base}/`);
    const regionA = page.getByRole("region").filter({ hasText: "Alpha on A" });
    const regionB = page.getByRole("region").filter({ hasText: "Beta on B" });
    await expect(regionA).toBeVisible({ timeout: 15_000 });
    await expect(regionB).toBeVisible({ timeout: 15_000 });
    await expect(regionB.getByRole("img", { name: "reachable" })).toBeVisible();

    const listed = probe(hostB, "devices.list", {}) as {
      devices?: { id: string; revoked_at: string | null }[];
    };
    const device = listed.devices?.find((item) => item.revoked_at === null);
    expect(device, JSON.stringify(listed)).toBeDefined();
    probe(hostB, "devices.revoke", {
      id: device?.id ?? "",
      op_id: "op_e2e_revoke",
    });
    await expect(regionB.getByRole("img", { name: "unreachable" })).toBeVisible(
      { timeout: 10_000 },
    );
    await expect(regionA.getByRole("img", { name: "reachable" })).toBeVisible();
  });
});
