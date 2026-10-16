import assert from "node:assert/strict";
import { test } from "node:test";

import { FILE_BYTES, fileSha256 } from "./support/blob.ts";
import { LIBS, withPeer } from "./support/session.ts";

const EXPECTED = [
  { id: 0, label: "rpc" },
  { id: 1, label: "events" },
  { id: 2, label: "files" },
];

test("rust peer and webkit open three channels", async () => {
  for (const lib of LIBS) {
    await withPeer("webkit", lib, "channels", async (page) => {
      await page.waitForFunction(
        () => {
          const spike = window.sevnSpike;
          return Boolean(spike && spike.channels && spike.channels.length === 3);
        },
        undefined,
        { timeout: 15_000 },
      );
      const channels = await page.evaluate(() => {
        const spike = window.sevnSpike;
        return (spike.channels ?? []).map((channel) => ({
          id: channel.id,
          label: channel.label,
        }));
      });
      assert.deepEqual(channels, EXPECTED, lib);
    });
  }
});

test("webkit receives 10 MB file intact", async () => {
  const expected = fileSha256();
  for (const lib of LIBS) {
    await withPeer("webkit", lib, "file", async (page) => {
      await page.waitForFunction(
        (byteCount) => {
          const spike = window.sevnSpike;
          return Boolean(
            spike &&
              spike.receivedBytes === byteCount &&
              typeof spike.receivedSha256 === "string" &&
              spike.receivedSha256.length === 64,
          );
        },
        FILE_BYTES,
        { timeout: 60_000 },
      );
      const actual = await page.evaluate(() => window.sevnSpike.receivedSha256);
      assert.equal(actual, expected, lib);
    });
  }
});
