import type { FleetWaiting } from "../../client/connection.ts";
import { type WaitingHost, WaitingList } from "./WaitingList.tsx";

export type { WaitingHost } from "./WaitingList.tsx";

const everything = (): boolean => true;

/** One inbox across hosts (plan 0055 D9): every waiting item with its host label. */
export function Inbox({
  hosts,
  onOpen,
}: {
  hosts: WaitingHost[];
  onOpen?: (hostId: string, item: FleetWaiting) => void;
}) {
  return (
    <WaitingList
      title="Inbox"
      empty="Nothing waiting on you"
      hosts={hosts}
      include={everything}
      onOpen={onOpen}
    />
  );
}
