import { useState } from "react";
import { call, type FleetWaiting } from "../../client/connection.ts";

/** Options as one-click answers, plus a text answer. */
export function QuestionCard({ item }: { item: FleetWaiting }) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState(false);
  const [answered, setAnswered] = useState(false);

  async function send(answer: { option_id: string } | { text: string }) {
    setSending(true);
    setFailed(false);
    try {
      await call("pending.answer", { pending_id: item.id, ...answer });
      setDraft("");
      // The card stays until the next refresh; a second answer would only
      // come back as pending_resolved.
      setAnswered(true);
    } catch {
      setFailed(true);
    } finally {
      setSending(false);
    }
  }

  if (answered) {
    return (
      <div className="space-y-2">
        <p>{item.text}</p>
        <p role="status" className="text-sm text-zinc-400">
          Answered
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p>{item.text}</p>
      {item.options.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {item.options.map((option) => (
            <button
              key={option.id}
              type="button"
              disabled={sending}
              className="rounded bg-zinc-100 px-3 py-1 text-left text-sm font-medium text-zinc-950 disabled:opacity-40"
              onClick={() => {
                void send({ option_id: option.id });
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const text = draft.trim();
          if (text !== "") {
            void send({ text });
          }
        }}
      >
        <input
          aria-label={`Answer ${item.text}`}
          placeholder={
            item.options.length > 0 ? "Or type an answer" : "Type an answer"
          }
          className="min-w-0 flex-1 rounded bg-zinc-900 px-2 py-1 text-sm"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
        />
        <button
          type="submit"
          aria-label="Send answer"
          disabled={sending || draft.trim() === ""}
          className="rounded border border-zinc-700 px-3 py-1 text-sm disabled:opacity-40"
        >
          Send
        </button>
      </form>
      {failed ? (
        <p className="text-sm text-red-400">Could not send the answer</p>
      ) : null}
    </div>
  );
}
