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
