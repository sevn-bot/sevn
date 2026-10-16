//! D3 H.264 test-pattern track.

mod support;

use support::LIBS;

#[test]
fn h264_track_negotiated() {
    for name in LIBS {
        let peers = support::two_peers(name);
        peers
            .offerer
            .enable_test_video()
            .unwrap_or_else(|err| panic!("{name} enable video: {err}"));
        support::connect_both(&peers);
        let sdp = peers.offerer.local_description();
        assert!(
            sdp.contains("m=video"),
            "{name} SDP has no video m-line:\n{sdp}"
        );
        assert!(sdp.contains("H264"), "{name} SDP has no H264:\n{sdp}");
        assert!(
            sdp.contains("profile-level-id=42e01f"),
            "{name} SDP missing constrained baseline profile:\n{sdp}"
        );
    }
}
