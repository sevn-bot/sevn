import { test } from "node:test";

type TestFn = () => Promise<void> | void;

/**
 * Skip the test unless `SEVN_RUN_MARKED=1`.
 * The skip reason is `green after <wave>` so reconciliation can find it.
 */
export function red(wave: string): (name: string, fn: TestFn) => void {
  return (name, fn) => {
    const marked = process.env.SEVN_RUN_MARKED === "1";
    test(name, { skip: marked ? false : `green after ${wave}` }, fn);
  };
}
