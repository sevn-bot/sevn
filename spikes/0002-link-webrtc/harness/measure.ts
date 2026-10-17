import { spawn } from "node:child_process";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
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
  await measureTurn();
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

async function measureTurn() {
  const id = process.env.CF_TURN_KEY_ID ?? "";
  const token = process.env.CF_TURN_API_TOKEN ?? "";
  if (!id || !token) {
    await skipTurn();
    return;
  }
  const servers = await mintIce(id, token);
  const udp = pickServer(servers, "udp");
  const tls = pickServer(servers, "tls443");
  if (!udp || !tls) {
    console.error("s-turn: minted server list has no udp or tls endpoint");
    process.exit(1);
  }
  const smoke = Boolean(process.env.SPIKE_RUNS) && process.env.SPIKE_RUNS !== "20";
  const udpCode = await runRelay(udp, "udp", secretList(id, token, udp));
  const tlsCode = await runRelay(tls, "tls443", secretList(id, token, tls));
  if (smoke) {
    process.exit(udpCode || tlsCode || 0);
  }
  const measured = await mergeTurn();
  if (!measured) {
    console.error("s-turn: relay measurement failed");
    process.exit(1);
  }
}

function secretList(id, token, server) {
  return [id, token, server.url, server.username, server.credential].filter(Boolean);
}

async function mintIce(id, token) {
  let response;
  try {
    response = await fetch(
      `https://rtc.live.cloudflare.com/v1/turn/keys/${encodeURIComponent(id)}/credentials/generate-ice-servers`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ttl: 86400 }),
      },
    );
  } catch {
    console.error("s-turn: credential mint failed");
    process.exit(1);
  }
  if (!response.ok) {
    await response.body?.cancel();
    console.error(`s-turn: credential mint failed status ${response.status}`);
    process.exit(1);
  }
  let body;
  try {
    body = await response.json();
  } catch {
    console.error("s-turn: credential mint returned no relay server");
    process.exit(1);
  }
  const listed = Array.isArray(body.iceServers)
    ? body.iceServers
    : body.iceServers
      ? [body.iceServers]
      : [];
  const servers = [];
  for (const server of listed) {
    const urls = Array.isArray(server.urls) ? server.urls : server.urls ? [server.urls] : [];
    for (const url of urls) {
      servers.push({
        url: String(url),
        username: String(server.username ?? ""),
        credential: String(server.credential ?? ""),
      });
    }
  }
  return servers;
}

function pickServer(servers, transport) {
  return servers.find((server) => {
    const port = portOf(server.url);
    if (transport === "udp") {
      return (
        server.url.startsWith("turn:") &&
        !server.url.startsWith("turns:") &&
        port === 3478 &&
        /transport=udp/i.test(server.url)
      );
    }
    return server.url.startsWith("turns:") && port === 443;
  });
}

function portOf(url) {
  const hostport = url.replace(/^turns?:/i, "").split("?")[0] ?? "";
  const match = hostport.match(/:(\d+)$/);
  return match ? Number(match[1]) : 0;
}

function runRelay(server, transport, secrets) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      "cargo",
      ["run", "--release", "--quiet", "--bin", "spike-measure", "--", "--scenario", "s-turn"],
      {
        cwd: spikeDir,
        env: {
          ...process.env,
          SPIKE_TURN_URL: server.url,
          SPIKE_TURN_USERNAME: server.username,
          SPIKE_TURN_CREDENTIAL: server.credential,
          SPIKE_TURN_TRANSPORT: transport,
        },
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    const scrub = (chunk) => {
      let text = chunk.toString();
      for (const secret of secrets) {
        text = text.split(secret).join("[redacted]");
      }
      text = text.replace(/\b\d{1,3}(\.\d{1,3}){3}\b/g, "[redacted]");
      text = text.replace(/turns?:[^\s"]+/gi, "[redacted]");
      process.stderr.write(text);
    };
    child.stdout.on("data", scrub);
    child.stderr.on("data", scrub);
    child.on("error", reject);
    child.on("exit", (code) => resolve(code ?? 1));
  });
}

async function mergeTurn() {
  await mkdir(resultsDir, { recursive: true });
  let measured = false;
  for (const lib of libs) {
    const transports = {};
    for (const transport of ["udp", "tls443"]) {
      const fragment = path.join(resultsDir, `s-turn-${lib}-${transport}.json`);
      try {
        transports[transport] = JSON.parse(await readFile(fragment, "utf8"));
      } catch {
        transports[transport] = {
          scenario: "s-turn",
          lib,
          transport,
          ice_transport_policy: "relay",
          ok: false,
          reason: "relay measurement failed",
        };
      }
      await rm(fragment, { force: true });
      const row = transports[transport];
      if (row.candidate_type === "relay" && row.runs === 20 && row.ok !== false) {
        measured = true;
      }
    }
    const body = {
      scenario: "s-turn",
      lib,
      ice_transport_policy: "relay",
      udp: transports.udp,
      tls443: transports.tls443,
    };
    await writeFile(path.join(resultsDir, `s-turn-${lib}.json`), `${JSON.stringify(body, null, 2)}\n`);
  }
  return measured;
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
