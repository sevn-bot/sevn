//! Shared spike contracts for the two S1 peers.

use std::fmt;
use std::sync::Arc;
use std::time::Duration;

use serde::{Deserialize, Serialize};

mod chunk;

pub use chunk::{
    CHANNEL_EVENTS, CHANNEL_FILES, CHANNEL_RPC, CHANNEL_SPECS, FILE_CHUNK_HEADER_LEN,
    FILE_CHUNK_PAYLOAD, PAUSE_ABOVE_BUFFERED, PauseGate, RESUME_BELOW_BUFFERED, chunk_blob,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Channel {
    pub id: u16,
    pub label: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Incoming {
    pub channel: u16,
    pub bytes: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Metrics {
    pub connect_ms: u64,
    pub ice_restart_ms: u64,
    pub backpressure_pauses: u64,
    pub first_frame_ms: u64,
    pub rss_mb: f64,
    pub cpu_pct: f64,
}

impl Metrics {
    pub fn empty() -> Self {
        Self {
            connect_ms: 0,
            ice_restart_ms: 0,
            backpressure_pauses: 0,
            first_frame_ms: 0,
            rss_mb: 0.0,
            cpu_pct: 0.0,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PeerError {
    UnknownPeer(String),
    Timeout,
    Failed(String),
}

impl fmt::Display for PeerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PeerError::UnknownPeer(name) => write!(f, "unknown peer {name}"),
            PeerError::Timeout => f.write_str("timed out"),
            PeerError::Failed(message) => f.write_str(message),
        }
    }
}

impl std::error::Error for PeerError {}

pub trait Peer: Send + Sync {
    fn connect(&self, signal_url: &str) -> Result<(), PeerError>;
    fn open_channels(&self) -> Result<Vec<Channel>, PeerError>;
    /// One message on `rpc` or `events`. On `files`, `bytes` is the whole blob:
    /// the peer chunks it (D2) and applies the pause/resume watermarks.
    fn send(&self, channel: u16, bytes: &[u8]) -> Result<(), PeerError>;
    /// Wait up to `timeout` for the next data-channel message.
    /// Returns [`PeerError::Timeout`] (display `timed out`) when none arrives.
    /// Must stay callable on one peer while [`Peer::send`] runs on the other.
    fn recv_timeout(&self, timeout: Duration) -> Result<Incoming, PeerError>;
    fn ice_restart(&self) -> Result<(), PeerError>;
    /// Snapshot. Must be readable while [`Peer::send`] is blocked on backpressure.
    fn metrics(&self) -> Metrics;
    /// Add the D3 H.264 test-pattern track before [`Peer::connect`].
    fn enable_test_video(&self) -> Result<(), PeerError>;
    /// SDP of the local description after connect. Includes the video m-line
    /// when [`Peer::enable_test_video`] ran first.
    fn local_description(&self) -> String;

    fn recv(&self) -> Result<Incoming, PeerError> {
        self.recv_timeout(Duration::from_secs(5))
    }
}

struct Adapted<T> {
    inner: T,
}

fn from_peer(err: impl fmt::Display) -> PeerError {
    let message = err.to_string();
    if message == "timed out" {
        PeerError::Timeout
    } else {
        PeerError::Failed(message)
    }
}

fn map_channels(channels: Vec<(u16, String)>) -> Vec<Channel> {
    channels
        .into_iter()
        .map(|(id, label)| Channel { id, label })
        .collect()
}

fn map_incoming(channel: u16, bytes: Vec<u8>) -> Incoming {
    Incoming { channel, bytes }
}

fn map_metrics(stats: peer_webrtcrs::Stats) -> Metrics {
    Metrics {
        connect_ms: stats.connect_ms,
        ice_restart_ms: stats.ice_restart_ms,
        backpressure_pauses: stats.backpressure_pauses,
        first_frame_ms: stats.first_frame_ms,
        rss_mb: stats.rss_mb,
        cpu_pct: stats.cpu_pct,
    }
}

fn map_str0m_metrics(stats: peer_str0m::Stats) -> Metrics {
    Metrics {
        connect_ms: stats.connect_ms,
        ice_restart_ms: stats.ice_restart_ms,
        backpressure_pauses: stats.backpressure_pauses,
        first_frame_ms: stats.first_frame_ms,
        rss_mb: stats.rss_mb,
        cpu_pct: stats.cpu_pct,
    }
}

impl Peer for Adapted<peer_webrtcrs::Peer> {
    fn connect(&self, signal_url: &str) -> Result<(), PeerError> {
        self.inner.connect(signal_url).map_err(from_peer)
    }

    fn open_channels(&self) -> Result<Vec<Channel>, PeerError> {
        self.inner
            .open_channels()
            .map(map_channels)
            .map_err(from_peer)
    }

    fn send(&self, channel: u16, bytes: &[u8]) -> Result<(), PeerError> {
        self.inner.send(channel, bytes).map_err(from_peer)
    }

    fn recv_timeout(&self, timeout: Duration) -> Result<Incoming, PeerError> {
        self.inner
            .recv_timeout(timeout)
            .map(|(channel, bytes)| map_incoming(channel, bytes))
            .map_err(from_peer)
    }

    fn ice_restart(&self) -> Result<(), PeerError> {
        self.inner.ice_restart().map_err(from_peer)
    }

    fn metrics(&self) -> Metrics {
        map_metrics(self.inner.metrics())
    }

    fn enable_test_video(&self) -> Result<(), PeerError> {
        self.inner.enable_test_video().map_err(from_peer)
    }

    fn local_description(&self) -> String {
        self.inner.local_description()
    }
}

impl Peer for Adapted<peer_str0m::Peer> {
    fn connect(&self, signal_url: &str) -> Result<(), PeerError> {
        self.inner.connect(signal_url).map_err(from_peer)
    }

    fn open_channels(&self) -> Result<Vec<Channel>, PeerError> {
        self.inner
            .open_channels()
            .map(map_channels)
            .map_err(from_peer)
    }

    fn send(&self, channel: u16, bytes: &[u8]) -> Result<(), PeerError> {
        self.inner.send(channel, bytes).map_err(from_peer)
    }

    fn recv_timeout(&self, timeout: Duration) -> Result<Incoming, PeerError> {
        self.inner
            .recv_timeout(timeout)
            .map(|(channel, bytes)| map_incoming(channel, bytes))
            .map_err(from_peer)
    }

    fn ice_restart(&self) -> Result<(), PeerError> {
        self.inner.ice_restart().map_err(from_peer)
    }

    fn metrics(&self) -> Metrics {
        map_str0m_metrics(self.inner.metrics())
    }

    fn enable_test_video(&self) -> Result<(), PeerError> {
        self.inner.enable_test_video().map_err(from_peer)
    }

    fn local_description(&self) -> String {
        self.inner.local_description()
    }
}

pub fn peer_by_name(name: &str) -> Result<Arc<dyn Peer>, PeerError> {
    match name {
        "webrtcrs" => Ok(Arc::new(Adapted {
            inner: peer_webrtcrs::Peer::new(),
        })),
        "str0m" => Ok(Arc::new(Adapted {
            inner: peer_str0m::Peer::new(),
        })),
        other => Err(PeerError::UnknownPeer(other.to_owned())),
    }
}
