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

export function demoMessages(): Record<string, unknown>[] {
  return [form, table, secret, approval, assist].flatMap((file) =>
    fileMessages(file as PayloadFile),
  );
}
