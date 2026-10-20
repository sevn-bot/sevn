import { useEffect, useState } from "react";
import { useCall } from "../../client/hooks.ts";
import { call } from "../../client/index.ts";

type AccessName = "workspace" | "full" | "isolated";
type NetworkFlag = "on" | "off";

const levels: readonly AccessName[] = ["workspace", "full", "isolated"];
const networks: readonly NetworkFlag[] = ["off", "on"];

export function SandboxSettings({ botId }: { botId: string }) {
  const bot = useCall("bots.get", { bot_id: botId });
  if (bot.data === undefined) {
    return null;
  }
  return (
    <SandboxForm
      botId={botId}
      access={isAccess(bot.data.access) ? bot.data.access : "workspace"}
      network={bot.data.network === "on" ? "on" : "off"}
      onSaved={() => {
        void bot.refetch();
      }}
    />
  );
}

function SandboxForm({
  botId,
  access,
  network,
  onSaved,
}: {
  botId: string;
  access: AccessName;
  network: NetworkFlag;
  onSaved: () => void;
}) {
  const [level, setLevel] = useState(access);
  const [net, setNet] = useState(network);

  useEffect(() => {
    setLevel(access);
  }, [access]);

  useEffect(() => {
    setNet(network);
  }, [network]);

  function onLevel(next: string): void {
    if (!isAccess(next) || next === level) {
      return;
    }
    setLevel(next);
    void call("bots.update", { bot_id: botId, access: next })
      .then(onSaved)
      .catch(() => undefined);
  }

  function onNetwork(next: string): void {
    if (!isNetwork(next) || next === net) {
      return;
    }
    setNet(next);
    void call("bots.update", { bot_id: botId, network: next })
      .then(onSaved)
      .catch(() => undefined);
  }

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-medium">Sandbox</h2>
      <label className="block text-sm">
        Level
        <select
          className="mt-1 block rounded bg-zinc-900 px-2 py-1"
          value={level}
          onChange={(event) => {
            onLevel(event.target.value);
          }}
        >
          {levels.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-sm">
        Network
        <select
          className="mt-1 block rounded bg-zinc-900 px-2 py-1"
          value={net}
          onChange={(event) => {
            onNetwork(event.target.value);
          }}
        >
          {networks.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function isAccess(value: unknown): value is AccessName {
  return value === "workspace" || value === "full" || value === "isolated";
}

function isNetwork(value: unknown): value is NetworkFlag {
  return value === "on" || value === "off";
}
