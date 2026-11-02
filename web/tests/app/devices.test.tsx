import { createElement } from "react";
import { expect } from "vitest";
import { requestParams, startHarness } from "../chat/host.ts";
import { loadComponent } from "../support/components.ts";
import { red } from "../support/red.ts";

/**
 * Plan 0055 D9: Settings → Devices on the host itself.
 *
 * Pinned components (both use the host's connection through `call`):
 * - `web/src/app/devices/PairingCard.tsx` → `PairingCard`: a "Scope" select
 *   (owner / member / read_only, default member), a "Start pairing" button, then a QR image
 *   named "Pairing QR code", the short code (`data-testid="pairing-code"`, grouping hyphens
 *   allowed) and an "Expires in m:ss" countdown that turns into "Expired".
 * - `web/src/app/devices/DevicesList.tsx` → `DevicesList`: one list item per device with its
 *   name, platform and scope; live devices have a "Revoke" button, revoked ones say "revoked".
 */
const w6 = red("W6");
const cardPath = "../../src/app/devices/PairingCard.tsx";
const listPath = "../../src/app/devices/DevicesList.tsx";

function started(expiresInMs: number): Record<string, unknown> {
  return {
    ticket: "t-0123456789abcdef0123456789abcdef",
    qr_uri: "sevn://pair?h=host_mac&k=fp&t=t-0123456789abcdef0123456789abcdef",
    short_code: "K7M2Q9XR",
    expires_at: new Date(Date.now() + expiresInMs).toISOString(),
  };
}

w6(
  "the pairing card starts a ticket with the chosen scope and shows QR, code and countdown",
  async () => {
    const harness = await startHarness({ "pairing.start": started(600_000) });
    const testing = await import("@testing-library/react");
    try {
      const PairingCard = await loadComponent(cardPath, "PairingCard");
      testing.render(createElement(PairingCard));
      const scope = (await testing.screen.findByLabelText(
        "Scope",
      )) as HTMLSelectElement;
      expect(scope.value).toBe("member");
      expect(
        Array.from(scope.options, (option) => option.value).sort(),
      ).toEqual(["member", "owner", "read_only"]);
      testing.fireEvent.change(scope, { target: { value: "owner" } });
      (
        await testing.screen.findByRole("button", { name: "Start pairing" })
      ).click();
      await testing.waitFor(() => {
        expect(requestParams(harness.requests, "pairing.start").length).toBe(1);
      });
      expect(requestParams(harness.requests, "pairing.start")[0]?.scope).toBe(
        "owner",
      );
      await testing.screen.findByRole("img", { name: "Pairing QR code" });
      const code = await testing.screen.findByTestId("pairing-code");
      expect(code.textContent?.replaceAll("-", "").replaceAll(" ", "")).toBe(
        "K7M2Q9XR",
      );
      await testing.screen.findByText(/^Expires in (10:00|9:5\d)$/);
    } finally {
      harness.stop();
      testing.cleanup();
    }
  },
);

w6("an expired ticket says so", async () => {
  const harness = await startHarness({ "pairing.start": started(-1000) });
  const testing = await import("@testing-library/react");
  try {
    const PairingCard = await loadComponent(cardPath, "PairingCard");
    testing.render(createElement(PairingCard));
    (
      await testing.screen.findByRole("button", { name: "Start pairing" })
    ).click();
    await testing.screen.findByText("Expired");
    expect(requestParams(harness.requests, "pairing.start")[0]?.scope).toBe(
      "member",
    );
  } finally {
    harness.stop();
    testing.cleanup();
  }
});

w6("the devices list shows each device and revokes a live one", async () => {
  const now = new Date().toISOString();
  const harness = await startHarness({
    "devices.list": {
      devices: [
        {
          id: "dev_phone",
          name: "Phone",
          platform: "ios",
          scope: "member",
          created_at: now,
          last_seen: now,
          revoked_at: null,
        },
        {
          id: "dev_old",
          name: "Old laptop",
          platform: "web",
          scope: "owner",
          created_at: now,
          last_seen: null,
          revoked_at: now,
        },
      ],
    },
    "devices.revoke": {
      id: "dev_phone",
      name: "Phone",
      platform: "ios",
      scope: "member",
      created_at: now,
      last_seen: now,
      revoked_at: now,
    },
  });
  const testing = await import("@testing-library/react");
  try {
    const DevicesList = await loadComponent(listPath, "DevicesList");
    testing.render(createElement(DevicesList));
    const phone = (await testing.screen.findByText("Phone")).closest("li");
    const old = (await testing.screen.findByText("Old laptop")).closest("li");
    expect(phone?.textContent).toContain("ios");
    expect(phone?.textContent).toContain("member");
    expect(old?.textContent).toContain("revoked");
    expect(
      testing.within(old as HTMLElement).queryByRole("button", {
        name: "Revoke",
      }),
    ).toBeNull();
    testing
      .within(phone as HTMLElement)
      .getByRole("button", { name: "Revoke" })
      .click();
    await testing.waitFor(() => {
      expect(requestParams(harness.requests, "devices.revoke")[0]?.id).toBe(
        "dev_phone",
      );
    });
  } finally {
    harness.stop();
    testing.cleanup();
  }
});
