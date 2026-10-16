import { readFileSync } from "node:fs";
import path from "node:path";
import { expect } from "vitest";
import { red } from "../support/red.ts";

const test = red("W6");

type Frame = { t: string } & Record<string, unknown>;

function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortValue);
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(
      ([left], [right]) => (left < right ? -1 : left > right ? 1 : 0),
    );
    return Object.fromEntries(
      entries.map(([key, item]) => [key, sortValue(item)]),
    );
  }
  return value;
}

function canonical(frame: Frame): string {
  return JSON.stringify(sortValue(frame));
}

function listFrames(document: unknown): Frame[] {
  const values = Array.isArray(document)
    ? document
    : Object.values(document as object);
  const frames: Frame[] = [];
  for (const value of values) {
    if (Array.isArray(value)) {
      frames.push(
        ...value.filter(
          (item): item is Frame => typeof item === "object" && item !== null,
        ),
      );
    } else if (typeof value === "object" && value !== null && "t" in value) {
      frames.push(value as Frame);
    }
  }
  return frames;
}

test("every vector in contracts/vectors/frames.json parses and re-serializes identically", async () => {
  const specifier = "../../src/client/index.ts";
  const client = (await import(specifier)) as {
    parse: (text: string) => unknown;
    dump: (frame: unknown) => string;
  };
  const file = path.resolve(
    import.meta.dirname,
    "../../../contracts/vectors/frames.json",
  );
  const frames = listFrames(JSON.parse(readFileSync(file, "utf8")));
  expect(frames.length).toBeGreaterThan(0);
  expect(frames.some((frame) => frame.t === "challenge")).toBe(true);
  const auth = frames.filter((frame) => frame.t === "auth");
  expect(auth.some((frame) => "token" in frame)).toBe(true);
  expect(auth.some((frame) => "device_sig" in frame)).toBe(true);
  for (const frame of frames) {
    const text = canonical(frame);
    expect(client.dump(client.parse(text))).toBe(text);
  }
});
