/** Protocol failure carried on `res.e`. */
export class ProtocolError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "ProtocolError";
    this.code = code;
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
