import { expect, test } from "@playwright/test";
import {
  type Host,
  probe,
  RESOLVER_ARGS,
  shortCode,
  startTwoHosts,
  stopHost,
  TEST_HOSTNAME,
} from "./support/twohosts.ts";

test.use({ launchOptions: { args: RESOLVER_ARGS } });

test.describe("direct multi-host", () => {
  test.setTimeout(90_000);

  let hostA: Host | undefined;
  let hostB: Host | undefined;

  test.beforeAll(async () => {
    const hosts = await startTwoHosts("pair-revoke");
    hostA = hosts.a;
    hostB = hosts.b;
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
    const code = shortCode(hostB);

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

  test("IndexedDB preserves conflicting profiles and replaces an obsolete origin after re-pairing", async ({
    page,
  }) => {
    if (hostA === undefined || hostB === undefined) {
      throw new Error("hosts did not start");
    }
    const hostId = String(probe(hostB, "system.info", {}).host_id);
    const url = `ws://${TEST_HOSTNAME}:${hostB.port}/ws`;
    await page.goto(
      `${hostA.base}/auth/login?token=${encodeURIComponent(hostA.token)}`,
    );
    await page.evaluate(
      async ({ hostId, url }) => {
        const db = await new Promise<IDBDatabase>((resolve, reject) => {
          const request = indexedDB.open("sevn", 1);
          request.onupgradeneeded = () =>
            request.result.createObjectStore("profiles", {
              keyPath: "host_id",
            });
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => reject(request.error);
        });
        const device = (await crypto.subtle.generateKey(
          { name: "Ed25519" },
          false,
          ["sign", "verify"],
        )) as CryptoKeyPair;
        const common = {
          name: "Saved profile",
          host_pubkey: "invalid-fixture-key",
          host_pubkey_fp: "fixture-fingerprint",
          transport: "direct",
          allow_plain_ws: true,
          device_id: "dev_fixture",
          device_key: device.privateKey,
          scope: "member",
        };
        await new Promise<void>((resolve, reject) => {
          const transaction = db.transaction("profiles", "readwrite");
          const store = transaction.objectStore("profiles");
          store.put({ ...common, host_id: "host_obsolete", direct_url: url });
          store.put({
            ...common,
            host_id: hostId,
            direct_url: "wss://unrelated.example/ws",
          });
          transaction.oncomplete = () => resolve();
          transaction.onerror = () => reject(transaction.error);
        });
        db.close();
      },
      { hostId, url },
    );
    await page.goto(`${hostA.base}/pairing`);
    await page.getByLabel("Host address").fill(url);
    await page.getByLabel("Short code").fill(shortCode(hostB));
    await page.getByRole("button", { name: "Pair" }).click();
    await page.getByLabel("Allow plain ws:// for this host").check();
    await page.getByRole("button", { name: "Pair" }).click();
    await expect(
      page.getByText(/Host identity conflicts with an existing profile/),
    ).toBeVisible();
    const inspect = async (removeCollision: boolean) =>
      page.evaluate(
        async ({ hostId, removeCollision }) => {
          const db = await new Promise<IDBDatabase>((resolve, reject) => {
            const request = indexedDB.open("sevn", 1);
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });
          const rows = await new Promise<
            { host_id: string; direct_url: string }[]
          >((resolve, reject) => {
            const transaction = db.transaction("profiles", "readwrite");
            const store = transaction.objectStore("profiles");
            const request = store.getAll();
            if (removeCollision) {
              store.delete(hostId);
            }
            transaction.oncomplete = () => resolve(request.result);
            transaction.onerror = () => reject(transaction.error);
          });
          db.close();
          return rows.map(({ host_id, direct_url }) => ({
            host_id,
            direct_url,
          }));
        },
        { hostId, removeCollision },
      );
    expect(await inspect(true)).toEqual(
      expect.arrayContaining([
        { host_id: "host_obsolete", direct_url: url },
        { host_id: hostId, direct_url: "wss://unrelated.example/ws" },
      ]),
    );
    // A refused pairing spends its ticket; a fresh ticket now replaces the obsolete identity.
    await page.getByLabel("Short code").fill(shortCode(hostB));
    await page.getByRole("button", { name: "Pair" }).click();
    await expect(page.getByText(/^Paired with /)).toBeVisible();
    expect(await inspect(false)).toEqual([
      { host_id: hostId, direct_url: url },
    ]);
  });
});
