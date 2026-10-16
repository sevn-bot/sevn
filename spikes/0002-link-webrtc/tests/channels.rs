//! D2 channels, chunking, and ICE restart. Green after W2.

mod support;

use std::sync::Arc;
use std::thread;

use common::{Channel, Peer};

use support::{LIBS, Peers};

#[ignore = "green after W2"]
#[test]
fn peer_by_name_rejects_unknown() {
    for name in ["pion", "webrtc-rs", "STR0M", ""] {
        let err = match common::peer_by_name(name) {
            Ok(_) => panic!("unknown library {name} was accepted"),
            Err(err) => err,
        };
        assert_eq!(err, common::PeerError::UnknownPeer(name.to_owned()));
        assert_eq!(err.to_string(), format!("unknown peer {name}"));
    }
}

#[ignore = "green after W2"]
#[test]
fn three_ordered_channels_open() {
    for name in LIBS {
        let peers = support::two_peers(name);
        support::connect_both(&peers);
        let offerer = peers.offerer.open_channels().expect("offerer channels");
        let answerer = peers.answerer.open_channels().expect("answerer channels");
        for (side, channels) in [("offerer", offerer), ("answerer", answerer)] {
            assert_labels(name, side, &channels);
        }
    }
}

#[ignore = "green after W2"]
#[test]
fn rpc_messages_arrive_in_order() {
    for name in LIBS {
        assert_ordered(name, common::CHANNEL_RPC);
    }
}

#[ignore = "green after W2"]
#[test]
fn events_messages_arrive_in_order() {
    for name in LIBS {
        assert_ordered(name, common::CHANNEL_EVENTS);
    }
}

#[ignore = "green after W2"]
#[test]
fn files_chunking_roundtrip() {
    assert_eq!(common::CHANNEL_FILES, 2);
    assert_eq!(common::FILE_CHUNK_PAYLOAD, 16 * 1024);
    assert_eq!(common::FILE_CHUNK_HEADER_LEN, 24);
    assert_eq!(common::PAUSE_ABOVE_BUFFERED, 1024 * 1024);
    assert_eq!(common::RESUME_BELOW_BUFFERED, 256 * 1024);

    for name in LIBS {
        let blob = support::blob_10mb();
        let got = exchange_file(name, &blob);
        assert_eq!(got.len(), blob.len(), "{name} length");
        assert_eq!(
            support::sha256_hex(&got),
            support::sha256_hex(&blob),
            "{name} sha256"
        );
    }
}

#[ignore = "green after W2"]
#[test]
fn files_short_chunk_roundtrip() {
    for name in LIBS {
        let blob = (0_u8..100).collect::<Vec<_>>();
        let got = exchange_file_without_backpressure(name, &blob);
        assert_eq!(got.len(), blob.len(), "{name} short length");
        assert_eq!(
            support::sha256_hex(&got),
            support::sha256_hex(&blob),
            "{name} short sha256"
        );
    }
}

#[ignore = "green after W2"]
#[test]
fn ice_restart_recovers() {
    for name in LIBS {
        let peers = connected(name);
        peers
            .offerer
            .send(common::CHANNEL_RPC, b"before")
            .unwrap_or_else(|err| panic!("{name} send before: {err}"));
        let before = peers
            .answerer
            .recv()
            .unwrap_or_else(|err| panic!("{name} recv before: {err}"));
        assert_eq!(before.channel, common::CHANNEL_RPC);
        assert_eq!(before.bytes, b"before");

        peers
            .offerer
            .ice_restart()
            .unwrap_or_else(|err| panic!("{name} ice restart: {err}"));
        peers
            .offerer
            .send(common::CHANNEL_RPC, b"after")
            .unwrap_or_else(|err| panic!("{name} send after: {err}"));
        let after = peers
            .answerer
            .recv()
            .unwrap_or_else(|err| panic!("{name} recv after: {err}"));
        assert_eq!(after.channel, common::CHANNEL_RPC);
        assert_eq!(after.bytes, b"after");

        let ms = peers.offerer.metrics().ice_restart_ms;
        assert!(ms > 0, "{name} ice_restart_ms was not recorded");
        assert!(ms < 5000, "{name} ice_restart_ms {ms} >= 5000");
    }
}

fn assert_labels(name: &str, side: &str, channels: &[Channel]) {
    assert_eq!(channels.len(), 3, "{name} {side} channel count");
    let mut pairs: Vec<(u16, String)> = channels
        .iter()
        .map(|ch| (ch.id, ch.label.clone()))
        .collect();
    pairs.sort();
    assert_eq!(
        pairs,
        vec![
            (0, "rpc".to_owned()),
            (1, "events".to_owned()),
            (2, "files".to_owned()),
        ],
        "{name} {side}"
    );
}

fn assert_ordered(name: &str, channel: u16) {
    assert!(channel == common::CHANNEL_RPC || channel == common::CHANNEL_EVENTS);
    assert_eq!(common::CHANNEL_RPC, 0);
    assert_eq!(common::CHANNEL_EVENTS, 1);

    let peers = connected(name);
    let count = 1000_u32;
    for index in 0..count {
        peers
            .offerer
            .send(channel, &index.to_be_bytes())
            .unwrap_or_else(|err| panic!("{name} ch {channel} send {index}: {err}"));
    }
    for index in 0..count {
        let message = peers
            .answerer
            .recv()
            .unwrap_or_else(|err| panic!("{name} ch {channel} recv {index}: {err}"));
        assert_eq!(message.channel, channel, "{name} index {index}");
        assert_eq!(message.bytes, index.to_be_bytes(), "{name} index {index}");
    }
}

fn exchange_file(name: &str, blob: &[u8]) -> Vec<u8> {
    let peers = connected(name);
    let answerer = Arc::clone(&peers.answerer);
    let total = blob.len();
    let reader = thread::spawn(move || collect_files(&answerer, total));
    peers
        .offerer
        .send(2, blob)
        .unwrap_or_else(|err| panic!("{name} send file: {err}"));
    let got = reader.join().expect("reader");
    let pauses = peers.offerer.metrics().backpressure_pauses;
    assert!(
        pauses > 0,
        "{name} sender never paused (backpressure_pauses={pauses})"
    );
    got
}

fn exchange_file_without_backpressure(name: &str, blob: &[u8]) -> Vec<u8> {
    let peers = connected(name);
    let answerer = Arc::clone(&peers.answerer);
    let total = blob.len();
    let reader = thread::spawn(move || collect_files(&answerer, total));
    peers
        .offerer
        .send(2, blob)
        .unwrap_or_else(|err| panic!("{name} send short file: {err}"));
    reader.join().expect("reader")
}

/// Files messages are D2 chunks: 16-byte transfer id, 8-byte big-endian offset, payload.
fn collect_files(peer: &Arc<dyn Peer>, total: usize) -> Vec<u8> {
    const ID_LEN: usize = 16;
    const OFFSET_LEN: usize = 8;
    assert_eq!(common::FILE_CHUNK_HEADER_LEN, ID_LEN + OFFSET_LEN);
    assert_eq!(common::FILE_CHUNK_PAYLOAD, 16 * 1024);

    let mut payloads = Vec::with_capacity(total);
    let mut expected_offset = 0_u64;
    let mut transfer_id: Option<[u8; 16]> = None;
    while payloads.len() < total {
        let message = peer.recv().expect("files recv");
        assert_eq!(message.channel, 2, "files channel id");
        let payload_len = (total - payloads.len()).min(common::FILE_CHUNK_PAYLOAD);
        assert_eq!(message.bytes.len(), ID_LEN + OFFSET_LEN + payload_len);
        let mut id = [0_u8; ID_LEN];
        id.copy_from_slice(&message.bytes[..ID_LEN]);
        let offset = u64::from_be_bytes(
            message.bytes[ID_LEN..ID_LEN + OFFSET_LEN]
                .try_into()
                .expect("offset width"),
        );
        assert_eq!(offset, expected_offset, "chunk offset");
        match transfer_id {
            None => transfer_id = Some(id),
            Some(previous) => assert_eq!(previous, id, "transfer id changed"),
        }
        payloads.extend_from_slice(&message.bytes[ID_LEN + OFFSET_LEN..]);
        expected_offset += payload_len as u64;
    }
    payloads
}

fn connected(name: &str) -> Peers {
    let peers = support::two_peers(name);
    support::connect_both(&peers);
    let _offerer = peers.offerer.open_channels().expect("offerer channels");
    let _answerer = peers.answerer.open_channels().expect("answerer channels");
    peers
}
