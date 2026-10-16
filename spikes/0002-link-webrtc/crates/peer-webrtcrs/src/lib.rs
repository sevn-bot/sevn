//! webrtc-rs peer (`webrtc` 0.21.1). Synchronous [`Peer`] methods drive a tokio worker.

use std::fmt;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use bytes::BytesMut;
use tokio::sync::{Notify, mpsc, watch};
use webrtc::data_channel::{DataChannel, DataChannelEvent, RTCDataChannelInit};
use webrtc::peer_connection::{
    PeerConnection, PeerConnectionBuilder, PeerConnectionEventHandler, RTCConfigurationBuilder,
    RTCIceCandidateInit, RTCPeerConnectionIceEvent, RTCPeerConnectionState, RTCSessionDescription,
};
use webrtc::runtime::TokioRuntime;

#[path = "../../common/src/chunk.rs"]
mod chunk;

use chunk::{CHANNEL_FILES, CHANNEL_SPECS, PAUSE_ABOVE_BUFFERED, PauseGate, RESUME_BELOW_BUFFERED};

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
        });
        let local_sdp = Arc::new(Mutex::new(String::new()));
        rt.spawn(worker(
            cmd_rx,
            incoming_tx,
            cancel_rx,
            Arc::clone(&stats),
            Arc::clone(&local_sdp),
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
            first_frame_ms: 0,
            rss_mb: 0.0,
            cpu_pct: 0.0,
        }
    }

    pub fn enable_test_video(&self) -> Result<(), Error> {
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

struct Handler {
    state_tx: watch::Sender<RTCPeerConnectionState>,
    connected_gen: Arc<AtomicU64>,
    signal_tx: mpsc::UnboundedSender<String>,
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
        let _ = signal::queue(
            &self.signal_tx,
            &signal::Sig::Candidate {
                candidate: init.candidate,
                sdp_mid: init.sdp_mid,
                sdp_mline_index: init.sdp_mline_index,
            },
        );
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
}

async fn worker(
    mut cmd_rx: mpsc::Receiver<Cmd>,
    incoming_tx: std::sync::mpsc::Sender<(u16, Vec<u8>)>,
    mut cancel_rx: watch::Receiver<bool>,
    stats: Arc<StatsInner>,
    local_sdp: Arc<Mutex<String>>,
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
                        let result = connect_session(&url, &incoming_tx, &local_sdp).await;
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
                        let _ = reply.send(Err(Error::Failed(
                            "h264 test pattern is added in a later wave".into(),
                        )));
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
) -> Result<Connected, Error> {
    let started = Instant::now();
    let conn = signal::connect(url)
        .await
        .map_err(|err| Error::Failed(err.to_string()))?;
    let (role, signal_tx, mut signal_rx) = conn.into_split();
    let (state_tx, state_rx) = watch::channel(RTCPeerConnectionState::New);
    let connected_gen = Arc::new(AtomicU64::new(0));
    let answer_gen = Arc::new(AtomicU64::new(0));

    let pc = PeerConnectionBuilder::new()
        .with_configuration(RTCConfigurationBuilder::new().build())
        .with_handler(Arc::new(Handler {
            state_tx,
            connected_gen: Arc::clone(&connected_gen),
            signal_tx: signal_tx.clone(),
        }))
        .with_runtime(Arc::new(TokioRuntime))
        .with_udp_addrs(vec!["127.0.0.1:0".to_string()])
        .with_data_channel_send_buffer_limit(4 * 1024 * 1024)
        .build()
        .await
        .map_err(|err| Error::Failed(err.to_string()))?;
    let pc: Arc<dyn PeerConnection> = Arc::new(pc);

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
    wait_state(&mut state_rx, CONNECT_TIMEOUT).await?;
    Ok(Connected {
        session: Session {
            pc,
            slots,
            signal_tx,
            state_rx,
            connected_gen,
            answer_gen,
        },
        connect_ms: elapsed_ms(started),
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

async fn wait_state(
    state_rx: &mut watch::Receiver<RTCPeerConnectionState>,
    timeout: Duration,
) -> Result<(), Error> {
    let deadline = Instant::now() + timeout;
    loop {
        let state = *state_rx.borrow();
        if state == RTCPeerConnectionState::Connected {
            return Ok(());
        }
        if state == RTCPeerConnectionState::Failed || state == RTCPeerConnectionState::Closed {
            return Err(Error::Failed(format!("connection {state}")));
        }
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return Err(Error::Timeout);
        }
        if tokio::time::timeout(left, state_rx.changed())
            .await
            .is_err()
        {
            return Err(Error::Timeout);
        }
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
        for chunk in chunks {
            loop {
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
    let deadline = Instant::now() + OPEN_TIMEOUT;
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
    let deadline = Instant::now() + RESTART_TIMEOUT;
    loop {
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
