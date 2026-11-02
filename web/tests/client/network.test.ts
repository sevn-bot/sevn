import { expect, test } from "vitest";

/**
 * Plan 0055 D7: the client-side private-network check, before any socket opens.
 *
 * Pinned in `web/src/client/profiles.ts`:
 * - `DEFAULT_PRIVATE_NETWORKS = ["100.64.0.0/10", "fd7a:115c:a1e0::/48"]`
 * - `checkDirectUrl(url, { private_networks?, allow_plain_ws? })`
 *   -> `{ ok: true } | { ok: false; reason: "scheme" | "hostname_over_ws" | "not_private" }`
 */
type Check = { ok: true } | { ok: false; reason: string };
type Profiles = {
  DEFAULT_PRIVATE_NETWORKS: readonly string[];
  checkDirectUrl: (
    url: string,
    options: { private_networks?: string[]; allow_plain_ws?: boolean },
  ) => Check;
};

async function loadProfiles(): Promise<Profiles> {
  const specifier = "../../src/client/profiles.ts";
  return (await import(specifier)) as Profiles;
}

type Row = {
  url: string;
  options?: { private_networks?: string[]; allow_plain_ws?: boolean };
  ok: boolean;
  reason?: string;
};

const matrix: Row[] = [
  { url: "wss://mac.tailnet.ts.net/ws", ok: true },
  { url: "wss://mac.tailnet.ts.net:8443/ws", ok: true },
  { url: "wss://203.0.113.7/ws", ok: true },
  { url: "ws://127.0.0.1:8787/ws", ok: true },
  { url: "ws://[::1]:8787/ws", ok: true },
  { url: "ws://100.64.0.1:8787/ws", ok: true },
  { url: "ws://100.101.102.103:8787/ws", ok: true },
  { url: "ws://100.127.255.254:8787/ws", ok: true },
  { url: "ws://100.63.255.255:8787/ws", ok: false, reason: "not_private" },
  { url: "ws://100.128.0.1:8787/ws", ok: false, reason: "not_private" },
  { url: "ws://[fd7a:115c:a1e0::1]:8787/ws", ok: true },
  { url: "ws://[fd7a:115c:a1e0:ab12::42]:8787/ws", ok: true },
  { url: "ws://[fd7a:115c:a1e1::1]:8787/ws", ok: false, reason: "not_private" },
  { url: "ws://192.168.1.20:8787/ws", ok: false, reason: "not_private" },
  { url: "ws://10.0.0.5:8787/ws", ok: false, reason: "not_private" },
  { url: "ws://203.0.113.7:8787/ws", ok: false, reason: "not_private" },
  {
    url: "ws://mac.tailnet.ts.net:8787/ws",
    ok: false,
    reason: "hostname_over_ws",
  },
  {
    url: "ws://100.101.102.103.nip.io:8787/ws",
    ok: false,
    reason: "hostname_over_ws",
  },
  { url: "http://100.101.102.103:8787/ws", ok: false, reason: "scheme" },
  { url: "https://mac.tailnet.ts.net/ws", ok: false, reason: "scheme" },
  { url: "not a url", ok: false, reason: "scheme" },
  // An owner-added overlay range (NetBird, ZeroTier, WireGuard).
  {
    url: "ws://10.147.17.5:8787/ws",
    options: { private_networks: ["10.147.17.0/24"] },
    ok: true,
  },
  {
    url: "ws://10.147.18.5:8787/ws",
    options: { private_networks: ["10.147.17.0/24"] },
    ok: false,
    reason: "not_private",
  },
  // `allow_plain_ws` is the owner's explicit opt-in for a LAN or a hostname.
  {
    url: "ws://192.168.1.20:8787/ws",
    options: { allow_plain_ws: true },
    ok: true,
  },
  {
    url: "ws://mac.tailnet.ts.net:8787/ws",
    options: { allow_plain_ws: true },
    ok: true,
  },
  {
    url: "http://192.168.1.20:8787/ws",
    options: { allow_plain_ws: true },
    ok: false,
    reason: "scheme",
  },
];

test("the D7 matrix: wss, loopback, tailnet v4/v6, LAN, hostnames, opt-in", async () => {
  const { checkDirectUrl } = await loadProfiles();
  for (const row of matrix) {
    const result = checkDirectUrl(row.url, row.options ?? {});
    expect({ url: row.url, ok: result.ok }).toEqual({
      url: row.url,
      ok: row.ok,
    });
    if (!row.ok && !result.ok) {
      expect({ url: row.url, reason: result.reason }).toEqual({
        url: row.url,
        reason: row.reason,
      });
    }
  }
});

test("the default private networks are the Tailscale and Headscale ranges", async () => {
  const { DEFAULT_PRIVATE_NETWORKS } = await loadProfiles();
  expect([...DEFAULT_PRIVATE_NETWORKS]).toEqual([
    "100.64.0.0/10",
    "fd7a:115c:a1e0::/48",
  ]);
});

test("ws://localhost counts as loopback; a localhost lookalike is a hostname", async () => {
  // Browsers hard-wire `localhost` to the loopback interface, so it is not a name the
  // browser resolves over the network (D7's reason to refuse ws:// hostnames).
  const { checkDirectUrl } = await loadProfiles();
  expect(checkDirectUrl("ws://localhost:8787/ws", {}).ok).toBe(true);
  const lookalike = checkDirectUrl("ws://localhost.evil.example:8787/ws", {});
  expect(lookalike).toEqual({ ok: false, reason: "hostname_over_ws" });
});

test("a profile's private_networks replaces the default list", async () => {
  // The setting defaults to the Tailscale and Headscale ranges; an owner-edited list is
  // taken as written, so an owner who wants both keeps the defaults in it.
  const { checkDirectUrl, DEFAULT_PRIVATE_NETWORKS } = await loadProfiles();
  const own = { private_networks: ["10.147.17.0/24"] };
  expect(checkDirectUrl("ws://10.147.17.5:8787/ws", own).ok).toBe(true);
  expect(checkDirectUrl("ws://100.101.102.103:8787/ws", own)).toEqual({
    ok: false,
    reason: "not_private",
  });
  const both = {
    private_networks: [...DEFAULT_PRIVATE_NETWORKS, "10.147.17.0/24"],
  };
  expect(checkDirectUrl("ws://100.101.102.103:8787/ws", both).ok).toBe(true);
  expect(checkDirectUrl("ws://10.147.17.5:8787/ws", both).ok).toBe(true);
  expect(checkDirectUrl("ws://[fd7a:115c:a1e0::1]:8787/ws", {}).ok).toBe(true);
});
