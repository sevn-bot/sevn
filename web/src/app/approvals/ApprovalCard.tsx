import { call } from "../../client/index.ts";

export function ApprovalCard({
  pendingId,
  kind,
  name,
  args,
}: {
  pendingId: string;
  kind: string;
  name: string;
  args: Record<string, unknown>;
}) {
  function answer(decision: "approve" | "deny"): void {
    void call("pending.answer", {
      pending_id: pendingId,
      answer: decision,
    }).catch(() => undefined);
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded border border-zinc-800 px-3 py-2">
      <p className="text-sm">{kind}</p>
      <p className="text-sm">{name}</p>
      <p className="text-sm">{JSON.stringify(args)}</p>
      <button
        type="button"
        className="rounded bg-zinc-100 px-3 py-1 text-sm font-medium text-zinc-950"
        onClick={() => {
          answer("approve");
        }}
      >
        Approve
      </button>
      <button
        type="button"
        className="rounded border border-zinc-700 px-3 py-1 text-sm"
        onClick={() => {
          answer("deny");
        }}
      >
        Deny
      </button>
    </div>
  );
}
