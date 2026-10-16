import { expectTypeOf } from "vitest";
import { call } from "../../src/client/index.ts";

expectTypeOf(call)
  .parameter(0)
  .extract<"system.ping">()
  .toEqualTypeOf<"system.ping">();

expectTypeOf(call("system.ping", { op_id: "op_1", note: "hi" })).toEqualTypeOf<
  Promise<{ seq: number }>
>();
