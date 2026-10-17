# Spike S1 — sevn-link WebRTC library

Verdict: **blocked**. No library is chosen. Desktop WebKit passed data and video for both
libraries. S-TURN was measured through Cloudflare. iOS Safari was not run. Decision D7
forbids a choice without that Safari gate.

`VERDICT.json` leaves `sha` null. The commit that adds this report is the revision; a commit
object cannot contain its own id. The wave plan annotation records that commit.

## Setup

Two peers implement the same `common::Peer` trait, one on `webrtc` 0.21.1 and one on
`str0m` 0.24.1. A one-room WebSocket server makes the first client the offerer. Each peer
negotiates three ordered reliable data channels (`rpc` / `events` / `files`, ids 0/1/2) and
an H.264 video m-line.

S-LAN is loopback on one macOS arm64 host (`cargo run --release`). The 20-run numbers below
are the release profile. A debug build of str0m moved the same 10 MiB blob at about 3 MiB/s;
that figure is not in `results/`.

The test pattern is 15 frames from ffmpeg (`testsrc`, 1280×720, 30 fps, libx264 baseline,
level 3.1, Annex B). x264's baseline SPS is `profile-level-id=42c01f`. The encoder output
is patched to constrained baseline `42e01f` (constraint set 2), with `packetization-mode=1`.

### Version pins

| Tool | Version |
|------|---------|
| rustc | 1.98.1 (48a229cea 2026-09-01) |
| cargo | 1.98.1 (797e8a9bc 2026-08-05) |
| node | v25.8.1 |
| pnpm | 11.8.0 |
| ffmpeg | 8.1 (libx264) |
| Chrome for Testing | 153.0.8010.12 (Playwright chromium-1243) |
| Playwright WebKit | 26.6 (webkit-2359) |
| webrtc-rs | 0.21.1 |
| str0m | 0.24.1 (`aws-lc-rs`) |

### What the S-LAN fields measure

Twenty runs. Percentiles are nearest-rank: index `ceil(p/100*n)-1` (p50 is the 10th sample,
p95 the 19th).

- `connect_p50_ms` / `connect_p95_ms`: wall time from just before `connect` until an `rpc`
  probe is delivered on the other peer (offer sent through a usable channel).
- `mbps_10mb`: median MiB/s of a 10 MiB payload (`10*1024*1024` bytes) on `files`, including
  the 24-byte D2 header. 1 MiB/s is stricter than 1 MB/s, so a pass against 5 MiB/s also
  clears the 5 MB/s bar.
- `ice_restart_ms`: median wall time from `ice_restart()` until a following `rpc` probe is
  delivered.
- `first_frame_ms`: sender clock, from ready-to-write until the first access unit is handed
  to the RTP writer. The pattern is cached before connect, so this lands at 1 ms. It is not
  the browser `requestVideoFrameCallback` time. Chrome (the harness test) and desktop WebKit
  (a separate check) each rendered 1280×720.
- `rss_mb`: `ru_maxrss` of the measure process after all 20 runs (macOS reports bytes).
- `cpu_pct`: process user+system time over wall time for those 20 runs. Above 100 means more
  than one core.

## Results

### S-LAN (measured, release, 20 runs)

| Field | webrtc-rs 0.21.1 | str0m 0.24.1 |
|-------|------------------|--------------|
| connect p50 | 412.5 ms | 30.3 ms |
| connect p95 | 451.5 ms | 32.2 ms |
| 10 MiB median | 77.74 MiB/s | 35.40 MiB/s |
| ICE restart median | 0.95 ms | 23.53 ms |
| sender first frame | 1.0 ms | 1.0 ms |
| process RSS | 125.7 MB | 135.3 MB |
| process CPU | 26.8% | 130.9% |

Source: `results/s-lan-webrtcrs.json`, `results/s-lan-str0m.json`.

### S-TURN (measured, release, 20 runs, relay only)

Both peers used `iceTransportPolicy: relay`. webrtc-rs gathered through its own TURN
client. str0m 0.24.1 still has no TURN client; this spike allocated the relay with
`rtc-turn` 0.21.1 and handed str0m only the unwrapped datagrams. UDP is `turn` port
3478. TLS:443 is `turns` on 443, self-delimited TURN on the stream. Result files name
the transports `udp` and `tls443` and the candidate type `relay`.

| Field | webrtc-rs UDP | str0m UDP | webrtc-rs TLS:443 | str0m TLS:443 |
|-------|---------------|-----------|-------------------|---------------|
| connect p50 | 5066.3 ms | 150.0 ms | no relay candidate | 214.8 ms |
| connect p95 | 5353.8 ms | 184.4 ms | — | 365.6 ms |
| 10 MiB median | 6.57 MiB/s | 12.22 MiB/s | — | 3.40 MiB/s |
| ICE restart median | 3079.6 ms | 25.7 ms | — | 40.2 ms |
| sender first frame | 1.0 ms | 1.0 ms | — | 1.0 ms |
| process RSS | 127.0 MB | 134.7 MB | — | 119.4 MB |
| process CPU | 3.7% | 40.4% | — | 19.3% |

webrtc-rs 0.21.1 does not gather a relay candidate for TLS:443 (it skips secure TURN).
That row is one failed attempt, not 20 timeouts. Source:
`results/s-turn-webrtcrs.json`, `results/s-turn-str0m.json`.

### S-iOS (skipped)

Safari on the physical iPhone opened the webrtc-rs page over the private LAN and showed
a blank page. The harness answered before Safari finished sending the request, then
closed. No `channels open` time was recorded. The simulator does not count.
`results/s-ios-*.json` stays `skipped: true`.

### Other checks from this run

| Check | webrtc-rs | str0m |
|-------|-----------|-------|
| Chrome three channels + 10 MB file | pass | pass |
| Chrome first frame 1280×720 within 3 s | pass | pass |
| Desktop WebKit three channels + 10 MB file | pass | pass |
| Desktop WebKit first frame 1280×720 | pass | pass |
| 100 loopback connects, 0 failures | 100/100 | 100/100 |

Desktop WebKit video was a one-off Playwright check against the same harness page, not a
stored millisecond. The callback reported width 1280 and height 720 for both libraries.
`results/stability-*.json` holds the 100-connect counts.

## D7 scoring

| Bar | webrtc-rs | str0m |
|-----|-----------|-------|
| S-LAN connect p50 < 1.0 s | pass (412 ms) | pass (30 ms) |
| S-TURN connect p50 < 3.0 s | fail (UDP 5066 ms; TLS:443 no relay candidate) | pass (UDP 150 ms, TLS:443 215 ms) |
| LAN 10 MB ≥ 5 MB/s | pass (77.7 MiB/s) | pass (35.4 MiB/s) |
| ICE restart < 5 s | pass (1.0 ms) | pass (23.5 ms) |
| Chrome data + video | pass | pass |
| Safari data + video | desktop WebKit pass; iOS Safari not run | desktop WebKit pass; iOS Safari not run |
| 100 connects, no crash | pass | pass |

webrtc-rs misses the S-TURN connect bar. str0m clears the bars that were run, including
both relay transports, using the spike's TURN adapter rather than a client inside str0m.
D7 says a tie goes to str0m, and that neither passing means plan C (pion). Neither of
those outcomes applies: iOS Safari evidence is missing, so the verdict is **blocked**
and `choice` is null.

## iOS build (0068)

`xcode-select -p` is `/Library/Developer/CommandLineTools`. `xcrun --sdk iphoneos` and
`xcrun --sdk iphonesimulator` both fail with `SDK cannot be located`. Rust targets
`aarch64-apple-ios` and `aarch64-apple-ios-sim` are installed.

| Target | peer-webrtcrs | peer-str0m | common |
|--------|---------------|------------|--------|
| aarch64-apple-ios | fail | fail | fail (depends on both) |
| aarch64-apple-ios-sim | fail | fail | fail (depends on both) |

The compiler stops in a build script before either peer crate is compiled:

- webrtc-rs: `ring` 0.17.14, `error: failed to run custom build command`, `xcrun --sdk iphoneos`
  / `iphonesimulator` exit 1.
- str0m (`aws-lc-rs`): `aws-lc-sys` 0.46.0, the same `xcrun` SDK error.

`ios_build` is false. This is a missing Apple SDK on the machine, not a measured source
incompatibility. Re-run after Xcode is installed before treating either crate as unable to
cross-compile.

## Risks

- **TURN.** Spec §3.1 allows only TURN (UDP, TCP, TLS:443). webrtc-rs relayed UDP;
  connect p50 was 5.07 s, over the 3.0 s bar, and TLS:443 produced no relay candidate.
  str0m 0.24.1 has no TURN client. The numbers above are from an adapter in this spike
  (`rtc-turn` 0.21.1), not from str0m itself.
- **H.264 packetization.** Chrome and Safari want constrained baseline `42e01f`. libx264
  baseline emits `42c01f`. The spike rewrites that byte. A later VideoToolbox encoder that
  emits plain baseline will negotiate and then fail to decode.
- **str0m media events.** `MediaAdded` fires for media in the remote offer, not for media
  this side added. The writer uses the `Mid` returned by `add_media`.
- **ICE restart.** Both recover on loopback well under 5 s. Through UDP relay, webrtc-rs
  took 3.08 s and str0m 26 ms. TLS:443 restart was 40 ms on str0m. webrtc-rs had no TLS
  relay to restart.
- **webrtc-rs first send.** `Connected` can arrive before SCTP `OnOpen`. A send in that gap
  was dropped under parallel load (the first ordered message never arrived). `connect` now
  waits until all three channels are open.
- **CPU.** str0m's measure process used 131% CPU across the 20 runs; webrtc-rs used 27%.
  D7 does not set a CPU cap. The gap matters for a phone.
- **Maintenance.** str0m is the smaller sans-IO crate (D7's tie-break). webrtc-rs is the
  larger stack and already speaks UDP TURN. It does not speak TLS:443 TURN.

## Decision text for downstream plans

Do not copy a library into product code off this spike.

**0065 (sevn-link).** WebRTC library is undecided (spike 0002 verdict `blocked`). On loopback,
release, 20 runs: webrtc-rs 0.21.1 connect p50 412 ms, 77.7 MiB/s, ICE restart 1.0 ms;
str0m 0.24.1 connect p50 30 ms, 35.4 MiB/s, ICE restart 23.5 ms. Both did Chrome and desktop
WebKit data plus 1280×720 H.264, and 100 connects with no failure. S-TURN, same profile,
relay only: webrtc-rs UDP connect p50 5066 ms (over 3.0 s) at 6.57 MiB/s, ICE restart 3.08 s;
TLS:443 gathered no relay candidate. str0m, via this spike's `rtc-turn` adapter, UDP connect
p50 150 ms at 12.22 MiB/s and TLS:443 connect p50 215 ms at 3.40 MiB/s. str0m 0.24.1 still
has no TURN client of its own. iOS Safari was not run. A tie, if both later pass, selects
str0m. If the adapter is not acceptable as str0m, the choice is webrtc-rs or plan C (pion
sidecar).

**0068 (UniFFI / Apple).** `ios_build` is false. Cross-builds for `aarch64-apple-ios` and
`aarch64-apple-ios-sim` stop in `ring` 0.17.14 (webrtc-rs) and `aws-lc-sys` 0.46.0 (str0m)
because the iPhoneOS and iPhoneSimulator SDKs are not installed. Repeat the build on an
Xcode toolchain before blaming either crate.

**0075 (screen video).** The wire format that decoded in Chrome and desktop WebKit is
`video/H264`, `profile-level-id=42e01f`, `packetization-mode=1`, 1280×720. Software x264
baseline does not emit that profile id; the SPS constraint byte was patched. VideoToolbox
was not used.

**0080 (edge / TURN).** Release, 20 runs, relay only. webrtc-rs UDP candidate type `relay`,
connect p50 5066 ms, 6.57 MiB/s; TLS:443 produced no relay candidate. str0m UDP connect p50
150 ms, 12.22 MiB/s; TLS:443 connect p50 215 ms, 3.40 MiB/s. Those str0m numbers used an
adapter in this spike. str0m 0.24.1 cannot place a TURN allocation by itself.
