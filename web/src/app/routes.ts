export function botIdFromPath(path: string): string | null {
  const match = /^\/bots\/([^/]+)$/.exec(path);
  const id = match?.[1];
  if (id === undefined || id === "") {
    return null;
  }
  return decodeURIComponent(id);
}

export function go(path: string): void {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
