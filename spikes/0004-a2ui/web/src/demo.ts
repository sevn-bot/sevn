import assist from "../../payloads/p5-assist.json";
import approval from "../../payloads/p4-approval.json";
import form from "../../payloads/p1-form.json";
import secret from "../../payloads/p3-secret.json";
import table from "../../payloads/p2-table-update.json";

type PayloadFile = {
  messages: Record<string, unknown>[];
  update?: Record<string, unknown>[];
};

function fileMessages(file: PayloadFile): Record<string, unknown>[] {
  return [...file.messages, ...(file.update ?? [])];
}

const payloadFiles = [form, table, secret, approval, assist] as PayloadFile[];

function surfaceId(file: PayloadFile): string {
  for (const message of file.messages) {
    const create = message.createSurface;
    if (typeof create === "object" && create !== null && !Array.isArray(create)) {
      const id = (create as { surfaceId?: unknown }).surfaceId;
      if (typeof id === "string") {
        return id;
      }
    }
  }
  return "";
}

export function demoMessages(): Record<string, unknown>[] {
  const selected =
    typeof location === "undefined" ? null : new URLSearchParams(location.search).get("payload");
  const files = selected ? payloadFiles.filter((file) => surfaceId(file) === selected) : payloadFiles;
  return files.flatMap((file) => fileMessages(file));
}
