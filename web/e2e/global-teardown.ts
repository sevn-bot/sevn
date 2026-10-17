import { readFileSync, rmSync } from "node:fs";
import { statePath } from "./global-setup.ts";

export default async function globalTeardown(): Promise<void> {
  const state = JSON.parse(readFileSync(statePath, "utf8")) as {
    pid: number;
    home: string;
  };
  try {
    process.kill(-state.pid, "SIGTERM");
  } catch {
    // The server already exited.
  }
  rmSync(state.home, { recursive: true, force: true });
  rmSync(statePath, { force: true });
}
