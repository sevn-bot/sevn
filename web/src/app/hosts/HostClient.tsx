import type { ReactNode } from "react";
import type { HostClient } from "../../client/connection.ts";
import { HostClientContext, useHostClient } from "../../client/hooks.ts";

export type { HostClient } from "../../client/connection.ts";
export { useHostClient };

/**
 * Point a subtree (a chat and its children) at one host (plan 0055 W6 follow-up). Without a
 * provider, components talk to the host that serves the page.
 */
export function HostClientProvider({
  client,
  children,
}: {
  client: HostClient;
  children?: ReactNode;
}) {
  return (
    <HostClientContext.Provider value={client}>
      {children}
    </HostClientContext.Provider>
  );
}
