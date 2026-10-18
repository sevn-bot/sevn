import { methods } from "../contracts/methods.ts";
import { IncompatibleHost, ProtocolError, Unauthorized } from "./errors.ts";

const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 10_000;

export type MethodName = keyof typeof methods;

type RuntimeName = "pydantic_ai" | "claude";
type AccessName = "workspace" | "full" | "isolated";
type ApprovalPolicy = "ask" | "auto" | "allow_all";
type AgentStatus = "running" | "waiting" | "idle" | "done" | "archived";

type Bot = {
  id: string;
  name: string;
  title: string;
  scope: string;
  instructions: string;
  avatar: string;
  runtime: RuntimeName;
  model: string;
  effort: string | null;
  access: AccessName;
  approval_policy: ApprovalPolicy;
  workspace_path: string;
  folder_id: string | null;
  paused: boolean;
  can_create_bots: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
};

type ModelInfo = {
  id: string;
  provider: string;
  name: string;
};

type Agent = {
  id: string;
  bot_id: string;
  thread_id: string;
  title: string;
  summary: string;
  status: AgentStatus;
  runtime: RuntimeName;
  runtime_session_ref: string | null;
  origin_job_id: string | null;
  isolation: string;
  created_at: string;
  last_activity_at: string;
};

type ChatMessage = {
  id: string;
  thread_id: string;
  turn_id: string;
  agent_id: string;
  role: string;
  author: string;
  parts: Record<string, string>[];
  created_at: string;
};

type PendingItem = {
  id: string;
  turn_id: string;
  agent_id: string;
  kind: string;
  tool_call_id: string | null;
  name: string;
  args: Record<string, unknown>;
  status: string;
};

export type MethodParams = {
  "system.info": Record<string, never>;
  "system.ping": { note: string; op_id?: string };
  "sync.since": { seq: number };
  "bots.create": {
    name: string;
    title?: string;
    scope?: string;
    instructions?: string;
    avatar?: string;
    runtime?: RuntimeName;
    model?: string;
    effort?: string;
    access?: AccessName;
    approval_policy?: ApprovalPolicy;
    folder_id?: string;
    op_id?: string;
  };
  "bots.list": Record<string, never>;
  "bots.get": { bot_id: string };
  "bots.update": {
    bot_id: string;
    name?: string;
    title?: string;
    scope?: string;
    instructions?: string;
    avatar?: string;
    runtime?: RuntimeName;
    model?: string;
    effort?: string;
    access?: AccessName;
    approval_policy?: ApprovalPolicy;
    folder_id?: string;
    paused?: boolean;
    can_create_bots?: boolean;
    op_id?: string;
  };
  "bots.delete": { bot_id: string; purge?: boolean; op_id?: string };
  "agents.list": { bot_id: string };
  "agents.get": { agent_id: string };
  "models.list": Record<string, never>;
  "messages.send": {
    bot_id: string;
    text: string;
    agent_id?: string;
    new_agent?: boolean;
    op_id?: string;
  };
  "messages.list": { bot_id: string; cursor?: string };
  "pending.list": Record<string, never>;
  "pending.answer": {
    pending_id: string;
    answer: "approve" | "deny";
    op_id?: string;
  };
  "turns.snapshot": { turn_id: string };
  "turns.cancel": { turn_id: string; op_id?: string };
};

export type MethodResult = {
  "system.info": {
    host_id: string;
    version: string;
    proto: number;
    caps: string[];
    host_pubkey_fp: string;
  };
  "system.ping": { seq: number };
  "sync.since": { host_seq: number };
  "bots.create": Bot;
  "bots.list": { bots: Bot[] };
  "bots.get": Bot;
  "bots.update": Bot;
  "bots.delete": { id: string };
  "agents.list": { agents: Agent[] };
  "agents.get": Agent;
  "models.list": { models: ModelInfo[] };
  "messages.send": { job_id: string; agent_id: string };
  "messages.list": { messages: ChatMessage[]; next_cursor: string | null };
  "pending.list": { pending: PendingItem[] };
  "pending.answer": { id: string; status: string };
  "turns.snapshot": { text: string; status: string };
  "turns.cancel": { turn_id: string; status: string };
};

export type Status = "connecting" | "connected" | "reconnecting";

export type ProtocolEvent = {
  s: number;
  k: string;
  d: Record<string, unknown>;
};

export type Connection = {
  call: <M extends MethodName>(
    method: M,
    params: MethodParams[M],
  ) => Promise<MethodResult[M]>;
  onEvent: (handler: (event: ProtocolEvent) => void) => void;
  offEvent: (handler: (event: ProtocolEvent) => void) => void;
  onTick: (
    kind: string,
    handler: (data: Record<string, unknown>) => void,
  ) => void;
  offTick: (
    kind: string,
    handler: (data: Record<string, unknown>) => void,
  ) => void;
  onStatus: (handler: (status: Status) => void) => void;
  close: () => void;
};

export type ConnectOptions = {
  url: string;
  token?: string;
  lastSeq?: number;
};

type Pending = {
  resolve: (value: unknown) => void;
  reject: (error: unknown) => void;
};

type TickHandler = (data: Record<string, unknown>) => void;
type EventHandler = (event: ProtocolEvent) => void;

const tickListeners: Array<{ kind: string; handler: TickHandler }> = [];
const eventListeners: EventHandler[] = [];

let active: Connection | null = null;

export function onTick(kind: string, handler: TickHandler): () => void {
  const entry = { kind, handler };
  tickListeners.push(entry);
  active?.onTick(kind, handler);
  return () => {
    const index = tickListeners.indexOf(entry);
    if (index >= 0) {
      tickListeners.splice(index, 1);
    }
    active?.offTick(kind, handler);
  };
}

export function onEvent(handler: EventHandler): () => void {
  eventListeners.push(handler);
  active?.onEvent(handler);
  return () => {
    const index = eventListeners.indexOf(handler);
    if (index >= 0) {
      eventListeners.splice(index, 1);
    }
    active?.offEvent(handler);
  };
}

function attachListeners(connection: Connection): void {
  for (const entry of tickListeners) {
    connection.onTick(entry.kind, entry.handler);
  }
  for (const handler of eventListeners) {
    connection.onEvent(handler);
  }
}

export function call<M extends MethodName>(
  method: M,
  params: MethodParams[M],
): Promise<MethodResult[M]> {
  if (active === null) {
    return Promise.reject(new Error("not connected"));
  }
  return active.call(method, params);
}

export function connect(options: ConnectOptions): Promise<Connection> {
  const url = options.url;
  const token = options.token;
  let lastSeq = options.lastSeq ?? 0;
  let nextSeq = lastSeq + 1;
  let backoff = INITIAL_BACKOFF_MS;
  let status: Status = "connecting";
  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  let settled = false;
  let reconnecting = false;
  let nextId = 1;
  const buffered = new Map<number, ProtocolEvent>();
  let pending = new Map<string, Pending>();
  const eventHandlers: Array<(event: ProtocolEvent) => void> = [];
  const statusHandlers: Array<(next: Status) => void> = [];
  const tickHandlers = new Map<
    string,
    Array<(data: Record<string, unknown>) => void>
  >();

  let resolveReady: (connection: Connection) => void = () => undefined;
  let rejectReady: (error: Error) => void = () => undefined;
  const ready = new Promise<Connection>((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });

  const connection: Connection = {
    call(method, params) {
      return request(method, params);
    },
    onEvent(handler) {
      eventHandlers.push(handler);
    },
    offEvent(handler) {
      const index = eventHandlers.indexOf(handler);
      if (index >= 0) {
        eventHandlers.splice(index, 1);
      }
    },
    onTick(kind, handler) {
      const list = tickHandlers.get(kind) ?? [];
      list.push(handler);
      tickHandlers.set(kind, list);
    },
    offTick(kind, handler) {
      const list = tickHandlers.get(kind);
      if (list === undefined) {
        return;
      }
      const next = list.filter((item) => item !== handler);
      if (next.length === 0) {
        tickHandlers.delete(kind);
        return;
      }
      tickHandlers.set(kind, next);
    },
    onStatus(handler) {
      statusHandlers.push(handler);
      handler(status);
    },
    close() {
      stopped = true;
      if (timer !== undefined) {
        clearTimeout(timer);
        timer = undefined;
      }
      const current = socket;
      socket = null;
      rejectPending(new Error("closed"));
      if (
        current !== null &&
        current.readyState !== WebSocket.CLOSING &&
        current.readyState !== WebSocket.CLOSED
      ) {
        current.close();
      }
      if (active === connection) {
        active = null;
      }
    },
  };

  active = connection;
  attachListeners(connection);
  openSocket();
  return ready;

  function emitStatus(next: Status): void {
    status = next;
    for (const handler of statusHandlers) {
      handler(next);
    }
  }

  function succeed(): void {
    if (settled) {
      return;
    }
    settled = true;
    resolveReady(connection);
  }

  function fail(error: Error): void {
    if (settled) {
      return;
    }
    settled = true;
    rejectReady(error);
  }

  function openSocket(): void {
    if (stopped) {
      return;
    }
    const next = new WebSocket(url);
    socket = next;
    next.addEventListener("open", () => {
      if (socket !== next) {
        return;
      }
      next.send(
        JSON.stringify({
          t: "hello",
          proto: [1, 1],
          client: "web",
          device: "dev_web",
          last_seq: lastSeq,
          caps: [],
        }),
      );
      if (token) {
        next.send(JSON.stringify({ t: "auth", token }));
      }
    });
    next.addEventListener("message", (event) => {
      if (socket !== next) {
        return;
      }
      onMessage(messageText(event));
    });
    next.addEventListener("close", (event) => {
      if (socket !== next && socket !== null) {
        return;
      }
      if (socket === next) {
        socket = null;
      }
      onClose(closeCode(event));
    });
  }

  function onMessage(text: string): void {
    let frame: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(text);
      if (!isRecord(parsed)) {
        return;
      }
      frame = parsed;
    } catch {
      return;
    }
    if (frame.t === "welcome") {
      backoff = INITIAL_BACKOFF_MS;
      emitStatus("connected");
      succeed();
      const seq = lastSeq;
      void request("sync.since", { seq }).catch(() => undefined);
      return;
    }
    if (frame.t === "res") {
      settleResponse(frame);
      return;
    }
    if (frame.t === "evt") {
      acceptEvent(frame);
      return;
    }
    if (frame.t === "tick") {
      acceptTick(frame);
    }
  }

  function onClose(code: number): void {
    rejectPending(new Error("closed"));
    if (stopped) {
      return;
    }
    if (code === 4001 || code === 4002) {
      const error = code === 4001 ? new Unauthorized() : new IncompatibleHost();
      fail(error);
      return;
    }
    if (reconnecting) {
      return;
    }
    reconnecting = true;
    emitStatus("reconnecting");
    const wait = backoff;
    backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
    timer = setTimeout(() => {
      timer = undefined;
      reconnecting = false;
      openSocket();
    }, wait);
  }

  function request<M extends MethodName>(
    method: M,
    params: MethodParams[M],
  ): Promise<MethodResult[M]> {
    const current = socket;
    if (current === null || current.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("not connected"));
    }
    const id = String(nextId);
    nextId += 1;
    const body = withOpId(method, params);
    const promise = new Promise<MethodResult[M]>((resolve, reject) => {
      pending.set(id, {
        resolve: (value) => {
          resolve(value as MethodResult[M]);
        },
        reject,
      });
    });
    current.send(JSON.stringify({ t: "req", id, m: method, p: body }));
    return promise;
  }

  function settleResponse(frame: Record<string, unknown>): void {
    const id = frame.id;
    if (typeof id !== "string" && typeof id !== "number") {
      return;
    }
    const waiter = pending.get(String(id));
    if (waiter === undefined) {
      return;
    }
    pending.delete(String(id));
    if (isRecord(frame.e)) {
      const code = frame.e.code;
      const message = frame.e.message;
      waiter.reject(
        new ProtocolError(
          typeof code === "string" ? code : "protocol_error",
          typeof message === "string" ? message : "request failed",
        ),
      );
      return;
    }
    waiter.resolve(isRecord(frame.r) ? frame.r : {});
  }

  function acceptEvent(frame: Record<string, unknown>): void {
    const seq = frame.s;
    const kind = frame.k;
    const data = frame.d;
    if (
      typeof seq !== "number" ||
      typeof kind !== "string" ||
      !isRecord(data)
    ) {
      return;
    }
    if (seq < nextSeq) {
      return;
    }
    buffered.set(seq, { s: seq, k: kind, d: data });
    while (buffered.has(nextSeq)) {
      const event = buffered.get(nextSeq);
      buffered.delete(nextSeq);
      if (event === undefined) {
        break;
      }
      nextSeq += 1;
      lastSeq = event.s;
      for (const handler of eventHandlers) {
        handler(event);
      }
    }
  }

  function acceptTick(frame: Record<string, unknown>): void {
    const kind = frame.k;
    const data = frame.d;
    if (typeof kind !== "string" || !isRecord(data)) {
      return;
    }
    for (const handler of tickHandlers.get(kind) ?? []) {
      handler(data);
    }
  }

  function rejectPending(error: Error): void {
    const waiting = pending;
    pending = new Map();
    for (const waiter of waiting.values()) {
      waiter.reject(error);
    }
  }
}

function withOpId(method: string, params: object): Record<string, unknown> {
  const body: Record<string, unknown> = { ...params };
  if (!isMutating(method)) {
    return body;
  }
  const opId = body.op_id;
  if (typeof opId === "string" && opId.length > 0) {
    return body;
  }
  body.op_id = uuidv7();
  return body;
}

function isMutating(method: string): boolean {
  if (!Object.hasOwn(methods, method)) {
    return false;
  }
  return methods[method as MethodName].mutating;
}

function uuidv7(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const timestamp = BigInt(Date.now());
  bytes[0] = Number((timestamp >> 40n) & 0xffn);
  bytes[1] = Number((timestamp >> 32n) & 0xffn);
  bytes[2] = Number((timestamp >> 24n) & 0xffn);
  bytes[3] = Number((timestamp >> 16n) & 0xffn);
  bytes[4] = Number((timestamp >> 8n) & 0xffn);
  bytes[5] = Number(timestamp & 0xffn);
  bytes[6] = (bytes[6] & 0x0f) | 0x70;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function messageText(event: Event): string {
  if ("data" in event) {
    const data = (event as MessageEvent).data;
    return typeof data === "string" ? data : String(data);
  }
  return String(event);
}

function closeCode(event: Event): number {
  if ("code" in event && typeof (event as CloseEvent).code === "number") {
    return (event as CloseEvent).code;
  }
  return 1005;
}
