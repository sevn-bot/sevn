//! webrtc-rs peer (`webrtc` 0.21.1). Synchronous [`Peer`] methods drive a tokio worker.

use std::fmt;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use bytes::BytesMut;
use rtc::media::Sample;
use rtc::media_stream::MediaStreamTrack;
use rtc::peer_connection::configuration::media_engine::{MIME_TYPE_H264, MediaEngine};
use rtc::rtp_transceiver::rtp_sender::{
    RTCRtpCodec, RTCRtpCodecParameters, RTCRtpCodingParameters, RTCRtpEncodingParameters,
    RtpCodecKind,
};
use tokio::sync::{Notify, mpsc, watch};
use webrtc::data_channel::{DataChannel, DataChannelEvent, RTCDataChannelInit};
use webrtc::media_stream::track_local::TrackLocal;
use webrtc::media_stream::track_local::static_sample::TrackLocalStaticSample;
use webrtc::peer_connection::{
    PeerConnection, PeerConnectionBuilder, PeerConnectionEventHandler, RTCConfigurationBuilder,
    RTCIceCandidateInit, RTCIceGatheringState, RTCIceServer, RTCIceTransportPolicy,
    RTCPeerConnectionIceEvent, RTCPeerConnectionState, RTCSessionDescription,
};
use webrtc::rtp_transceiver::RtpSender;
use webrtc::runtime::TokioRuntime;

#[path = "../../common/src/chunk.rs"]
mod chunk;
#[path = "../../common/src/video.rs"]
mod video;

use chunk::{CHANNEL_FILES, CHANNEL_SPECS, PAUSE_ABOVE_BUFFERED, PauseGate, RESUME_BELOW_BUFFERED};

const VIDEO_SSRC: u32 = 0x0002_51D0;
const FRAME: Duration = Duration::from_millis(33);

const CONNECT_TIMEOUT: Duration = Duration::from_secs(20);
const RESTART_TIMEOUT: Duration = Duration::from_secs(4);
const OPEN_TIMEOUT: Duration = Duration::from_secs(10);

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

enum Cmd {
    Connect(String, std::sync::mpsc::Sender<Result<(), Error>>),
    Open(std::sync::mpsc::Sender<Result<Vec<(u16, String)>, Error>>),
    Send {
        channel: u16,
        bytes: Vec<u8>,
        reply: std::sync::mpsc::Sender<Result<(), Error>>,
    },
    IceRestart(std::sync::mpsc::Sender<Result<(), Error>>),
    EnableVideo(std::sync::mpsc::Sender<Result<(), Error>>),
}

struct Slot {
    id: u16,
    label: String,
    dc: Arc<dyn DataChannel>,
    open: Arc<AtomicBool>,
    opened: Arc<Notify>,
}

pub struct Peer {
    rt: Mutex<Option<tokio::runtime::Runtime>>,
    cmd_tx: mpsc::Sender<Cmd>,
    incoming_rx: Mutex<std::sync::mpsc::Receiver<(u16, Vec<u8>)>>,
    cancel_tx: watch::Sender<bool>,
    stats: Arc<StatsInner>,
    local_sdp: Arc<Mutex<String>>,
    browser_joined: Arc<Mutex<Option<Arc<AtomicBool>>>>,
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
        let browser_joined = Arc::new(Mutex::new(None));
        rt.spawn(worker(
            cmd_rx,
            incoming_tx,
            cancel_rx,
            Arc::clone(&stats),
            Arc::clone(&local_sdp),
            want_video,
            Arc::clone(&browser_joined),
        ));
        Self {
            rt: Mutex::new(Some(rt)),
            cmd_tx,
            incoming_rx: Mutex::new(incoming_rx),
            cancel_tx,
            stats,
            local_sdp,
            browser_joined,
        }
    }

    /// The connect deadline starts once `joined` is true, not at `connect`.
    pub fn defer_connect_deadline(&self, joined: Arc<AtomicBool>) {
        *self.browser_joined.lock().expect("browser joined") = Some(joined);
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

    fn call<T>(
        &self,
        make: impl FnOnce(std::sync::mpsc::Sender<Result<T, Error>>) -> Cmd,
    ) -> Result<T, Error> {
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

struct GatherWatch {
    saw_relay: AtomicBool,
    saw_other: AtomicBool,
    done: AtomicBool,
}

struct Handler {
    state_tx: watch::Sender<RTCPeerConnectionState>,
    connected_gen: Arc<AtomicU64>,
    signal_tx: mpsc::UnboundedSender<String>,
    gather: Option<Arc<GatherWatch>>,
}

#[async_trait]
impl PeerConnectionEventHandler for Handler {
    async fn on_ice_candidate(&self, event: RTCPeerConnectionIceEvent) {
        let Ok(init) = event.candidate.to_json() else {
            return;
        };
        if init.candidate.is_empty() {
            return;
        }
        if let Some(gather) = &self.gather {
            if init.candidate.contains(" typ relay") {
                gather.saw_relay.store(true, Ordering::SeqCst);
            } else {
                gather.saw_other.store(true, Ordering::SeqCst);
                return;
            }
        }
        let _ = signal::queue(
            &self.signal_tx,
            &signal::Sig::Candidate {
                candidate: init.candidate,
                sdp_mid: init.sdp_mid,
                sdp_mline_index: init.sdp_mline_index,
            },
        );
    }

    async fn on_ice_gathering_state_change(&self, state: RTCIceGatheringState) {
        if state == RTCIceGatheringState::Complete
            && let Some(gather) = &self.gather
        {
            gather.done.store(true, Ordering::SeqCst);
        }
    }

    async fn on_connection_state_change(&self, state: RTCPeerConnectionState) {
        if state == RTCPeerConnectionState::Connected {
            self.connected_gen.fetch_add(1, Ordering::SeqCst);
        }
        let _ = self.state_tx.send(state);
    }
}

struct Session {
    pc: Arc<dyn PeerConnection>,
    slots: Vec<Slot>,
    signal_tx: mpsc::UnboundedSender<String>,
    state_rx: watch::Receiver<RTCPeerConnectionState>,
    connected_gen: Arc<AtomicU64>,
    answer_gen: Arc<AtomicU64>,
    relay: bool,
    gather: Option<Arc<GatherWatch>>,
}

async fn worker(
    mut cmd_rx: mpsc::Receiver<Cmd>,
    incoming_tx: std::sync::mpsc::Sender<(u16, Vec<u8>)>,
    mut cancel_rx: watch::Receiver<bool>,
    stats: Arc<StatsInner>,
    local_sdp: Arc<Mutex<String>>,
    want_video: Arc<AtomicBool>,
    browser_joined: Arc<Mutex<Option<Arc<AtomicBool>>>>,
) {
    let mut session: Option<Session> = None;
    loop {
        tokio::select! {
            _ = cancel_rx.changed() => {
                if *cancel_rx.borrow() {
                    break;
                }
            }
            cmd = cmd_rx.recv() => {
                let Some(cmd) = cmd else { break };
                if *cancel_rx.borrow() {
                    break;
                }
                match cmd {
                    Cmd::Connect(url, reply) => {
                        let joined = browser_joined.lock().expect("browser joined").clone();
                        let result = connect_session(
                            &url,
                            &incoming_tx,
                            &local_sdp,
                            &stats,
                            want_video.load(Ordering::SeqCst),
                            joined,
                        )
                        .await;
                        match result {
                            Ok(ready) => {
                                stats.connect_ms.store(ready.connect_ms, Ordering::Relaxed);
                                session = Some(ready.session);
                                let _ = reply.send(Ok(()));
                            }
                            Err(err) => {
                                let _ = reply.send(Err(err));
                            }
                        }
                    }
                    Cmd::Open(reply) => {
                        let result = session.as_ref().map(|session| {
                            session
                                .slots
                                .iter()
                                .map(|slot| (slot.id, slot.label.clone()))
                                .collect()
                        });
                        let _ = reply.send(result.ok_or_else(|| Error::Failed("not connected".into())));
                    }
                    Cmd::Send { channel, bytes, reply } => {
                        let result = match session.as_ref() {
                            Some(session) => send_on(session, channel, &bytes, &stats).await,
                            None => Err(Error::Failed("not connected".into())),
                        };
                        let _ = reply.send(result);
                    }
                    Cmd::IceRestart(reply) => {
                        let result = match session.as_ref() {
                            Some(session) => ice_restart(session, &local_sdp).await,
                            None => Err(Error::Failed("not connected".into())),
                        };
                        if let Ok(ms) = result {
                            stats.ice_restart_ms.store(ms, Ordering::Relaxed);
                            let _ = reply.send(Ok(()));
                        } else {
                            let _ = reply.send(result.map(|_| ()));
                        }
                    }
                    Cmd::EnableVideo(reply) => {
                        want_video.store(true, Ordering::SeqCst);
                        let _ = reply.send(Ok(()));
                    }
                }
            }
        }
    }
}

struct Connected {
    session: Session,
    connect_ms: u64,
}

async fn connect_session(
    url: &str,
    incoming_tx: &std::sync::mpsc::Sender<(u16, Vec<u8>)>,
    local_sdp: &Arc<Mutex<String>>,
    stats: &Arc<StatsInner>,
    want_video: bool,
    browser_joined: Option<Arc<AtomicBool>>,
) -> Result<Connected, Error> {
    let started = Instant::now();
    let conn = signal::connect(url)
        .await
        .map_err(|err| Error::Failed(err.to_string()))?;
    let (role, signal_tx, mut signal_rx) = conn.into_split();
    let (state_tx, state_rx) = watch::channel(RTCPeerConnectionState::New);
    let connected_gen = Arc::new(AtomicU64::new(0));
    let answer_gen = Arc::new(AtomicU64::new(0));

    let mut media_engine = MediaEngine::default();
    media_engine
        .register_codec(h264_codec(), RtpCodecKind::Video)
        .map_err(|err| Error::Failed(err.to_string()))?;
    let relay = relay_config()?;
    let relay_on = relay.is_some();
    let gather = relay_on.then(|| {
        Arc::new(GatherWatch {
            saw_relay: AtomicBool::new(false),
            saw_other: AtomicBool::new(false),
            done: AtomicBool::new(false),
        })
    });
    let (configuration, udp_addrs) = if let Some((url, username, credential)) = relay {
        (
            RTCConfigurationBuilder::new()
                .with_ice_servers(vec![RTCIceServer {
                    urls: vec![url],
                    username,
                    credential,
                }])
                .with_ice_transport_policy(RTCIceTransportPolicy::Relay)
                .build(),
            vec!["0.0.0.0:0".to_string()],
        )
    } else {
        (
            RTCConfigurationBuilder::new().build(),
            vec!["127.0.0.1:0".to_string()],
        )
    };
    let pc = PeerConnectionBuilder::new()
        .with_configuration(configuration)
        .with_media_engine(media_engine)
        .with_handler(Arc::new(Handler {
            state_tx,
            connected_gen: Arc::clone(&connected_gen),
            signal_tx: signal_tx.clone(),
            gather: gather.clone(),
        }))
        .with_runtime(Arc::new(TokioRuntime))
        .with_udp_addrs(udp_addrs)
        .with_data_channel_send_buffer_limit(4 * 1024 * 1024)
        .build()
        .await
        .map_err(|err| Error::Failed(err.to_string()))?;
    let pc: Arc<dyn PeerConnection> = Arc::new(pc);
    // Every peer offers the H.264 m-line. The harness starts both connects
    // together, so the peer that called enable_test_video is not always the
    // signalling offerer; an answer cannot add an m-line the offer omitted.
    let added = add_video_track(&pc).await?;
    let video_sender = if want_video { Some(added) } else { None };

    let mut slots = Vec::with_capacity(CHANNEL_SPECS.len());
    for (id, label) in CHANNEL_SPECS {
        let dc = pc
            .create_data_channel(
                label,
                Some(RTCDataChannelInit {
                    ordered: true,
                    negotiated: Some(id),
                    ..Default::default()
                }),
            )
            .await
            .map_err(|err| Error::Failed(err.to_string()))?;
        let open = Arc::new(AtomicBool::new(false));
        let opened = Arc::new(Notify::new());
        spawn_reader(
            Arc::clone(&dc),
            id,
            Arc::clone(&open),
            Arc::clone(&opened),
            incoming_tx.clone(),
        );
        slots.push(Slot {
            id,
            label: label.to_owned(),
            dc,
            open,
            opened,
        });
    }

    let pc_reader = Arc::clone(&pc);
    let local_reader = Arc::clone(local_sdp);
    let answer_gen_reader = Arc::clone(&answer_gen);
    let answer_tx = signal_tx.clone();
    tokio::spawn(async move {
        if let Err(err) = signal_loop(
            &mut signal_rx,
            pc_reader,
            local_reader,
            answer_gen_reader,
            answer_tx,
        )
        .await
        {
            spike_log(&format!("signal loop: {err}"));
        }
    });

    if role == "offerer" {
        let offer = pc
            .create_offer(None)
            .await
            .map_err(|err| Error::Failed(err.to_string()))?;
        pc.set_local_description(offer)
            .await
            .map_err(|err| Error::Failed(err.to_string()))?;
        let local = pc
            .local_description()
            .await
            .ok_or_else(|| Error::Failed("missing local description".into()))?;
        *local_sdp.lock().expect("sdp") = local.sdp.clone();
        signal::queue(&signal_tx, &signal::Sig::Offer { sdp: local.sdp })
            .map_err(|err| Error::Failed(err.to_string()))?;
    }

    let mut state_rx = state_rx;
    let armed = wait_connected(
        &mut state_rx,
        connect_limit(),
        gather.as_deref(),
        browser_joined.as_ref(),
    )
    .await?;
    // PC Connected can precede SCTP OnOpen. A send in that gap is dropped by
    // the stack, so connect does not return until every negotiated channel is open.
    for slot in &slots {
        wait_open(&slot.open, &slot.opened).await?;
    }
    if let Some((track, sender)) = video_sender {
        let payload_type = negotiated_payload_type(&sender).await?;
        let stats = Arc::clone(stats);
        tokio::spawn(async move {
            if let Err(err) = send_pattern(track, payload_type, stats).await {
                spike_log(&format!("video: {err}"));
            }
        });
    }
    Ok(Connected {
        session: Session {
            pc,
            slots,
            signal_tx,
            state_rx,
            connected_gen,
            answer_gen,
            relay: relay_on,
            gather,
        },
        connect_ms: elapsed_ms(if browser_joined.is_some() {
            armed
        } else {
            started
        }),
    })
}

fn spawn_reader(
    dc: Arc<dyn DataChannel>,
    id: u16,
    open: Arc<AtomicBool>,
    opened: Arc<Notify>,
    incoming_tx: std::sync::mpsc::Sender<(u16, Vec<u8>)>,
) {
    tokio::spawn(async move {
        let _ = dc
            .set_buffered_amount_low_threshold(RESUME_BELOW_BUFFERED.saturating_sub(1) as u32)
            .await;
        let _ = dc
            .set_buffered_amount_high_threshold(PAUSE_ABOVE_BUFFERED.saturating_add(1) as u32)
            .await;
        while let Some(event) = dc.poll().await {
            match event {
                DataChannelEvent::OnOpen => {
                    open.store(true, Ordering::SeqCst);
                    opened.notify_waiters();
                }
                DataChannelEvent::OnMessage(message) => {
                    let _ = incoming_tx.send((id, message.data.to_vec()));
                }
                DataChannelEvent::OnClose => break,
                _ => {}
            }
        }
    });
}

async fn signal_loop(
    signal_rx: &mut mpsc::UnboundedReceiver<String>,
    pc: Arc<dyn PeerConnection>,
    local_sdp: Arc<Mutex<String>>,
    answer_gen: Arc<AtomicU64>,
    signal_tx: mpsc::UnboundedSender<String>,
) -> Result<(), Error> {
    let mut have_remote = false;
    let mut pending = Vec::new();
    while let Some(text) = signal_rx.recv().await {
        let message: signal::Sig = match serde_json::from_str(&text) {
            Ok(message) => message,
            Err(err) => {
                spike_log(&format!("bad signal json: {err}"));
                continue;
            }
        };
        match message {
            signal::Sig::Answer { sdp } => {
                let description = RTCSessionDescription::answer(sdp)
                    .map_err(|err| Error::Failed(err.to_string()))?;
                pc.set_remote_description(description)
                    .await
                    .map_err(|err| Error::Failed(err.to_string()))?;
                have_remote = true;
                answer_gen.fetch_add(1, Ordering::SeqCst);
                flush_candidates(&pc, &mut pending).await?;
            }
            signal::Sig::Offer { sdp } => {
                let description = RTCSessionDescription::offer(sdp)
                    .map_err(|err| Error::Failed(err.to_string()))?;
                pc.set_remote_description(description)
                    .await
                    .map_err(|err| Error::Failed(err.to_string()))?;
                have_remote = true;
                flush_candidates(&pc, &mut pending).await?;
                let answer = pc
                    .create_answer(None)
                    .await
                    .map_err(|err| Error::Failed(err.to_string()))?;
                pc.set_local_description(answer)
                    .await
                    .map_err(|err| Error::Failed(err.to_string()))?;
                if let Some(local) = pc.local_description().await {
                    *local_sdp.lock().expect("sdp") = local.sdp.clone();
                    signal::queue(&signal_tx, &signal::Sig::Answer { sdp: local.sdp })
                        .map_err(|err| Error::Failed(err.to_string()))?;
                }
            }
            signal::Sig::Candidate {
                candidate,
                sdp_mid,
                sdp_mline_index,
            } => {
                if candidate.is_empty() {
                    continue;
                }
                let init = RTCIceCandidateInit {
                    candidate,
                    sdp_mid,
                    sdp_mline_index,
                    username_fragment: None,
                    url: None,
                };
                if have_remote {
                    add_candidate(&pc, init).await?;
                } else {
                    pending.push(init);
                }
            }
            _ => {}
        }
    }
    Ok(())
}

async fn flush_candidates(
    pc: &Arc<dyn PeerConnection>,
    pending: &mut Vec<RTCIceCandidateInit>,
) -> Result<(), Error> {
    for init in pending.drain(..) {
        add_candidate(pc, init).await?;
    }
    Ok(())
}

async fn add_candidate(
    pc: &Arc<dyn PeerConnection>,
    init: RTCIceCandidateInit,
) -> Result<(), Error> {
    pc.add_ice_candidate(init)
        .await
        .map_err(|err| Error::Failed(err.to_string()))
}

fn relay_config() -> Result<Option<(String, String, String)>, Error> {
    let Ok(url) = std::env::var("SPIKE_TURN_URL") else {
        return Ok(None);
    };
    if url.is_empty() {
        return Ok(None);
    }
    let username = std::env::var("SPIKE_TURN_USERNAME").unwrap_or_default();
    let credential = std::env::var("SPIKE_TURN_CREDENTIAL").unwrap_or_default();
    if username.is_empty() || credential.is_empty() {
        return Err(Error::Failed("relay measurement env is unset".into()));
    }
    Ok(Some((url, username, credential)))
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

fn open_limit() -> Duration {
    if relay_requested() {
        Duration::from_secs(20)
    } else {
        OPEN_TIMEOUT
    }
}

async fn wait_connected(
    state_rx: &mut watch::Receiver<RTCPeerConnectionState>,
    timeout: Duration,
    gather: Option<&GatherWatch>,
    browser_joined: Option<&Arc<AtomicBool>>,
) -> Result<Instant, Error> {
    let mut armed = if browser_joined.is_some() {
        None
    } else {
        Some(Instant::now())
    };
    loop {
        if armed.is_none() {
            let ready = browser_joined.is_some_and(|flag| flag.load(Ordering::SeqCst));
            if !ready {
                let _ = tokio::time::timeout(Duration::from_millis(100), state_rx.changed()).await;
                continue;
            }
            armed = Some(Instant::now());
        }
        let started = armed.expect("deadline armed");
        let deadline = started + timeout;
        if let Some(gather) = gather {
            if gather.saw_other.load(Ordering::SeqCst) {
                return Err(Error::Failed("non-relay candidate gathered".into()));
            }
            if gather.done.load(Ordering::SeqCst) && !gather.saw_relay.load(Ordering::SeqCst) {
                return Err(Error::Failed("no relay candidate".into()));
            }
        }
        let state = *state_rx.borrow();
        if state == RTCPeerConnectionState::Connected {
            if let Some(gather) = gather
                && !gather.saw_relay.load(Ordering::SeqCst)
            {
                return Err(Error::Failed("no relay candidate".into()));
            }
            return Ok(started);
        }
        if state == RTCPeerConnectionState::Failed || state == RTCPeerConnectionState::Closed {
            return Err(Error::Failed(format!("connection {state}")));
        }
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            if gather.is_some() {
                return Err(Error::Failed("no relay candidate".into()));
            }
            return Err(Error::Timeout);
        }
        let _ =
            tokio::time::timeout(left.min(Duration::from_millis(100)), state_rx.changed()).await;
    }
}

async fn send_on(
    session: &Session,
    channel: u16,
    bytes: &[u8],
    stats: &StatsInner,
) -> Result<(), Error> {
    let slot = session
        .slots
        .iter()
        .find(|slot| slot.id == channel)
        .ok_or_else(|| Error::Failed(format!("unknown channel {channel}")))?;
    wait_open(&slot.open, &slot.opened).await?;
    if channel == CHANNEL_FILES {
        let chunks = chunk::chunk_blob(bytes);
        let mut gate = PauseGate::new();
        let started = Instant::now();
        for chunk in chunks {
            loop {
                if relay_requested() && started.elapsed() > Duration::from_secs(180) {
                    return Err(Error::Timeout);
                }
                let outstanding = slot
                    .dc
                    .outstanding_bytes()
                    .await
                    .map_err(|err| Error::Failed(err.to_string()))?;
                if !gate.observe(outstanding) {
                    break;
                }
                stats
                    .backpressure_pauses
                    .store(gate.pauses, Ordering::Relaxed);
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
            slot.dc
                .send(BytesMut::from(chunk.as_slice()))
                .await
                .map_err(|err| Error::Failed(err.to_string()))?;
        }
        stats
            .backpressure_pauses
            .store(gate.pauses, Ordering::Relaxed);
    } else {
        slot.dc
            .send(BytesMut::from(bytes))
            .await
            .map_err(|err| Error::Failed(err.to_string()))?;
    }
    Ok(())
}

async fn wait_open(open: &AtomicBool, opened: &Notify) -> Result<(), Error> {
    let deadline = Instant::now() + open_limit();
    loop {
        if open.load(Ordering::SeqCst) {
            return Ok(());
        }
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return Err(Error::Timeout);
        }
        let _ = tokio::time::timeout(left.min(Duration::from_millis(50)), opened.notified()).await;
    }
}

async fn ice_restart(session: &Session, local_sdp: &Arc<Mutex<String>>) -> Result<u64, Error> {
    let started = Instant::now();
    let before_connected = session.connected_gen.load(Ordering::SeqCst);
    let before_answer = session.answer_gen.load(Ordering::SeqCst);
    session
        .pc
        .restart_ice()
        .await
        .map_err(|err| Error::Failed(err.to_string()))?;
    let offer = session
        .pc
        .create_offer(None)
        .await
        .map_err(|err| Error::Failed(err.to_string()))?;
    session
        .pc
        .set_local_description(offer)
        .await
        .map_err(|err| Error::Failed(err.to_string()))?;
    let local = session
        .pc
        .local_description()
        .await
        .ok_or_else(|| Error::Failed("missing local description".into()))?;
    *local_sdp.lock().expect("sdp") = local.sdp.clone();
    signal::queue(&session.signal_tx, &signal::Sig::Offer { sdp: local.sdp })
        .map_err(|err| Error::Failed(err.to_string()))?;

    let mut state_rx = session.state_rx.clone();
    let timeout = if session.relay {
        Duration::from_secs(20)
    } else {
        RESTART_TIMEOUT
    };
    let deadline = Instant::now() + timeout;
    loop {
        if let Some(gather) = &session.gather
            && gather.saw_other.load(Ordering::SeqCst)
        {
            return Err(Error::Failed("non-relay candidate gathered".into()));
        }
        let answered = session.answer_gen.load(Ordering::SeqCst) > before_answer;
        let state = *state_rx.borrow();
        let reconnected = session.connected_gen.load(Ordering::SeqCst) > before_connected;
        if answered
            && state == RTCPeerConnectionState::Connected
            && (reconnected || started.elapsed() > Duration::from_millis(50))
        {
            return Ok(elapsed_ms(started));
        }
        if state == RTCPeerConnectionState::Failed || state == RTCPeerConnectionState::Closed {
            return Err(Error::Failed(format!("ice restart {state}")));
        }
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return Err(Error::Timeout);
        }
        let _ =
            tokio::time::timeout(left.min(Duration::from_millis(100)), state_rx.changed()).await;
    }
}

fn h264_codec() -> RTCRtpCodecParameters {
    RTCRtpCodecParameters {
        rtp_codec: RTCRtpCodec {
            mime_type: MIME_TYPE_H264.to_owned(),
            clock_rate: 90_000,
            channels: 0,
            sdp_fmtp_line: "level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f"
                .to_owned(),
            rtcp_feedback: vec![],
        },
        payload_type: 102,
    }
}

async fn add_video_track(
    pc: &Arc<dyn PeerConnection>,
) -> Result<(Arc<TrackLocalStaticSample>, Arc<dyn RtpSender>), Error> {
    let codec = h264_codec();
    let track = Arc::new(
        TrackLocalStaticSample::new(
            Instant::now(),
            MediaStreamTrack::new(
                "spike-video".to_owned(),
                "pattern".to_owned(),
                "test-pattern".to_owned(),
                RtpCodecKind::Video,
                vec![RTCRtpEncodingParameters {
                    rtp_coding_parameters: RTCRtpCodingParameters {
                        ssrc: Some(VIDEO_SSRC),
                        ..Default::default()
                    },
                    codec: codec.rtp_codec,
                    ..Default::default()
                }],
            ),
        )
        .map_err(|err| Error::Failed(err.to_string()))?,
    );
    let sender = pc
        .add_track(Arc::clone(&track) as Arc<dyn TrackLocal>)
        .await
        .map_err(|err| Error::Failed(err.to_string()))?;
    Ok((track, sender))
}

async fn negotiated_payload_type(sender: &Arc<dyn RtpSender>) -> Result<u8, Error> {
    sender
        .get_parameters()
        .await
        .map_err(|err| Error::Failed(err.to_string()))?
        .rtp_parameters
        .codecs
        .first()
        .map(|codec| codec.payload_type)
        .ok_or_else(|| Error::Failed("no negotiated video codec".into()))
}

async fn send_pattern(
    track: Arc<TrackLocalStaticSample>,
    payload_type: u8,
    stats: Arc<StatsInner>,
) -> Result<(), Error> {
    let units = video::h264_access_units().map_err(Error::Failed)?;
    let started = Instant::now();
    let mut index = 0_usize;
    loop {
        let sample = Sample {
            data: bytes::Bytes::copy_from_slice(&units[index]),
            duration: FRAME,
            ..Sample::new(Instant::now())
        };
        track
            .sample_writer(VIDEO_SSRC, payload_type)
            .write_sample(&sample)
            .await
            .map_err(|err| Error::Failed(err.to_string()))?;
        let ms = elapsed_ms(started);
        let _ = stats.first_frame_ms.compare_exchange(
            0,
            ms.max(1),
            Ordering::Relaxed,
            Ordering::Relaxed,
        );
        index = (index + 1) % units.len();
        tokio::time::sleep(FRAME).await;
    }
}

fn elapsed_ms(start: Instant) -> u64 {
    let elapsed = start.elapsed();
    let ms = elapsed.as_millis() as u64;
    if ms == 0 && !elapsed.is_zero() { 1 } else { ms }
}

fn spike_log(message: &str) {
    if std::env::var_os("SPIKE_DEBUG").is_some() {
        eprintln!("spike-webrtcrs: {message}");
    }
}
