export type Route = {
  /** A paired host's id for `/hosts/:hostId/bots/...`; null for the serving host. */
  hostId: string | null;
  botId: string | null;
  agentId: string | null;
};

const home: Route = { hostId: null, botId: null, agentId: null };

export function routeFromPath(path: string): Route {
  const match =
    /^(?:\/hosts\/([^/]+))?\/bots\/([^/]+)(?:\/agents\/([^/]+))?$/.exec(path);
  const bot = match?.[2];
  if (bot === undefined || bot === "") {
    return home;
  }
  const host = match?.[1];
  const agent = match?.[3];
  return {
    hostId: host === undefined ? null : decodeURIComponent(host),
    botId: decodeURIComponent(bot),
    agentId: agent === undefined ? null : decodeURIComponent(agent),
  };
}

/** A bot on a paired host (plan 0055 W6 follow-up). */
export function hostBotPath(hostId: string, botId: string): string {
  return `/hosts/${encodeURIComponent(hostId)}/bots/${encodeURIComponent(botId)}`;
}

/** A bot's chat on the serving host (`hostId` null) or on a paired host. */
export function botPath(hostId: string | null, botId: string): string {
  return hostId === null
    ? `/bots/${encodeURIComponent(botId)}`
    : hostBotPath(hostId, botId);
}

export function agentPath(botId: string, agentId: string): string {
  return `/bots/${encodeURIComponent(botId)}/agents/${encodeURIComponent(agentId)}`;
}

export function go(path: string): void {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function isBriefPath(path: string): boolean {
  return path === "/brief";
}

/** Settings → Devices on the serving host (plan 0055 D9). */
export const devicesPath = "/settings/devices";

/** Pair this browser with another host (plan 0055 D9). */
export const pairingPath = "/pairing";

/** The serving host's own fleet dashboard. */
export const fleetPath = "/fleet";

export type ShareRoute = { shareId: string; secret: string };

/** ``/share/<id>/<secret>``: a read-only page that needs no login. */
export function shareFromPath(path: string): ShareRoute | null {
  const match = /^\/share\/([A-Za-z0-9_]+)\/([A-Za-z0-9_-]+)$/.exec(path);
  const shareId = match?.[1];
  const secret = match?.[2];
  if (shareId === undefined || secret === undefined) {
    return null;
  }
  return { shareId, secret };
}
