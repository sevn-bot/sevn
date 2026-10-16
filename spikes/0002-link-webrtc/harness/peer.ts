const FILE_BYTES = 10 * 1024 * 1024;
const HEADER = 24;

const params = new URLSearchParams(location.search);
const scenario = params.get("scenario") ?? "";
const signalUrl = params.get("signal") ?? "";

const spike = {
  channels: [],
  receivedBytes: 0,
  receivedSha256: "",
};
window.sevnSpike = spike;

const specs = [
  { id: 0, label: "rpc" },
  { id: 1, label: "events" },
  { id: 2, label: "files" },
];

const pc = new RTCPeerConnection({ iceServers: [] });
const dataChannels = specs.map((spec) => {
  const channel = pc.createDataChannel(spec.label, {
    ordered: true,
    negotiated: true,
    id: spec.id,
  });
  channel.binaryType = "arraybuffer";
  return channel;
});

const parts = new Map();
let got = 0;

dataChannels[2].onmessage = (event) => {
  const bytes = new Uint8Array(event.data);
  if (bytes.length < HEADER) {
    return;
  }
  const offset = Number(new DataView(bytes.buffer, bytes.byteOffset + 16, 8).getBigUint64(0));
  const payload = bytes.subarray(HEADER);
  if (!parts.has(offset)) {
    parts.set(offset, payload);
    got += payload.length;
  }
  if (got >= FILE_BYTES) {
    void finishFile();
  }
};

async function finishFile() {
  const out = new Uint8Array(FILE_BYTES);
  let cursor = 0;
  const offsets = [...parts.keys()].sort((a, b) => a - b);
  for (const offset of offsets) {
    const payload = parts.get(offset);
    out.set(payload, cursor);
    cursor += payload.length;
  }
  const digest = await crypto.subtle.digest("SHA-256", out);
  const hex = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  spike.receivedSha256 = hex;
  spike.receivedBytes = out.length;
}

let openCount = 0;
for (const channel of dataChannels) {
  channel.onopen = () => {
    openCount += 1;
    if (openCount !== specs.length) {
      return;
    }
    spike.channels = specs.map((spec) => ({ id: spec.id, label: spec.label }));
    if (scenario === "file") {
      dataChannels[0].send(new TextEncoder().encode("ready"));
    }
  };
}

const pending = [];
let haveRemote = false;

function send(message) {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(message));
  }
}

async function flush() {
  const queued = pending.splice(0);
  for (const candidate of queued) {
    await pc.addIceCandidate(candidate);
  }
}

const ws = new WebSocket(signalUrl);
ws.onmessage = async (event) => {
  const message = JSON.parse(event.data);
  if (message.kind === "role" && message.role === "offerer") {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    send({ kind: "offer", sdp: pc.localDescription.sdp });
  } else if (message.kind === "offer") {
    await pc.setRemoteDescription({ type: "offer", sdp: message.sdp });
    haveRemote = true;
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    send({ kind: "answer", sdp: pc.localDescription.sdp });
    await flush();
  } else if (message.kind === "answer") {
    await pc.setRemoteDescription({ type: "answer", sdp: message.sdp });
    haveRemote = true;
    await flush();
  } else if (message.kind === "candidate" && message.candidate) {
    const candidate = {
      candidate: message.candidate,
      sdpMid: message.sdpMid ?? "0",
      sdpMLineIndex: message.sdpMLineIndex ?? 0,
    };
    if (haveRemote) {
      await pc.addIceCandidate(candidate);
    } else {
      pending.push(candidate);
    }
  }
};

pc.onicecandidate = (event) => {
  if (!event.candidate) {
    return;
  }
  send({
    kind: "candidate",
    candidate: event.candidate.candidate,
    sdpMid: event.candidate.sdpMid,
    sdpMLineIndex: event.candidate.sdpMLineIndex,
  });
};
