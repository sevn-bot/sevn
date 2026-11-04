# Remote access over a tailnet (direct, no edge)

A sevn host listens on loopback (`127.0.0.1:8787`) by default. To reach it from another machine
or a phone, put it on a private overlay network and pair each browser with it. The browser then
connects straight to the host over WebSocket. Nothing goes through a relay.

The examples use the placeholder names `mac.tailnet.ts.net` and `linux.tailnet.ts.net`. Replace
them with your machines' MagicDNS names.

## How a remote browser gets in

- A **loopback** session is one from `127.0.0.1`, `localhost` or `[::1]`, with that name in the
  `Host` header on the bound port and no proxy header. Only a loopback session can use the run
  token or the login cookie, and it is always `owner`.
- Every other session has to be a **paired device**. After `hello`, the host sends a challenge
  signed with its host key over a fresh nonce and the origin the browser dialled. The browser
  answers with the device key it made when it paired. The session then has the scope the owner
  chose for that device: `owner`, `member` or `read_only`.
- **Pairing** uses a one-time ticket that expires after 10 minutes. You can start one with
  `sevn pair` on the host, which prints a QR code and an 8-character short code. You can also
  start one from **Settings → Devices** in the web app on the host. On the new device, open
  **Add a host**, then either scan the QR code (in browsers with `BarcodeDetector`) or enter the
  host address and the short code. The device stores a non-extractable Ed25519 key for that
  host in IndexedDB. It never sends the private key anywhere.
- **Revoking** a device (Settings → Devices, or `sevn devices revoke <id>`) closes its open
  sessions within a second. Later connections from that device are refused.

### The proxy-header rule

`tailscale serve` connects to sevn from `127.0.0.1`, so the peer address alone would make every
tailnet user look local. To prevent that, sevn treats a request as non-loopback whenever it
carries any of these headers: `Forwarded`, `X-Forwarded-For`, `X-Forwarded-Host`,
`X-Forwarded-Proto`, `X-Real-IP`, `Tailscale-User-Login`, `Tailscale-User-Name`,
`Tailscale-User-Profile-Pic` or `Tailscale-Headers-Info`.

- Anything that arrives through `tailscale serve`, or through any proxy that adds one of these
  headers, is not local. It has to pass the device handshake. A proxy that rewrites `Host` to
  a loopback name and adds none of these headers (an nginx default) cannot be told apart from
  a local client; such a request still needs the loopback token or cookie.
- `/auth/login` works only on loopback. Every other request gets `403 login is loopback only`.
- sevn only checks whether these headers are present. `Tailscale-User-Login` and the other
  identity headers are never used as identity. A tailnet user who has not paired a device gets
  the challenge and then a close with 4001.

### A secure page is required

WebCrypto, which holds the device key, only works on a secure page: `https://…`, or
`http://localhost` / `http://127.0.0.1`. A page served over plain `http://` from a tailnet IP
cannot pair. A page served over `https://` can only dial `wss://` (browsers block `ws://` from
an https page). **iOS Safari therefore needs the `wss://` form below.** The same goes for any
phone browser that opens the web app on a remote host.

## Tailscale with `tailscale serve` (recommended)

On each host:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8787
```

Then add this to `$SEVN_HOME/config.toml` and restart `sevn serve`:

```toml
[http]
allowed_hosts = ["mac.tailnet.ts.net"]
public_scheme = "https"
```

`allowed_hosts` lets the `Host` header and the handshake origin `wss://mac.tailnet.ts.net`
through the guard. `public_scheme = "https"` makes the QR link carry
`d=wss://mac.tailnet.ts.net/ws`, so a scanning device knows where to connect. sevn itself still
listens on loopback, and `tailscale serve` provides the TLS certificate.

Pair a browser with this host:

1. Run `sevn pair` on the host. Add `--scope owner` for a device that should have full control;
   the default is `member`. You can also use **Settings → Devices** in a browser on the host
   itself (`http://127.0.0.1:8787`).
2. On the new device, open `https://mac.tailnet.ts.net/pairing`. Scan the QR code, or enter
   `wss://mac.tailnet.ts.net/ws` and the short code.
3. Done. The page reconnects with its device key.

### One web app, several hosts

Any host's web app can show every paired host: one sidebar grouped by host, one Inbox and one
Approvals view. Say the Mac serves the web app and you want to add `linux.tailnet.ts.net`:

- On the **Linux host**, also allow the origin of the page that will dial it. That is the exact
  scheme, host and port shown in the browser's address bar:

  ```toml
  [http]
  allowed_hosts = ["linux.tailnet.ts.net"]
  public_scheme = "https"
  allowed_origins = ["https://mac.tailnet.ts.net", "http://127.0.0.1:8787"]
  ```

- On the **Mac**, which serves the page, let the page's Content-Security-Policy connect to the
  Linux host:

  ```toml
  [http]
  connect_src = ["wss://linux.tailnet.ts.net"]
  ```

  If this line is missing, the pairing screen shows exactly which `connect_src` line to add.

- Run `sevn pair` on the Linux host. In the Mac's web app, open **Add a host** and enter
  `wss://linux.tailnet.ts.net/ws` and the short code.

**Forget** in the sidebar removes a paired host. It revokes this device on that host first when
the host answers. If the host refuses revocation (for example, this is its last owner device),
the app shows the refusal and keeps the profile and key. If the host cannot be reached, it
removes the local profile; revoke the device on the host when it is available again.

## Headscale

Headscale uses the same address ranges as Tailscale (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`).
Those are the defaults the web client accepts for `ws://`. If your Headscale setup can issue
certificates for `tailscale serve --https`, follow the Tailscale recipe with your Headscale
MagicDNS names. If it cannot, bind sevn to the node's tailnet address as described in the next
section. Plain `ws://` to a `100.x` address then needs no extra setting, but phones still need
an https page (see above).

## NetBird, ZeroTier, WireGuard

Bind sevn to the host's overlay address. Any address other than loopback needs
`--allow-remote-bind`, and every name or address that clients will use has to be listed:

```bash
sevn serve --host 10.147.17.5 --port 8787 --allow-remote-bind
```

```toml
[http]
allowed_hosts = ["10.147.17.5:8787"]
```

On such a bind no TCP connection is loopback, so the login link does not work and
`sevn serve --open` prints a hint instead: run `sevn pair --scope owner` on the host and enter
the code in the web app. The local CLI (`sevn probe`, `sevn devices revoke`) reaches the host
through its unix control socket, `<home>/run/control.sock` (mode 0600).

The browser checks a `ws://` URL before it dials. It accepts loopback, an IP inside the
profile's private networks, or any `ws://` URL when the owner has turned on **Allow plain ws://
for this host**. A `ws://` hostname always needs that toggle, because the browser resolves the
name itself.

When you pair with `ws://10.147.17.5:8787/ws`, the pairing screen refuses the first try and
shows the rule. Enter your overlay's subnet under **Private networks for this host** (for
example `10.147.17.0/24` for ZeroTier, or the subnet of your WireGuard interface) and pair
again. That list replaces the default Tailscale ranges for this host. NetBird's default range is
`100.64.0.0/10`, which is already in the defaults.

Plain `ws://` is not encrypted by the browser. The overlay encrypts the traffic between the two
machines. Keep in mind that a page served over `http://<overlay-ip>` is not a secure page, so
pair from a browser that loads the web app from its own loopback, or use an https front end.

## Containers

Inside Docker, the browser's peer address is the bridge gateway, not loopback. A container host
therefore never treats the browser as local:

- `/auth/login` returns 403 by design.
- The image's `sevn serve --host 0.0.0.0 --allow-remote-bind` refuses to start unless
  `SEVN_ALLOWED_HOSTS` (or `http.allowed_hosts`) is set.

Publish the port on loopback and pair the browser with an owner ticket:

```bash
docker build -f deploy/Dockerfile -t sevn .
docker run -d --name sevn -p 127.0.0.1:8787:8787 \
  -e SEVN_ALLOWED_HOSTS=127.0.0.1:8787 -v sevn-data:/data sevn
docker exec sevn sevn pair --scope owner
```

Open `http://127.0.0.1:8787/pairing` and enter `ws://127.0.0.1:8787/ws` and the short code. The
web app then reconnects to its own host with the new device key.
