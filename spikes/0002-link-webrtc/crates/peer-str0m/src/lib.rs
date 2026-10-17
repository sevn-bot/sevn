//! str0m peer (`str0m` 0.24.1). One worker thread owns the sans-IO `Rtc` and its UDP socket.

use std::fmt;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

mod relay;

use str0m::change::{SdpAnswer, SdpOffer, SdpPendingOffer};
use str0m::channel::{ChannelConfig, ChannelId, Reliability};
use str0m::format::Codec;
use str0m::media::{Direction, MediaKind, MediaTime, Mid};
use str0m::net::{Protocol, Receive};
use str0m::{Candidate, Event, Input, Output, Rtc};
use tokio::net::UdpSocket;
use tokio::sync::{mpsc, watch};

#[path = "../../common/src/chunk.rs"]
mod chunk;
#[path = "../../common/src/video.rs"]
mod video;

use chunk::{CHANNEL_FILES, CHANNEL_SPECS, PauseGate};

const CONNECT_TIMEOUT: Duration = Duration::from_secs(20);
const RESTART_TIMEOUT: Duration = Duration::from_secs(4);
const SEND_TIMEOUT: Duration = Duration::from_secs(60);
/// Above the 1 MiB pause watermark so a loopback sender can actually queue that much.
const SCTP_BUFFER: usize = 4 * 1024 * 1024;

#[derive(Debug)]
pub enum Error {
    Timeout,
    Failed(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Timeout => f.write_str("timed out"),
            Error::Failed(message) => f.write_str(message),
        }
    }
}

impl std::error::Error for Error {}

#[derive(Debug, Clone, Copy)]
pub struct Stats {
    pub connect_ms: u64,
    pub ice_restart_ms: u64,
    pub backpressure_pauses: u64,
    pub first_frame_ms: u64,
    pub rss_mb: f64,
    pub cpu_pct: f64,
}

struct StatsInner {
    connect_ms: AtomicU64,
    ice_restart_ms: AtomicU64,
    backpressure_pauses: AtomicU64,
    first_frame_ms: AtomicU64,
}

type Reply<T> = std::sync::mpsc::Sender<Result<T, Error>>;

enum Cmd {
    Connect(String, Reply<()>),
    Open(Reply<Vec<(u16, String)>>),
    Send {
        channel: u16,
        bytes: Vec<u8>,
        reply: Reply<()>,
    },
    IceRestart(Reply<()>),
    EnableVideo(Reply<()>),
}

struct Chan {
    our_id: u16,
    label: String,
    id: ChannelId,
    open: bool,
}

struct ConnectWait {
    reply: Reply<()>,
    started: Instant,
}

struct RestartWait {
    reply: Reply<()>,
    started: Instant,
    pending: Option<SdpPendingOffer>,
    answer_applied: bool,
    saw_down: bool,
}

struct SendJob {
    reply: Reply<()>,
    channel: u16,
    chunks: Vec<Vec<u8>>,
    index: usize,
    gate: PauseGate,
    started: Instant,
}

struct World {
    rtc: Rtc,
    sock: Arc<UdpSocket>,
    local_addr: SocketAddr,
    relay: Option<relay::TurnSide>,
    net_rx: mpsc::UnboundedReceiver<Vec<u8>>,
    tls_relay: bool,
    signal_tx: mpsc::UnboundedSender<String>,
    signal_rx: mpsc::UnboundedReceiver<String>,
    role: String,
    channels: Vec<Chan>,
    pending: Option<SdpPendingOffer>,
    candidate_sdp: String,
    buf: Vec<u8>,
    video: bool,
    video_mid: Option<Mid>,
    video_units: Vec<Vec<u8>>,
    video_index: usize,
    video_next: Instant,
    video_rtp: u64,
    video_ready: Option<Instant>,
}

pub struct Peer {
    rt: Mutex<Option<tokio::runtime::Runtime>>,
    cmd_tx: mpsc::Sender<Cmd>,
    incoming_rx: Mutex<std::sync::mpsc::Receiver<(u16, Vec<u8>)>>,
    cancel_tx: watch::Sender<bool>,
    stats: Arc<StatsInner>,
    local_sdp: Arc<Mutex<String>>,
}

impl Peer {
    pub fn new() -> Self {
        let rt = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("tokio runtime");
        let (cmd_tx, cmd_rx) = mpsc::channel(8);
        let (incoming_tx, incoming_rx) = std::sync::mpsc::channel();
        let (cancel_tx, cancel_rx) = watch::channel(false);
        let stats = Arc::new(StatsInner {
            connect_ms: AtomicU64::new(0),
            ice_restart_ms: AtomicU64::new(0),
            backpressure_pauses: AtomicU64::new(0),
            first_frame_ms: AtomicU64::new(0),
        });
        let local_sdp = Arc::new(Mutex::new(String::new()));
        let want_video = Arc::new(AtomicBool::new(false));
        rt.spawn(worker(
            cmd_rx,
            incoming_tx,
            cancel_rx,
            Arc::clone(&stats),
            Arc::clone(&local_sdp),
            want_video,
        ));
        Self {
            rt: Mutex::new(Some(rt)),
            cmd_tx,
            incoming_rx: Mutex::new(incoming_rx),
            cancel_tx,
            stats,
            local_sdp,
        }
    }

    pub fn connect(&self, signal_url: &str) -> Result<(), Error> {
        self.call(|reply| Cmd::Connect(signal_url.to_owned(), reply))
    }

    pub fn open_channels(&self) -> Result<Vec<(u16, String)>, Error> {
        self.call(|reply| Cmd::Open(reply))
    }

    pub fn send(&self, channel: u16, bytes: &[u8]) -> Result<(), Error> {
        self.call(|reply| Cmd::Send {
            channel,
            bytes: bytes.to_vec(),
            reply,
        })
    }

    pub fn recv_timeout(&self, timeout: Duration) -> Result<(u16, Vec<u8>), Error> {
        match self
            .incoming_rx
            .lock()
            .expect("incoming")
            .recv_timeout(timeout)
        {
            Ok(message) => Ok(message),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => Err(Error::Timeout),
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                Err(Error::Failed("peer stopped".into()))
            }
        }
    }

    pub fn ice_restart(&self) -> Result<(), Error> {
        self.call(|reply| Cmd::IceRestart(reply))
    }

    pub fn metrics(&self) -> Stats {
        Stats {
            connect_ms: self.stats.connect_ms.load(Ordering::Relaxed),
            ice_restart_ms: self.stats.ice_restart_ms.load(Ordering::Relaxed),
            backpressure_pauses: self.stats.backpressure_pauses.load(Ordering::Relaxed),
            first_frame_ms: self.stats.first_frame_ms.load(Ordering::Relaxed),
            rss_mb: 0.0,
            cpu_pct: 0.0,
        }
    }

    pub fn enable_test_video(&self) -> Result<(), Error> {
        video::h264_access_units().map_err(Error::Failed)?;
        self.call(|reply| Cmd::EnableVideo(reply))
    }

    pub fn local_description(&self) -> String {
        self.local_sdp.lock().expect("sdp").clone()
    }

    fn call<T>(&self, make: impl FnOnce(Reply<T>) -> Cmd) -> Result<T, Error> {
        let (reply_tx, reply_rx) = std::sync::mpsc::channel();
        self.cmd_tx
            .blocking_send(make(reply_tx))
            .map_err(|_| Error::Failed("peer stopped".into()))?;
        reply_rx
            .recv()
            .map_err(|_| Error::Failed("peer stopped".into()))?
    }
}

impl Default for Peer {
    fn default() -> Self {
        Self::new()
    }
}

impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.cancel_tx.send(true);
        if let Some(rt) = self.rt.lock().expect("runtime").take() {
            rt.shutdown_timeout(Duration::from_millis(800));
        }
    }
}

async fn worker(
    mut cmd_rx: mpsc::Receiver<Cmd>,
    incoming_tx: std::sync::mpsc::Sender<(u16, Vec<u8>)>,
    mut cancel_rx: watch::Receiver<bool>,
    stats: Arc<StatsInner>,
    local_sdp: Arc<Mutex<String>>,
    want_video: Arc<AtomicBool>,
) {
    let connect = wait_for_connect(&mut cmd_rx, &mut cancel_rx, &want_video).await;
    let Some((url, connect_reply)) = connect else {
        return;
    };
    let mut world = match setup(&url, &local_sdp, want_video.load(Ordering::SeqCst)).await {
        Ok(world) => world,
        Err(err) => {
            let _ = connect_reply.send(Err(err));
            return;
        }
    };
    let mut connect_wait = Some(ConnectWait {
        reply: connect_reply,
        started: Instant::now(),
    });
    let mut restart_wait: Option<RestartWait> = None;
    let mut send_job: Option<SendJob> = None;

    loop {
        if *cancel_rx.borrow() {
            break;
        }

        if let Some(side) = world.relay.as_mut()
            && let Err(err) = side.flush().await
        {
            spike_log(&format!("relay: {err}"));
            fail_waits(&mut connect_wait, &mut restart_wait, &mut send_job, err);
            break;
        }

        if let Err(err) = drain(&mut world, &incoming_tx).await {
            spike_log(&format!("drain: {err}"));
            fail_waits(&mut connect_wait, &mut restart_wait, &mut send_job, err);
            break;
        }

        let mut finished: Option<Result<(), Error>> = None;
        if let Some(job) = send_job.as_mut() {
            let status = pump_send(&mut world.rtc, &world.channels, job);
            stats
                .backpressure_pauses
                .store(job.gate.pauses, Ordering::Relaxed);
            finished = match status {
                Pump::Done => Some(Ok(())),
                Pump::Failed(err) => Some(Err(err)),
                Pump::Wait if job.started.elapsed() > send_limit() => Some(Err(Error::Timeout)),
                Pump::Wait => None,
            };
        }
        if let Err(err) = drain(&mut world, &incoming_tx).await {
            spike_log(&format!("drain: {err}"));
            fail_waits(&mut connect_wait, &mut restart_wait, &mut send_job, err);
            break;
        }
        if send_job.is_none()
            && let Err(err) = pump_video(&mut world, &stats)
        {
            spike_log(&format!("video: {err}"));
        }
        if let Err(err) = drain(&mut world, &incoming_tx).await {
            spike_log(&format!("drain: {err}"));
            fail_waits(&mut connect_wait, &mut restart_wait, &mut send_job, err);
            break;
        }
        if let Some(result) = finished {
            if let Some(job) = send_job.take() {
                let _ = job.reply.send(result);
            }
        }

        settle_connect(&mut connect_wait, &world, &stats);
        settle_restart(&mut restart_wait, &world, &stats);

        let sleep_for = Duration::from_millis(20);
        let tls_relay = world.tls_relay;
        tokio::select! {
            _ = cancel_rx.changed() => {
                if *cancel_rx.borrow() {
                    break;
                }
            }
            _ = tokio::time::sleep(sleep_for) => {
                if let Err(err) = world.rtc.handle_input(Input::Timeout(Instant::now())) {
                    spike_log(&format!("timeout input: {err}"));
                }
            }
            packet = world.sock.recv_from(&mut world.buf), if !tls_relay => {
                match packet {
                    Ok((size, source)) => {
                        let owned = world.buf[..size].to_vec();
                        if world.relay.is_some() {
                            let server = world.relay.as_ref().map(|side| side.server());
                            if server == Some(source)
                                && let Err(err) = take_relay(&mut world, &owned).await
                            {
                                spike_log(&format!("relay: {err}"));
                                fail_waits(
                                    &mut connect_wait,
                                    &mut restart_wait,
                                    &mut send_job,
                                    err,
                                );
                                break;
                            }
                        } else if let Err(err) = on_packet(&mut world, &owned, source) {
                            spike_log(&format!("packet: {err}"));
                        }
                    }
                    Err(err) => spike_log(&format!("udp: {err}")),
                }
            }
            frame = world.net_rx.recv(), if tls_relay => {
                match frame {
                    Some(frame) => {
                        if let Err(err) = take_relay(&mut world, &frame).await {
                            spike_log(&format!("relay: {err}"));
                            fail_waits(&mut connect_wait, &mut restart_wait, &mut send_job, err);
                            break;
                        }
                    }
                    None => {
                        fail_waits(
                            &mut connect_wait,
                            &mut restart_wait,
                            &mut send_job,
                            Error::Failed("relay tls failed".into()),
                        );
                        break;
                    }
                }
            }
            incoming = world.signal_rx.recv() => {
                let Some(text) = incoming else { break };
                if let Err(err) = on_signal(&mut world, &text, &local_sdp, restart_wait.as_mut()).await {
                    spike_log(&format!("signal: {err}"));
                }
            }
            cmd = cmd_rx.recv() => {
                let Some(cmd) = cmd else { break };
                on_cmd(cmd, &mut world, &local_sdp, &mut connect_wait, &mut restart_wait, &mut send_job);
            }
        }
    }
}

async fn wait_for_connect(
    cmd_rx: &mut mpsc::Receiver<Cmd>,
    cancel_rx: &mut watch::Receiver<bool>,
    want_video: &AtomicBool,
) -> Option<(String, Reply<()>)> {
    loop {
        tokio::select! {
            _ = cancel_rx.changed() => {
                if *cancel_rx.borrow() {
                    return None;
                }
            }
            cmd = cmd_rx.recv() => {
                match cmd {
                    Some(Cmd::Connect(url, reply)) => return Some((url, reply)),
                    Some(Cmd::Open(reply)) => {
                        let _ = reply.send(Err(Error::Failed("not connected".into())));
                    }
                    Some(Cmd::Send { reply, .. }) => {
                        let _ = reply.send(Err(Error::Failed("not connected".into())));
                    }
                    Some(Cmd::IceRestart(reply)) => {
                        let _ = reply.send(Err(Error::Failed("not connected".into())));
                    }
                    Some(Cmd::EnableVideo(reply)) => {
                        want_video.store(true, Ordering::SeqCst);
                        let _ = reply.send(Ok(()));
                    }
                    None => return None,
                }
            }
        }
    }
}

async fn setup(url: &str, local_sdp: &Arc<Mutex<String>>, video: bool) -> Result<World, Error> {
    let conn = signal::connect(url)
        .await
        .map_err(|err| Error::Failed(err.to_string()))?;
    let (role, signal_tx, signal_rx) = conn.into_split();
    let creds = relay::credentials()?;
    let (sock, relay, net_rx, tls_relay, candidate) = if let Some(creds) = creds {
        let bring = relay::allocate(creds).await?;
        let candidate =
            Candidate::relayed(bring.side.relayed(), bring.side.local(), "udp").map_err(failed)?;
        (
            bring.sock,
            Some(bring.side),
            bring.net_rx,
            bring.tls,
            candidate,
        )
    } else {
        let std_sock = std::net::UdpSocket::bind("127.0.0.1:0").map_err(failed)?;
        std_sock.set_nonblocking(true).map_err(failed)?;
        let sock = Arc::new(UdpSocket::from_std(std_sock).map_err(failed)?);
        let local_addr = sock.local_addr().map_err(failed)?;
        let (tx, net_rx) = mpsc::unbounded_channel();
        drop(tx);
        (
            sock,
            None,
            net_rx,
            false,
            Candidate::host(local_addr, "udp").map_err(failed)?,
        )
    };
    let local_addr = sock.local_addr().map_err(failed)?;
    // Both roles advertise constrained-baseline H.264. The video peer is not
    // always the signalling offerer, and an answer cannot add an m-line.
    let mut builder = Rtc::builder()
        .set_sctp_max_buffered_amount(SCTP_BUFFER)
        .clear_codecs();
    builder
        .codec_config()
        .add_h264(108.into(), Some(109.into()), true, 0x42e0_1f);
    let mut rtc = builder.build(Instant::now());
    let host = candidate;
    let candidate_sdp = rtc
        .add_local_candidate(host)
        .map(|candidate| candidate.to_sdp_string())
        .ok_or_else(|| Error::Failed("local candidate rejected".into()))?;

    let mut world = World {
        rtc,
        sock,
        local_addr,
        relay,
        net_rx,
        tls_relay,
        signal_tx,
        signal_rx,
        role,
        channels: Vec::new(),
        pending: None,
        candidate_sdp,
        buf: vec![0; 16 * 1024],
        video,
        video_mid: None,
        video_units: if video {
            video::h264_access_units().map_err(Error::Failed)?.to_vec()
        } else {
            Vec::new()
        },
        video_index: 0,
        video_next: Instant::now(),
        video_rtp: 0,
        video_ready: None,
    };

    if world.role == "offerer" {
        let mut change = world.rtc.sdp_api();
        for (id, label) in CHANNEL_SPECS {
            let channel_id = change.add_channel_with_config(channel_config(id, label));
            world.channels.push(Chan {
                our_id: id,
                label: label.to_owned(),
                id: channel_id,
                open: false,
            });
        }
        // str0m emits MediaAdded for a remote offer, not for media this
        // side added. The mid from add_media is the one writer() uses
        // after the answer is applied. The m-line is always in the offer;
        // frames are written only when this peer enabled the test pattern.
        let mid = change.add_media(
            MediaKind::Video,
            Direction::SendOnly,
            Some("spike".to_owned()),
            Some("pattern".to_owned()),
            None,
        );
        if world.video {
            world.video_mid = Some(mid);
        }
        let (offer, pending) = change
            .apply()
            .ok_or_else(|| Error::Failed("offer had no changes".into()))?;
        let sdp = offer.to_sdp_string();
        world.pending = Some(pending);
        *local_sdp.lock().expect("sdp") = sdp.clone();
        signal::queue(&world.signal_tx, &signal::Sig::Offer { sdp }).map_err(failed)?;
        send_candidate(&world, local_sdp)?;
    } else {
        send_candidate(&world, local_sdp)?;
    }
    Ok(world)
}

fn channel_config(id: u16, label: &str) -> ChannelConfig {
    ChannelConfig {
        label: label.to_owned(),
        ordered: true,
        reliability: Reliability::Reliable,
        negotiated: Some(id),
        protocol: String::new(),
    }
}

fn send_candidate(world: &World, local_sdp: &Arc<Mutex<String>>) -> Result<(), Error> {
    let sdp = local_sdp.lock().expect("sdp").clone();
    let mid = first_mid(&sdp);
    signal::queue(
        &world.signal_tx,
        &signal::Sig::Candidate {
            candidate: world.candidate_sdp.clone(),
            sdp_mid: mid,
            sdp_mline_index: Some(0),
        },
    )
    .map_err(failed)
}

fn first_mid(sdp: &str) -> Option<String> {
    sdp.lines()
        .find_map(|line| line.trim().strip_prefix("a=mid:"))
        .map(|mid| mid.trim().to_owned())
}

fn on_cmd(
    cmd: Cmd,
    world: &mut World,
    local_sdp: &Arc<Mutex<String>>,
    connect_wait: &mut Option<ConnectWait>,
    restart_wait: &mut Option<RestartWait>,
    send_job: &mut Option<SendJob>,
) {
    match cmd {
        Cmd::Connect(_, reply) => {
            let _ = reply.send(Err(Error::Failed("already connected".into())));
        }
        Cmd::Open(reply) => {
            if connect_wait.is_some() {
                let _ = reply.send(Err(Error::Failed("not connected".into())));
                return;
            }
            let _ = reply.send(Ok(world
                .channels
                .iter()
                .map(|channel| (channel.our_id, channel.label.clone()))
                .collect()));
        }
        Cmd::Send {
            channel,
            bytes,
            reply,
        } => {
            if send_job.is_some() {
                let _ = reply.send(Err(Error::Failed("send already in progress".into())));
                return;
            }
            let chunks = if channel == CHANNEL_FILES {
                chunk::chunk_blob(&bytes)
            } else {
                vec![bytes]
            };
            *send_job = Some(SendJob {
                reply,
                channel,
                chunks,
                index: 0,
                gate: PauseGate::new(),
                started: Instant::now(),
            });
        }
        Cmd::IceRestart(reply) => {
            if restart_wait.is_some() {
                let _ = reply.send(Err(Error::Failed("ice restart already in progress".into())));
                return;
            }
            let mut change = world.rtc.sdp_api();
            change.ice_restart(true);
            let Some((offer, pending)) = change.apply() else {
                let _ = reply.send(Err(Error::Failed("ice restart produced no offer".into())));
                return;
            };
            let sdp = offer.to_sdp_string();
            *local_sdp.lock().expect("sdp") = sdp.clone();
            if let Err(err) = signal::queue(&world.signal_tx, &signal::Sig::Offer { sdp }) {
                let _ = reply.send(Err(failed(err)));
                return;
            }
            let _ = send_candidate(world, local_sdp);
            *restart_wait = Some(RestartWait {
                reply,
                started: Instant::now(),
                pending: Some(pending),
                answer_applied: false,
                saw_down: !world.rtc.is_connected(),
            });
        }
        Cmd::EnableVideo(reply) => {
            let _ = reply.send(Err(Error::Failed("enable video before connect".into())));
        }
    }
}

async fn on_signal(
    world: &mut World,
    text: &str,
    local_sdp: &Arc<Mutex<String>>,
    mut restart: Option<&mut RestartWait>,
) -> Result<(), Error> {
    let message: signal::Sig = serde_json::from_str(text).map_err(failed)?;
    match message {
        signal::Sig::Offer { sdp } => {
            let offer = SdpOffer::from_sdp_string(&sdp).map_err(failed)?;
            let answer = world.rtc.sdp_api().accept_offer(offer).map_err(failed)?;
            if world.channels.is_empty() {
                for (id, label) in CHANNEL_SPECS {
                    let channel_id = world
                        .rtc
                        .direct_api()
                        .create_data_channel(channel_config(id, label));
                    world.channels.push(Chan {
                        our_id: id,
                        label: label.to_owned(),
                        id: channel_id,
                        open: false,
                    });
                }
            }
            let answer_sdp = answer.to_sdp_string();
            *local_sdp.lock().expect("sdp") = answer_sdp.clone();
            signal::queue(&world.signal_tx, &signal::Sig::Answer { sdp: answer_sdp })
                .map_err(failed)?;
            send_candidate(world, local_sdp)?;
        }
        signal::Sig::Answer { sdp } => {
            let answer = SdpAnswer::from_sdp_string(&sdp).map_err(failed)?;
            if let Some(restart) = restart.as_mut()
                && let Some(pending) = restart.pending.take()
            {
                world
                    .rtc
                    .sdp_api()
                    .accept_answer(pending, answer)
                    .map_err(failed)?;
                restart.answer_applied = true;
            } else if let Some(pending) = world.pending.take() {
                world
                    .rtc
                    .sdp_api()
                    .accept_answer(pending, answer)
                    .map_err(failed)?;
            }
        }
        signal::Sig::Candidate { candidate, .. } => {
            let line = candidate
                .trim()
                .strip_prefix("a=")
                .unwrap_or(candidate.trim());
            if line.is_empty() {
                return Ok(());
            }
            if world.relay.is_some() && !line.contains(" typ relay") {
                return Ok(());
            }
            match Candidate::from_sdp_string(line) {
                Ok(candidate) => {
                    if let Some(side) = world.relay.as_mut() {
                        side.permit(candidate.addr())?;
                        side.flush().await?;
                    }
                    world.rtc.add_remote_candidate(candidate);
                }
                Err(err) => spike_log(&format!("candidate: {err}")),
            }
        }
        _ => {}
    }
    Ok(())
}

fn on_packet(world: &mut World, packet: &[u8], source: SocketAddr) -> Result<(), Error> {
    let destination = world
        .relay
        .as_ref()
        .map(|side| side.relayed())
        .unwrap_or(world.local_addr);
    let received = Receive::new(Protocol::Udp, source, destination, packet).map_err(failed)?;
    world
        .rtc
        .handle_input(Input::Receive(Instant::now(), received))
        .map_err(failed)
}

async fn take_relay(world: &mut World, datagram: &[u8]) -> Result<(), Error> {
    let inbound = world
        .relay
        .as_mut()
        .ok_or_else(|| Error::Failed("relay allocation failed".into()))?
        .ingest(datagram)?;
    for (source, bytes) in inbound {
        on_packet(world, &bytes, source)?;
    }
    Ok(())
}

async fn drain(
    world: &mut World,
    incoming_tx: &std::sync::mpsc::Sender<(u16, Vec<u8>)>,
) -> Result<(), Error> {
    loop {
        match world.rtc.poll_output().map_err(failed)? {
            Output::Timeout(_) => return Ok(()),
            Output::Transmit(transmit) => {
                if world.relay.is_some() {
                    let dest = transmit.destination;
                    let bytes = transmit.contents.to_vec();
                    let side = world
                        .relay
                        .as_mut()
                        .ok_or_else(|| Error::Failed("relay allocation failed".into()))?;
                    side.send_payload(dest, &bytes)?;
                    side.flush().await?;
                } else {
                    world
                        .sock
                        .send_to(&transmit.contents, transmit.destination)
                        .await
                        .map_err(failed)?;
                }
            }
            Output::Event(event) => {
                if let Event::MediaAdded(added) = &event
                    && world.video
                    && added.kind == MediaKind::Video
                    && added.direction.is_sending()
                {
                    world.video_mid = Some(added.mid);
                }
                on_event(&mut world.channels, incoming_tx, event);
            }
        }
    }
}

fn on_event(
    channels: &mut [Chan],
    incoming_tx: &std::sync::mpsc::Sender<(u16, Vec<u8>)>,
    event: Event,
) {
    match event {
        Event::ChannelOpen(id, label) => {
            if let Some(channel) = channels.iter_mut().find(|channel| channel.id == id) {
                channel.open = true;
            } else if let Some(channel) = channels.iter_mut().find(|channel| channel.label == label)
            {
                channel.id = id;
                channel.open = true;
            }
        }
        Event::ChannelData(data) => {
            if let Some(channel) = channels.iter().find(|channel| channel.id == data.id) {
                let _ = incoming_tx.send((channel.our_id, data.data));
            }
        }
        other => {
            if std::env::var_os("SPIKE_DEBUG").is_some() {
                spike_log(&format!("event {other:?}"));
            }
        }
    }
}

enum Pump {
    Wait,
    Done,
    Failed(Error),
}

fn pump_send(rtc: &mut Rtc, channels: &[Chan], job: &mut SendJob) -> Pump {
    let Some(channel) = channels
        .iter()
        .find(|channel| channel.our_id == job.channel)
    else {
        return Pump::Failed(Error::Failed(format!("unknown channel {}", job.channel)));
    };
    if !channel.open {
        return Pump::Wait;
    }
    let id = channel.id;
    loop {
        let buffered = match rtc.channel(id) {
            Some(mut channel) => channel.buffered_amount(),
            None => return Pump::Wait,
        };
        if job.gate.observe(buffered) {
            return Pump::Wait;
        }
        if job.index >= job.chunks.len() {
            return Pump::Done;
        }
        let accepted = match rtc.channel(id) {
            Some(mut channel) => match channel.write(true, &job.chunks[job.index]) {
                Ok(accepted) => accepted,
                Err(err) => return Pump::Failed(failed(err)),
            },
            None => return Pump::Wait,
        };
        if !accepted {
            return Pump::Wait;
        }
        job.index += 1;
    }
}

fn settle_connect(wait: &mut Option<ConnectWait>, world: &World, stats: &StatsInner) {
    let Some(pending) = wait.as_ref() else {
        return;
    };
    if pending.started.elapsed() > connect_limit() {
        if let Some(pending) = wait.take() {
            let _ = pending.reply.send(Err(Error::Timeout));
        }
        return;
    }
    let open = !world.channels.is_empty() && world.channels.iter().all(|channel| channel.open);
    if world.rtc.is_connected() && open {
        stats
            .connect_ms
            .store(elapsed_ms(pending.started), Ordering::Relaxed);
        if let Some(pending) = wait.take() {
            let _ = pending.reply.send(Ok(()));
        }
    }
}

fn settle_restart(wait: &mut Option<RestartWait>, world: &World, stats: &StatsInner) {
    let Some(pending) = wait.as_mut() else {
        return;
    };
    if pending.started.elapsed() > restart_limit() {
        if let Some(pending) = wait.take() {
            let _ = pending.reply.send(Err(Error::Timeout));
        }
        return;
    }
    if !pending.answer_applied {
        return;
    }
    if !world.rtc.is_connected() {
        pending.saw_down = true;
        return;
    }
    let rpc_open = world
        .channels
        .iter()
        .any(|channel| channel.our_id == 0 && channel.open);
    if pending.saw_down || pending.started.elapsed() > Duration::from_millis(200) {
        if rpc_open {
            stats
                .ice_restart_ms
                .store(elapsed_ms(pending.started), Ordering::Relaxed);
            if let Some(pending) = wait.take() {
                let _ = pending.reply.send(Ok(()));
            }
        }
    }
}

fn fail_waits(
    connect_wait: &mut Option<ConnectWait>,
    restart_wait: &mut Option<RestartWait>,
    send_job: &mut Option<SendJob>,
    err: Error,
) {
    if let Some(wait) = connect_wait.take() {
        let _ = wait.reply.send(Err(Error::Failed(err.to_string())));
    }
    if let Some(wait) = restart_wait.take() {
        let _ = wait.reply.send(Err(Error::Failed(err.to_string())));
    }
    if let Some(job) = send_job.take() {
        let _ = job.reply.send(Err(err));
    }
}

fn pump_video(world: &mut World, stats: &StatsInner) -> Result<(), Error> {
    if !world.video || world.video_units.is_empty() || !world.rtc.is_connected() {
        return Ok(());
    }
    let Some(mid) = world.video_mid else {
        return Ok(());
    };
    let now = Instant::now();
    if now < world.video_next {
        return Ok(());
    }
    let ready = *world.video_ready.get_or_insert(now);
    let pt = {
        let writer = world
            .rtc
            .writer(mid)
            .ok_or_else(|| Error::Failed("video writer missing".into()))?;
        writer
            .payload_params()
            .find(|params| {
                let spec = params.spec();
                spec.codec == Codec::H264
                    && spec.format.profile_level_id == Some(0x42e0_1f)
                    && spec.format.packetization_mode == Some(1)
            })
            .map(|params| params.pt())
            .ok_or_else(|| Error::Failed("no H264 42e01f payload type".into()))?
    };
    let frame = world.video_units[world.video_index].clone();
    world
        .rtc
        .writer(mid)
        .ok_or_else(|| Error::Failed("video writer missing".into()))?
        .write(pt, now, MediaTime::from_90khz(world.video_rtp), frame)
        .map_err(failed)?;
    let ms = elapsed_ms(ready).max(1);
    let _ = stats
        .first_frame_ms
        .compare_exchange(0, ms, Ordering::Relaxed, Ordering::Relaxed);
    world.video_index = (world.video_index + 1) % world.video_units.len();
    world.video_rtp = world.video_rtp.wrapping_add(3_000);
    world.video_next = now + Duration::from_millis(33);
    Ok(())
}

fn relay_requested() -> bool {
    std::env::var("SPIKE_TURN_URL")
        .ok()
        .is_some_and(|value| !value.is_empty())
}

fn connect_limit() -> Duration {
    if relay_requested() {
        Duration::from_secs(45)
    } else {
        CONNECT_TIMEOUT
    }
}

fn restart_limit() -> Duration {
    if relay_requested() {
        Duration::from_secs(20)
    } else {
        RESTART_TIMEOUT
    }
}

fn send_limit() -> Duration {
    if relay_requested() {
        Duration::from_secs(180)
    } else {
        SEND_TIMEOUT
    }
}

fn elapsed_ms(start: Instant) -> u64 {
    let elapsed = start.elapsed();
    let ms = u64::try_from(elapsed.as_millis()).unwrap_or(u64::MAX);
    if ms == 0 && !elapsed.is_zero() { 1 } else { ms }
}

fn failed(err: impl fmt::Display) -> Error {
    Error::Failed(err.to_string())
}

fn spike_log(message: &str) {
    if std::env::var_os("SPIKE_DEBUG").is_some() {
        eprintln!("spike-str0m: {message}");
    }
}
