import { createElement } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { loadComponent } from "../support/components.ts";

/**
 * Plan 0055 D7, D8: a scanned QR that needs the plain ws:// opt-in is retried with the
 * scanned ticket and key, not the empty short-code field.
 */
vi.mock("../../src/app/pairing/QrScanner.tsx", () => ({
  scannerAvailable: () => true,
  QrScanner: ({ onLink }: { onLink: (link: unknown) => void }) =>
    createElement(
      "button",
      {
        type: "button",
        onClick: () => {
          onLink({
            host_id: "host_lan",
            ticket: "scanned-full-ticket",
            host_pubkey_fp: "scanned-fp",
            direct_url: "ws://192.168.1.20:8787/ws",
          });
        },
      },
      "Fake scan",
    ),
}));

const pagePath = "../../src/app/pairing/PairingPage.tsx";
const errorsPath = "../../src/client/errors.ts";

type Input = {
  url: string;
  code: string;
  allowPlainWs: boolean;
  expectedFp?: string;
  expectedHostId?: string;
};

afterEach(async () => {
  const testing = await import("@testing-library/react");
  testing.cleanup();
});

async function scanThenOptIn(calls: Input[]): Promise<void> {
  const testing = await import("@testing-library/react");
  const errors = (await import(errorsPath)) as {
    DirectUrlRefused: new (url: string, reason: string) => Error;
  };
  const PairingPage = await loadComponent(pagePath, "PairingPage");
  testing.render(
    createElement(PairingPage, {
      pair: (input: Input) => {
        calls.push(input);
        return input.allowPlainWs
          ? Promise.resolve({ host_id: "host_lan", name: "LAN box" })
          : Promise.reject(
              new errors.DirectUrlRefused(input.url, "not_private"),
            );
      },
    }),
  );
  (await testing.screen.findByRole("button", { name: "Scan QR code" })).click();
  (await testing.screen.findByRole("button", { name: "Fake scan" })).click();
  (
    await testing.screen.findByLabelText("Allow plain ws:// for this host")
  ).click();
}

test("a retry after a refused scan keeps the scanned ticket and key", async () => {
  const testing = await import("@testing-library/react");
  const calls: Input[] = [];
  await scanThenOptIn(calls);
  (await testing.screen.findByRole("button", { name: "Pair" })).click();
  await testing.screen.findByText("Paired with LAN box");
  expect(calls.at(-1)?.code).toBe("scanned-full-ticket");
  expect(calls.at(-1)?.expectedFp).toBe("scanned-fp");
  expect(calls.at(-1)?.expectedHostId).toBe("host_lan");
});

test("typing a short code replaces the scanned ticket", async () => {
  const testing = await import("@testing-library/react");
  const calls: Input[] = [];
  await scanThenOptIn(calls);
  testing.fireEvent.change(testing.screen.getByLabelText("Short code"), {
    target: { value: "K7M2-Q9XR" },
  });
  (await testing.screen.findByRole("button", { name: "Pair" })).click();
  await testing.screen.findByText("Paired with LAN box");
  expect(calls.at(-1)?.code).toBe("K7M2Q9XR");
  expect(calls.at(-1)?.expectedFp).toBeUndefined();
});

test("successful pairing clears scanned identity, ticket, address and plain-ws consent", async () => {
  const testing = await import("@testing-library/react");
  const calls: Input[] = [];
  await scanThenOptIn(calls);
  testing.screen.getByRole("button", { name: "Pair" }).click();
  await testing.screen.findByText("Paired with LAN box");
  expect(
    (testing.screen.getByLabelText("Host address") as HTMLInputElement).value,
  ).toBe("");
  expect(
    (testing.screen.getByLabelText("Short code") as HTMLInputElement).value,
  ).toBe("");
  testing.fireEvent.change(testing.screen.getByLabelText("Host address"), {
    target: { value: "ws://192.168.1.21:8787/ws" },
  });
  testing.fireEvent.change(testing.screen.getByLabelText("Short code"), {
    target: { value: "ABCD2345" },
  });
  testing.screen.getByRole("button", { name: "Pair" }).click();
  await testing.screen.findByLabelText("Allow plain ws:// for this host");
  expect(calls.at(-1)).toMatchObject({ code: "ABCD2345", allowPlainWs: false });
  expect(calls.at(-1)?.expectedFp).toBeUndefined();
  expect(calls.at(-1)?.expectedHostId).toBeUndefined();
});
