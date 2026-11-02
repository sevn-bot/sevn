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

/**
 * Plan 0055 W6 follow-up (WV.1): chat with a bot on each host from one window.
 * Gated: green after W6 follow-up (per-host chat); runs only with SEVN_RUN_MARKED=1.
 */
const RUN_MARKED = process.env.SEVN_RUN_MARKED === "1";

test.use({ launchOptions: { args: RESOLVER_ARGS } });

test.describe("per-host chat [green after W6 follow-up: per-host chat]", () => {
  test.skip(
    !RUN_MARKED,
    "green after W6 follow-up: per-host chat (set SEVN_RUN_MARKED=1)",
  );
  test.setTimeout(90_000);

  let hostA: Host | undefined;
  let hostB: Host | undefined;

  test.beforeAll(async () => {
    const started = await startTwoHosts("chat");
    hostA = started.a;
    hostB = started.b;
    probe(hostA, "bots.create", { name: "Alpha on A", op_id: "op_chat_a" });
    probe(hostB, "bots.create", { name: "Beta on B", op_id: "op_chat_b" });
  });

  test.afterAll(() => {
    stopHost(hostA);
    stopHost(hostB);
  });

  test("open a bot on the second host, chat with it, then chat on the first", async ({
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
    await page.getByLabel("Short code").fill(code);
    await page.getByRole("button", { name: "Pair" }).click();
    await page.getByLabel("Allow plain ws:// for this host").check();
    await page.getByRole("button", { name: "Pair" }).click();
    await expect(page.getByText(/^Paired with /)).toBeVisible({
      timeout: 15_000,
    });

    await page.goto(`${hostA.base}/`);
    const regionB = page.getByRole("region").filter({ hasText: "Beta on B" });
    await regionB
      .getByRole("button", { name: "Beta on B" })
      .click({ timeout: 15_000 });
    await expect(page).toHaveURL(/\/hosts\/[^/]+\/bots\/[^/]+$/);
    const message = page.getByRole("textbox", { name: "Message" });
    await message.fill("hi from A to B");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(
      page.getByText("echo: hi from A to B", { exact: true }),
    ).toBeVisible({ timeout: 15_000 });

    // The message landed on host B, not on A.
    const botsB = probe(hostB, "bots.list", {}) as {
      bots: { id: string; name: string }[];
    };
    const beta = botsB.bots.find((bot) => bot.name === "Beta on B");
    const onB = probe(hostB, "messages.list", { bot_id: beta?.id ?? "" });
    expect(JSON.stringify(onB)).toContain("hi from A to B");
    const botsA = probe(hostA, "bots.list", {}) as {
      bots: { id: string; name: string }[];
    };
    const alpha = botsA.bots.find((bot) => bot.name === "Alpha on A");
    const onA = probe(hostA, "messages.list", { bot_id: alpha?.id ?? "" });
    expect(JSON.stringify(onA)).not.toContain("hi from A to B");

    // The serving host's own bot still chats on its own connection.
    const regionA = page.getByRole("region").filter({ hasText: "Alpha on A" });
    await regionA.getByRole("button", { name: "Alpha on A" }).click();
    await message.fill("hi on A");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("echo: hi on A", { exact: true })).toBeVisible({
      timeout: 15_000,
    });
  });
});
