#![allow(dead_code)]

use std::sync::Arc;
use std::thread;

use common::Peer;
use sha2::{Digest, Sha256};

pub const LIBS: [&str; 2] = ["webrtcrs", "str0m"];

pub struct Peers {
    pub offerer: Arc<dyn Peer>,
    pub answerer: Arc<dyn Peer>,
    pub room: signal::Room,
}

pub fn two_peers(name: &str) -> Peers {
    let room = signal::serve_one_room().unwrap_or_else(|err| panic!("{name}: signal: {err}"));
    let offerer = common::peer_by_name(name).unwrap_or_else(|err| panic!("{name}: offerer: {err}"));
    let answerer =
        common::peer_by_name(name).unwrap_or_else(|err| panic!("{name}: answerer: {err}"));
    Peers {
        offerer,
        answerer,
        room,
    }
}

/// `connect` may block until the other peer connects, so both run together.
pub fn connect_both(peers: &Peers) {
    let url = peers.room.url.as_str();
    thread::scope(|scope| {
        scope.spawn(|| {
            peers
                .offerer
                .connect(url)
                .unwrap_or_else(|err| panic!("offerer connect: {err}"));
        });
        scope.spawn(|| {
            peers
                .answerer
                .connect(url)
                .unwrap_or_else(|err| panic!("answerer connect: {err}"));
        });
    });
}

pub fn sha256(bytes: &[u8]) -> [u8; 32] {
    let digest = Sha256::digest(bytes);
    digest.into()
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    hex(&sha256(bytes))
}

fn hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

/// Pseudorandom 10 MiB blob. Fixed seed so a mismatch is reproducible.
pub fn blob_10mb() -> Vec<u8> {
    const LEN: usize = 10 * 1024 * 1024;
    let mut state: u64 = 0x0002_5EED;
    let mut out = vec![0_u8; LEN];
    for byte in &mut out {
        state = state
            .wrapping_mul(0x5851_F42D_4C95_7F2D)
            .wrapping_add(0x1405_7B7E_F767_814F);
        *byte = (state >> 33) as u8;
    }
    out
}
