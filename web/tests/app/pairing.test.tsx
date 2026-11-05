import { createElement } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { loadComponent } from "../support/components.ts";

/**
 * Plan 0055 D7, D8, D9: the pairing screen on the device.
 *
 * Pinned: `web/src/app/pairing/PairingPage.tsx` → `PairingPage({ pair })` where
 * `pair({ url, code, allowPlainWs })` resolves the saved profile (`{ host_id, name, ... }`).
 * Inputs "Host address" and "Short code", a "Pair" button, then "Paired with <name>".
 * "Scan QR code" shows only when `BarcodeDetector` exists. A `CspBlocked(origin)` failure
 * shows the `connect_src = ["<origin>"]` line; a `DirectUrlRefused` failure shows the rule
 * and an "Allow plain ws:// for this host" checkbox.
 */
const pagePath = "../../src/app/pairing/PairingPage.tsx";
const errorsPath = "../../src/client/errors.ts";

type Input = { url: string; code: string; allowPlainWs: boolean };

afterEach(async () => {
  const testing = await import("@testing-library/react");
  testing.cleanup();
  vi.unstubAllGlobals();
});

async function fill(url: string, code: string): Promise<void> {
  const testing = await import("@testing-library/react");
  testing.fireEvent.change(
    await testing.screen.findByLabelText("Host address"),
    {
      target: { value: url },
    },
  );
  testing.fireEvent.change(await testing.screen.findByLabelText("Short code"), {
    target: { value: code },
  });
  (await testing.screen.findByRole("button", { name: "Pair" })).click();
}

test("short-code entry pairs and names the host; no camera without BarcodeDetector", async () => {
  vi.stubGlobal("BarcodeDetector", undefined);
  const testing = await import("@testing-library/react");
  const calls: Input[] = [];
  const PairingPage = await loadComponent(pagePath, "PairingPage");
  testing.render(
    createElement(PairingPage, {
      pair: (input: Input) => {
        calls.push(input);
        return Promise.resolve({ host_id: "host_linux", name: "Omarchy" });
      },
    }),
  );
  expect(
    testing.screen.queryByRole("button", { name: "Scan QR code" }),
  ).toBeNull();
  await fill("wss://linux.tailnet.ts.net/ws", " k7m2-q9xr ");
  await testing.screen.findByText("Paired with Omarchy");
  expect(calls).toEqual([
    {
      url: "wss://linux.tailnet.ts.net/ws",
      code: "K7M2Q9XR",
      allowPlainWs: false,
    },
  ]);
});

test("the camera scan is offered when BarcodeDetector exists", async () => {
  vi.stubGlobal(
    "BarcodeDetector",
    class {
      detect(): Promise<unknown[]> {
        return Promise.resolve([]);
      }
    },
  );
  const testing = await import("@testing-library/react");
  const PairingPage = await loadComponent(pagePath, "PairingPage");
  testing.render(
    createElement(PairingPage, {
      pair: () => Promise.resolve({ host_id: "h", name: "h" }),
    }),
  );
  await testing.screen.findByRole("button", { name: "Scan QR code" });
  expect(testing.screen.getByLabelText("Short code")).toBeTruthy();
});

test("a dial blocked by CSP shows the exact connect_src line to add", async () => {
  const testing = await import("@testing-library/react");
  const errors = (await import(errorsPath)) as {
    CspBlocked: new (origin: string) => Error;
  };
  const PairingPage = await loadComponent(pagePath, "PairingPage");
  testing.render(
    createElement(PairingPage, {
      pair: () =>
        Promise.reject(new errors.CspBlocked("wss://linux.tailnet.ts.net")),
    }),
  );
  await fill("wss://linux.tailnet.ts.net/ws", "K7M2Q9XR");
  await testing.screen.findByText(
    'connect_src = ["wss://linux.tailnet.ts.net"]',
    { exact: false },
  );
});

test("a refused plain ws:// URL shows the rule and the owner toggle", async () => {
  const testing = await import("@testing-library/react");
  const errors = (await import(errorsPath)) as {
    DirectUrlRefused: new (url: string, reason: string) => Error;
  };
  const calls: Input[] = [];
  const PairingPage = await loadComponent(pagePath, "PairingPage");
  testing.render(
    createElement(PairingPage, {
      pair: (input: Input) => {
        calls.push(input);
        if (!input.allowPlainWs) {
          return Promise.reject(
            new errors.DirectUrlRefused(input.url, "not_private"),
          );
        }
        return Promise.resolve({ host_id: "host_lan", name: "LAN box" });
      },
    }),
  );
  await fill("ws://192.168.1.20:8787/ws", "K7M2Q9XR");
  const toggle = await testing.screen.findByLabelText(
    "Allow plain ws:// for this host",
  );
  expect(
    (await testing.screen.findAllByText(/wss:\/\//)).length,
  ).toBeGreaterThan(0);
  toggle.click();
  (await testing.screen.findByRole("button", { name: "Pair" })).click();
  await testing.screen.findByText("Paired with LAN box");
  expect(calls.map((call) => call.allowPlainWs)).toEqual([false, true]);
});
