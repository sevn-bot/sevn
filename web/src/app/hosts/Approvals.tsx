import type { FleetWaiting } from "../../client/connection.ts";
import { type WaitingHost, WaitingList } from "./WaitingList.tsx";

const approvalsOnly = (item: FleetWaiting): boolean => item.kind === "approval";

/** One approvals view across hosts (plan 0055 D9): approvals only, each with its host. */
export function Approvals({
  hosts,
  onOpen,
}: {
  hosts: WaitingHost[];
  onOpen?: (hostId: string, item: FleetWaiting) => void;
}) {
  return (
    <WaitingList
      title="Approvals"
      empty="No approvals waiting"
      hosts={hosts}
      include={approvalsOnly}
      onOpen={onOpen}
    />
  );
}
