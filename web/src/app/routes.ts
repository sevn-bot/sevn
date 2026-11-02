export type Route = {
  botId: string | null;
  agentId: string | null;
};

const home: Route = { botId: null, agentId: null };

export function routeFromPath(path: string): Route {
  const match = /^\/bots\/([^/]+)(?:\/agents\/([^/]+))?$/.exec(path);
  const bot = match?.[1];
  if (bot === undefined || bot === "") {
    return home;
  }
  const agent = match?.[2];
  return {
    botId: decodeURIComponent(bot),
    agentId: agent === undefined ? null : decodeURIComponent(agent),
  };
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
