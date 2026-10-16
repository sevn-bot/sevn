//! Shared spike contracts for the two S1 peers.
//!
//! Signatures only. `peer_by_name` and every `Peer` method stay unimplemented
//! until the peer wave fills them in. Valid names are `webrtcrs` and `str0m`.

use std::fmt;
use std::sync::Arc;
use std::time::Duration;

pub const CHANNEL_RPC: u16 = 0;
pub const CHANNEL_EVENTS: u16 = 1;
pub const CHANNEL_FILES: u16 = 2;

/// D2: files payload size, not counting the 24-byte header.
pub const FILE_CHUNK_PAYLOAD: usize = 16 * 1024;
/// D2: 16-byte transfer id followed by an 8-byte big-endian offset.
pub const FILE_CHUNK_HEADER_LEN: usize = 24;
/// Sender pauses while buffered bytes are above this.
pub const PAUSE_ABOVE_BUFFERED: usize = 1024 * 1024;
/// Sender resumes once buffered bytes fall below this.
pub const RESUME_BELOW_BUFFERED: usize = 256 * 1024;

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

#[derive(Debug, Clone, PartialEq)]
pub struct Metrics {
    pub connect_ms: u64,
    pub ice_restart_ms: u64,
    pub backpressure_pauses: u64,
    pub first_frame_ms: u64,
    pub rss_mb: f64,
    pub cpu_pct: f64,
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

pub fn peer_by_name(name: &str) -> Result<Arc<dyn Peer>, PeerError> {
    unimplemented!("peer_by_name({name})")
}
