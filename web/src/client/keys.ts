/**
 * Device keys and the direct-transport handshake bytes (plan 0055 D3, spec D30).
 *
 * `challengeMessage = "sevn-v1|chal|ws|" ‖ nonce ‖ SHA-256(origin)` is signed by the host;
 * `authMessage = "sevn-v1|auth|ws|" ‖ nonce ‖ SHA-256(origin) ‖ host_pubkey_fp` is signed by
 * the device. Nonces, public keys and signatures travel as base64url without padding. The
 * Python reference is `sevn.identity.handshake`; `contracts/vectors/handshake_ws.json` pins
 * the bytes.
 *
 * A device private key is a non-extractable WebCrypto key: it signs in place and never leaves
 * the browser's key store.
 */

const ED25519 = { name: "Ed25519" } as const;
const NONCE_BYTES = 32;
const PUBKEY_BYTES = 32;
const SIGNATURE_BYTES = 64;
const FINGERPRINT_BYTES = 16;
const CHALLENGE_PREFIX = "sevn-v1|chal|ws|";
const AUTH_PREFIX = "sevn-v1|auth|ws|";
const B64URL = /^[A-Za-z0-9_-]*$/;

const encoder = new TextEncoder();

/** Base64url without padding. */
export function toBase64Url(bytes: Uint8Array): string {
  let text = "";
  for (const byte of bytes) {
    text += String.fromCharCode(byte);
  }
  return btoa(text)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

/** Strict base64url (no padding) decode; throws on any other input. */
export function fromBase64Url(text: string): Uint8Array<ArrayBuffer> {
  if (!B64URL.test(text) || text.length % 4 === 1) {
    throw new Error("invalid base64url");
  }
  const padded = text.replaceAll("-", "+").replaceAll("_", "/");
  const raw = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const out = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) {
    out[index] = raw.charCodeAt(index);
  }
  return out;
}

function concat(...parts: Uint8Array[]): Uint8Array<ArrayBuffer> {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

async function sha256(bytes: Uint8Array<ArrayBuffer>): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
}

function decodeNonce(nonce: string): Uint8Array<ArrayBuffer> {
  const bytes = fromBase64Url(nonce);
  if (bytes.length !== NONCE_BYTES) {
    throw new Error("nonce must be 32 bytes");
  }
  return bytes;
}

/** A new device key pair for one host: Ed25519, the private half not extractable. */
export async function generateDeviceKey(): Promise<CryptoKeyPair> {
  const pair = await crypto.subtle.generateKey(ED25519, false, [
    "sign",
    "verify",
  ]);
  if (!("privateKey" in pair)) {
    throw new Error("Ed25519 key generation returned a single key");
  }
  return pair;
}

/** The raw public key of a device key pair, as base64url (`device_pubkey_ed25519`). */
export async function exportPublicKey(publicKey: CryptoKey): Promise<string> {
  return toBase64Url(
    new Uint8Array(await crypto.subtle.exportKey("raw", publicKey)),
  );
}

/** The bytes the host signs: `"sevn-v1|chal|ws|" ‖ nonce ‖ SHA-256(origin)`. */
export async function challengeMessage(
  nonce: string,
  origin: string,
): Promise<Uint8Array<ArrayBuffer>> {
  return concat(
    encoder.encode(CHALLENGE_PREFIX),
    decodeNonce(nonce),
    await sha256(encoder.encode(origin)),
  );
}

/** The bytes the device signs: `"sevn-v1|auth|ws|" ‖ nonce ‖ SHA-256(origin) ‖ host_fp`. */
export async function authMessage(
  nonce: string,
  origin: string,
  hostFp: string,
): Promise<Uint8Array<ArrayBuffer>> {
  return concat(
    encoder.encode(AUTH_PREFIX),
    decodeNonce(nonce),
    await sha256(encoder.encode(origin)),
    encoder.encode(hostFp),
  );
}

/** `device_sig` for an `auth` frame, signed in place by the non-extractable device key. */
export async function signAuth(
  deviceKey: CryptoKey,
  nonce: string,
  origin: string,
  hostFp: string,
): Promise<string> {
  const message = await authMessage(nonce, origin, hostFp);
  return toBase64Url(
    new Uint8Array(await crypto.subtle.sign(ED25519, deviceKey, message)),
  );
}

/**
 * True only when `hostSig` is the pinned host key's signature over this nonce and origin.
 * Anything malformed (key, nonce or signature) is false, never an exception.
 */
export async function verifyChallenge(
  hostPubkey: string,
  nonce: string,
  origin: string,
  hostSig: string,
): Promise<boolean> {
  try {
    const raw = fromBase64Url(hostPubkey);
    const signature = fromBase64Url(hostSig);
    if (raw.length !== PUBKEY_BYTES || signature.length !== SIGNATURE_BYTES) {
      return false;
    }
    const key = await crypto.subtle.importKey("raw", raw, ED25519, false, [
      "verify",
    ]);
    return await crypto.subtle.verify(
      ED25519,
      key,
      signature,
      await challengeMessage(nonce, origin),
    );
  } catch {
    return false;
  }
}

/** `host_pubkey_fp`: base64url of the first 16 bytes of SHA-256(raw public key). */
export async function fingerprint(pubkey: string): Promise<string> {
  const digest = await sha256(fromBase64Url(pubkey));
  return toBase64Url(digest.slice(0, FINGERPRINT_BYTES));
}
