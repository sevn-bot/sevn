import { test as base, type TestFunction } from "vitest";

/** `test` when SEVN_RUN_MARKED=1, otherwise `test.skip`. Name suffix: ` [green after ${wave}]`. */
export function red(wave: string): (name: string, fn: TestFunction) => void {
  const test = process.env.SEVN_RUN_MARKED === "1" ? base : base.skip;
  return (name, fn) => {
    test(`${name} [green after ${wave}]`, fn);
  };
}
