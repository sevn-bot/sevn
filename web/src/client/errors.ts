/** Protocol failure carried on `res.e`. */
export class ProtocolError extends Error {
  readonly code: string;
  readonly data: Record<string, unknown> | undefined;

  constructor(code: string, message: string, data?: Record<string, unknown>) {
    super(message);
    this.name = "ProtocolError";
    this.code = code;
    this.data = data;
  }
}

/** WebSocket close 4001. The client does not retry. */
export class Unauthorized extends Error {
  constructor(message = "unauthorized") {
    super(message);
    this.name = "Unauthorized";
  }
}

/** WebSocket close 4002. The client does not retry. */
export class IncompatibleHost extends Error {
  constructor(message = "update sevn: host speaks 1..1") {
    super(message);
    this.name = "IncompatibleHost";
  }
}

/**
 * The host's `challenge` does not verify against the pinned host key (plan 0055 D6).
 * A hard error: no `auth` is sent, nothing is re-pinned and the client does not retry.
 */
export class HostIdentityChanged extends Error {
  constructor(message = "Host identity changed — re-pair to continue") {
    super(message);
    this.name = "HostIdentityChanged";
  }
}

/** Why the client-side network check (plan 0055 D7) refused a direct URL. */
export type DirectUrlReason = "scheme" | "hostname_over_ws" | "not_private";

const DIRECT_URL_RULES: Record<DirectUrlReason, string> = {
  scheme: "a direct URL must be wss:// or ws://",
  hostname_over_ws:
    "a ws:// URL must name an IP address; use wss:// or turn on allow_plain_ws for this host",
  not_private:
    "a ws:// URL must be loopback or in this host's private networks; use wss:// or turn on allow_plain_ws for this host",
};

/** The D7 check refused a direct URL before any socket opened. */
export class DirectUrlRefused extends Error {
  readonly url: string;
  readonly reason: DirectUrlReason;

  constructor(url: string, reason: DirectUrlReason) {
    super(`refused ${url}: ${DIRECT_URL_RULES[reason]}`);
    this.name = "DirectUrlRefused";
    this.url = url;
    this.reason = reason;
  }
}

/** The page's Content-Security-Policy `connect-src` blocked a dial (plan 0055 D8). */
export class CspBlocked extends Error {
  readonly origin: string;

  constructor(origin: string) {
    super(
      `blocked by connect-src: add ${origin} to http.connect_src on the host that serves this page`,
    );
    this.name = "CspBlocked";
    this.origin = origin;
  }
}
