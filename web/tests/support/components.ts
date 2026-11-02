/** Load a named React component by path at test time, so a missing module fails one test only. */
export type Component = (props: Record<string, unknown>) => unknown;

export async function loadComponent(
  specifier: string,
  exportName: string,
): Promise<Component> {
  const loaded = (await import(specifier)) as Record<string, unknown>;
  const component = loaded[exportName];
  if (typeof component !== "function") {
    throw new Error(`expected named export ${exportName} from ${specifier}`);
  }
  return component as Component;
}
