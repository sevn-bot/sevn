import { type ChildProcess, spawn } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";

export const statePath = path.join(tmpdir(), "sevn-0001-e2e.json");

type State = {
  baseURL: string;
  token: string;
  home: string;
  pid: number;
};

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
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // The server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`sevn serve did not become healthy on ${url}`);
}

export default async function globalSetup(): Promise<void> {
  const repo = path.resolve(import.meta.dirname, "../..");
  const dist = path.join(repo, "web", "dist");
  const home = path.join(tmpdir(), `sevn-e2e-${process.pid}`);
  mkdirSync(home, { recursive: true });
  writeFileSync(
    path.join(home, "config.toml"),
    '[secrets]\nbackend = "age-file"\n',
    "utf8",
  );
  const port = await freePort();
  const child: ChildProcess = spawn(
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
    {
      cwd: repo,
      detached: true,
      stdio: "ignore",
      env: {
        ...process.env,
        SEVN_HOME: home,
        SEVN_WEB_DIST: dist,
        SEVN_SECRETS__BACKEND: "age-file",
        SEVN_DEV: "1",
        SEVN_TEST_MODEL: "echo",
        SEVN_WORKSPACES: path.join(home, "workspaces"),
      },
    },
  );
  child.unref();
  if (child.pid === undefined) {
    throw new Error("failed to start sevn serve");
  }
  try {
    await waitForHealth(port);
    const token = readFileSync(path.join(home, "run", "token"), "utf8").trim();
    const state: State = {
      baseURL: `http://127.0.0.1:${port}`,
      token,
      home,
      pid: child.pid,
    };
    writeFileSync(statePath, JSON.stringify(state), "utf8");
  } catch (error) {
    process.kill(-child.pid, "SIGTERM");
    rmSync(home, { recursive: true, force: true });
    throw error;
  }
}
