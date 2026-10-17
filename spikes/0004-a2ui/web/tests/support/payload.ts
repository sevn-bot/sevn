import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

export type JsonObject = { [key: string]: Json };

export type Payload = {
  messages: Json[];
  update?: Json[];
};

export function isRecord(value: Json | undefined): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function payloadPath(id: string): string {
  const here = dirname(fileURLToPath(import.meta.url));
  return resolve(here, "..", "..", "..", "payloads", `${id}.json`);
}

export function readPayload(id: string): Payload {
  const path = payloadPath(id);
  if (!existsSync(path)) {
    throw new Error(`missing payload ${path}`);
  }
  const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (!isUnknownRecord(parsed) || !Array.isArray(parsed.messages) || parsed.messages.length === 0) {
    throw new Error(`${id} must be an object with a non-empty messages array`);
  }
  return {
    messages: parsed.messages as Json[],
    update: Array.isArray(parsed.update) ? (parsed.update as Json[]) : undefined,
  };
}

function isUnknownRecord(value: unknown): value is { messages?: unknown; update?: unknown } {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function asMessages(values: readonly Json[]): JsonObject[] {
  return values.filter(isRecord);
}

export function messagesOf(payload: Payload, includeUpdate: boolean): JsonObject[] {
  const extra = includeUpdate && payload.update ? payload.update : [];
  return asMessages([...payload.messages, ...extra]);
}

export function components(messages: readonly JsonObject[]): JsonObject[] {
  const found: JsonObject[] = [];
  for (const message of messages) {
    const update = message.updateComponents;
    if (!isRecord(update) || !Array.isArray(update.components)) {
      continue;
    }
    found.push(...update.components.filter(isRecord));
  }
  return found;
}

export function surfaceId(messages: readonly JsonObject[]): string {
  for (const message of messages) {
    const create = message.createSurface;
    if (isRecord(create) && typeof create.surfaceId === "string" && create.surfaceId) {
      return create.surfaceId;
    }
  }
  throw new Error("createSurface.surfaceId is missing");
}

export function firstChoiceValue(messages: readonly JsonObject[]): string {
  for (const component of components(messages)) {
    if (component.component !== "ChoicePicker" && component.component !== "Select") {
      continue;
    }
    if (!Array.isArray(component.options) || !isRecord(component.options[0])) {
      continue;
    }
    const value = component.options[0].value;
    if (typeof value === "string" && value) {
      return value;
    }
  }
  throw new Error("p1 choice must include a string option value");
}

export function secretField(messages: readonly JsonObject[]): {
  name: string;
  label: string;
  help: string;
  link: string;
} {
  for (const component of components(messages)) {
    if (component.component !== "sevn.SecretField") {
      continue;
    }
    const { name, label, help, link } = component;
    if (
      typeof name === "string" &&
      name &&
      typeof label === "string" &&
      label &&
      typeof help === "string" &&
      help &&
      typeof link === "string" &&
      link
    ) {
      return { name, label, help, link };
    }
  }
  throw new Error("sevn.SecretField needs string name, label, help, and link");
}

function decode(segment: string): string {
  return segment.replace(/~1/g, "/").replace(/~0/g, "~");
}

export function setPointer(root: JsonObject, pointer: string, value: Json): JsonObject {
  if (pointer === "" || pointer === "/") {
    if (!isRecord(value)) {
      throw new Error("data model root must be an object");
    }
    return value;
  }
  const parts = pointer.split("/").slice(1).map(decode);
  const clone: JsonObject = { ...root };
  let cursor = clone;
  for (let index = 0; index < parts.length - 1; index += 1) {
    const part = parts[index] ?? "";
    const next = cursor[part];
    const child: JsonObject = isRecord(next) ? { ...next } : {};
    cursor[part] = child;
    cursor = child;
  }
  cursor[parts[parts.length - 1] ?? ""] = value;
  return clone;
}

export function applyData(messages: readonly JsonObject[]): JsonObject {
  let model: JsonObject = {};
  for (const message of messages) {
    const update = message.updateDataModel;
    if (!isRecord(update)) {
      continue;
    }
    const path = typeof update.path === "string" ? update.path : "/";
    model = setPointer(model, path, update.value ?? null);
  }
  return model;
}

export function listLengths(node: Json, path = ""): Map<string, number> {
  const found = new Map<string, number>();
  if (Array.isArray(node)) {
    found.set(path || "/", node.length);
    for (const [index, item] of node.entries()) {
      for (const [key, length] of listLengths(item, `${path}/${index}`)) {
        found.set(key, length);
      }
    }
  } else if (isRecord(node)) {
    for (const [key, value] of Object.entries(node)) {
      for (const [child, length] of listLengths(value, `${path}/${key}`)) {
        found.set(child, length);
      }
    }
  }
  return found;
}

export function leaves(node: Json, path = ""): Map<string, string> {
  const found = new Map<string, string>();
  if (Array.isArray(node)) {
    for (const [index, item] of node.entries()) {
      for (const [key, value] of leaves(item, `${path}/${index}`)) {
        found.set(key, value);
      }
    }
  } else if (isRecord(node)) {
    for (const [key, value] of Object.entries(node)) {
      for (const [child, leaf] of leaves(value, `${path}/${key}`)) {
        found.set(child, leaf);
      }
    }
  } else if (typeof node === "string") {
    found.set(path, node);
  } else if (typeof node === "number") {
    found.set(path, String(node));
  }
  return found;
}

export function grownListPaths(before: JsonObject, after: JsonObject): string[] {
  const beforeLengths = listLengths(before);
  const grown: string[] = [];
  for (const [path, length] of listLengths(after)) {
    const previous = beforeLengths.get(path) ?? 0;
    if (previous >= 1 && length >= previous + 1) {
      grown.push(path);
    }
  }
  return grown;
}

export function changedLeaves(
  before: Json,
  after: Json,
): { path: string; previous: string; next: string }[] {
  const afterLeaves = leaves(after);
  const changes: { path: string; previous: string; next: string }[] = [];
  for (const [path, previous] of leaves(before)) {
    const next = afterLeaves.get(path);
    if (next !== undefined && next !== previous) {
      changes.push({ path, previous, next });
    }
  }
  return changes;
}
