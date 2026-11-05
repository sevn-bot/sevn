import { expect, test } from "vitest";
import {
  b64u,
  fromHex,
  hex,
  importSeed,
  loadVectors,
  unb64u,
} from "../support/direct.ts";

/**
 * Plan 0055 D3: the web signer passes `contracts/vectors/handshake_ws.json`.
 *
 * Pinned `web/src/client/keys.ts` (wire forms are base64url strings without padding):
 * - `challengeMessage(nonce, origin): Promise<Uint8Array>`
 * - `authMessage(nonce, origin, hostFp): Promise<Uint8Array>`
 * - `signAuth(deviceKey: CryptoKey, nonce, origin, hostFp): Promise<string>`
 * - `verifyChallenge(hostPubkey, nonce, origin, hostSig): Promise<boolean>`
 * - `fingerprint(pubkey): Promise<string>`
 */
type Keys = {
  challengeMessage: (nonce: string, origin: string) => Promise<Uint8Array>;
  authMessage: (
    nonce: string,
    origin: string,
    hostFp: string,
  ) => Promise<Uint8Array>;
  signAuth: (
    deviceKey: CryptoKey,
    nonce: string,
    origin: string,
    hostFp: string,
  ) => Promise<string>;
  verifyChallenge: (
    hostPubkey: string,
    nonce: string,
    origin: string,
    hostSig: string,
  ) => Promise<boolean>;
  fingerprint: (pubkey: string) => Promise<string>;
};

async function loadKeys(): Promise<Keys> {
  const specifier = "../../src/client/keys.ts";
  return (await import(specifier)) as Keys;
}

const vectors = loadVectors();

test("challenge and auth messages match the vector bytes", async () => {
  const keys = await loadKeys();
  for (const vector of vectors.cases) {
    expect(hex(await keys.challengeMessage(vector.nonce, vector.origin))).toBe(
      vector.challenge_message_hex,
    );
    expect(
      hex(
        await keys.authMessage(
          vector.nonce,
          vector.origin,
          vectors.host.pubkey_fp,
        ),
      ),
    ).toBe(vector.auth_message_hex);
  }
});

test("the device signature matches the vectors byte for byte", async () => {
  const keys = await loadKeys();
  const device = await importSeed(
    vectors.device.seed_hex,
    vectors.device.pubkey,
  );
  expect(device.extractable).toBe(false);
  for (const vector of vectors.cases) {
    expect(
      await keys.signAuth(
        device,
        vector.nonce,
        vector.origin,
        vectors.host.pubkey_fp,
      ),
    ).toBe(vector.device_sig);
  }
});

test("vector host signatures verify; a changed origin or nonce does not", async () => {
  const keys = await loadKeys();
  for (const vector of vectors.cases) {
    const host = vectors.host.pubkey;
    expect(
      await keys.verifyChallenge(
        host,
        vector.nonce,
        vector.origin,
        vector.host_sig,
      ),
    ).toBe(true);
    expect(
      await keys.verifyChallenge(
        host,
        vector.nonce,
        "wss://evil.example",
        vector.host_sig,
      ),
    ).toBe(false);
    const nonce = unb64u(vector.nonce);
    nonce[0] = (nonce[0] ?? 0) ^ 1;
    expect(
      await keys.verifyChallenge(
        host,
        b64u(nonce),
        vector.origin,
        vector.host_sig,
      ),
    ).toBe(false);
  }
});

test("a signature from another host key does not verify", async () => {
  const keys = await loadKeys();
  const vector = vectors.cases[0];
  if (vector === undefined) {
    throw new Error("vectors file has no cases");
  }
  const other = b64u(fromHex("11".repeat(32)));
  expect(
    await keys.verifyChallenge(
      other,
      vector.nonce,
      vector.origin,
      vector.host_sig,
    ),
  ).toBe(false);
  expect(
    await keys.verifyChallenge(
      vectors.host.pubkey,
      vector.nonce,
      vector.origin,
      "not-a-signature",
    ),
  ).toBe(false);
});

test("the host fingerprint matches the vectors", async () => {
  const keys = await loadKeys();
  expect(await keys.fingerprint(vectors.host.pubkey)).toBe(
    vectors.host.pubkey_fp,
  );
});

test("the test reference reproduces the vectors (guards the helpers)", async () => {
  const { authBytes, challengeBytes } = await import("../support/direct.ts");
  const device = await importSeed(
    vectors.device.seed_hex,
    vectors.device.pubkey,
  );
  for (const vector of vectors.cases) {
    const nonce = unb64u(vector.nonce);
    expect(hex(await challengeBytes(nonce, vector.origin))).toBe(
      vector.challenge_message_hex,
    );
    const auth = await authBytes(nonce, vector.origin, vectors.host.pubkey_fp);
    expect(hex(auth)).toBe(vector.auth_message_hex);
    const sig = await crypto.subtle.sign({ name: "Ed25519" }, device, auth);
    expect(b64u(new Uint8Array(sig))).toBe(vector.device_sig);
  }
});
