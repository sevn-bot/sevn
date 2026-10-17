const KINDS = new Set([
  "hello",
  "challenge",
  "auth",
  "welcome",
  "req",
  "res",
  "evt",
  "tick",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortValue);
  }
  if (isRecord(value)) {
    const entries = Object.entries(value).sort(([left], [right]) =>
      left < right ? -1 : left > right ? 1 : 0,
    );
    return Object.fromEntries(
      entries.map(([key, item]) => [key, sortValue(item)]),
    );
  }
  return value;
}

/** Parse a text frame. The returned value round-trips through {@link dump}. */
export function parse(text: string): unknown {
  const value: unknown = JSON.parse(text);
  if (!isRecord(value) || typeof value.t !== "string" || !KINDS.has(value.t)) {
    throw new Error("invalid frame");
  }
  return value;
}

/** Canonical JSON: sorted keys, no insignificant whitespace. */
export function dump(frame: unknown): string {
  return JSON.stringify(sortValue(frame));
}
