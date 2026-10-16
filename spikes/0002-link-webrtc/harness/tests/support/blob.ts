import { createHash } from "node:crypto";

/** Bytes the rust `spike-peer --scenario file` must send, and Chrome must hash. */
export const FILE_BYTES = 10 * 1024 * 1024;

export function fileBytes(): Buffer {
  const out = Buffer.allocUnsafe(FILE_BYTES);
  for (let i = 0; i < FILE_BYTES; i += 1) {
    out[i] = i % 251;
  }
  return out;
}

export function fileSha256(): string {
  return createHash("sha256").update(fileBytes()).digest("hex");
}
