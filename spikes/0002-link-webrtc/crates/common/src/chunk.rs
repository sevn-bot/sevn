//! D2 file chunks and the pause/resume watermarks.
//!
//! Included by `common` and by both peer crates (via `#[path]`) so the wire
//! format stays in one place without a crate cycle.

use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

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

pub const CHANNEL_SPECS: [(u16, &str); 3] = [
    (CHANNEL_RPC, "rpc"),
    (CHANNEL_EVENTS, "events"),
    (CHANNEL_FILES, "files"),
];

static TRANSFER_SEQ: AtomicU64 = AtomicU64::new(1);

/// Split `bytes` into D2 wire chunks. The transfer id is stable across the blob.
pub fn chunk_blob(bytes: &[u8]) -> Vec<Vec<u8>> {
    let mut id = [0_u8; 16];
    let seq = TRANSFER_SEQ.fetch_add(1, Ordering::Relaxed);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_nanos() as u64)
        .unwrap_or(0);
    id[..8].copy_from_slice(&seq.to_le_bytes());
    id[8..].copy_from_slice(&now.to_le_bytes());

    let mut out = Vec::new();
    let mut offset = 0_usize;
    while offset < bytes.len() {
        let end = (offset + FILE_CHUNK_PAYLOAD).min(bytes.len());
        let mut wire = Vec::with_capacity(FILE_CHUNK_HEADER_LEN + (end - offset));
        wire.extend_from_slice(&id);
        wire.extend_from_slice(&(offset as u64).to_be_bytes());
        wire.extend_from_slice(&bytes[offset..end]);
        out.push(wire);
        offset = end;
    }
    out
}

/// Pause above 1 MiB buffered, resume below 256 KiB. `pauses` counts episodes.
#[derive(Debug)]
pub struct PauseGate {
    pub pauses: u64,
    pausing: bool,
}

impl PauseGate {
    pub fn new() -> Self {
        Self {
            pauses: 0,
            pausing: false,
        }
    }

    /// `true` when the caller must wait before queueing another chunk.
    pub fn observe(&mut self, buffered: usize) -> bool {
        if self.pausing {
            if buffered < RESUME_BELOW_BUFFERED {
                self.pausing = false;
                false
            } else {
                true
            }
        } else if buffered > PAUSE_ABOVE_BUFFERED {
            self.pausing = true;
            self.pauses += 1;
            true
        } else {
            false
        }
    }
}

impl Default for PauseGate {
    fn default() -> Self {
        Self::new()
    }
}
