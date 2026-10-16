import assert from "node:assert/strict";
import { test } from "node:test";

import { LIBS, withPeer } from "./support/session.ts";

test("chrome renders first frame", async () => {
  for (const lib of LIBS) {
    await withPeer("chromium", lib, "video", async (page) => {
      const size = await page.evaluate(() => {
        return new Promise((resolve, reject) => {
          const video = document.querySelector("video");
          if (!video || video.tagName !== "VIDEO") {
            reject(new Error("no video element"));
            return;
          }
          const timer = setTimeout(() => reject(new Error("first frame timeout")), 3000);
          video.requestVideoFrameCallback((_now, metadata) => {
            clearTimeout(timer);
            resolve({ width: metadata.width, height: metadata.height });
          });
        });
      });
      assert.equal(size.width, 1280, lib);
      assert.equal(size.height, 720, lib);
    });
  }
});
