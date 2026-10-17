import { useEffect, useState } from "react";
import { useCall } from "../../client/hooks.ts";
import { call } from "../../client/index.ts";

export function ModelPicker({
  botId,
  model,
}: {
  botId: string;
  model: string;
}) {
  const models = useCall("models.list", {});
  const listed = models.data?.models ?? [];
  const [chosen, setChosen] = useState(model);

  useEffect(() => {
    setChosen(model);
  }, [model]);

  if (listed.length === 0 && chosen === "") {
    return null;
  }

  function onChange(next: string): void {
    setChosen(next);
    if (next === "") {
      return;
    }
    void call("bots.update", { bot_id: botId, model: next }).catch(
      () => undefined,
    );
  }

  return (
    <label className="block text-sm">
      Model
      <select
        className="mt-1 block rounded bg-zinc-900 px-2 py-1"
        value={chosen}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      >
        {chosen === "" ? <option value="">Select a model</option> : null}
        {chosen !== "" && !listed.some((item) => item.id === chosen) ? (
          <option value={chosen}>{chosen}</option>
        ) : null}
        {listed.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
    </label>
  );
}
