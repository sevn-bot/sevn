//! D3 H.264 constrained-baseline test pattern (1280×720, 30 fps).
//!
//! Included by both peer crates via `#[path]` so they share one encoder
//! invocation without a crate cycle. `ffmpeg` / `libx264` produces Annex B.
//! x264's baseline profile emits `profile-level-id` `42c01f`; the constrained
//! baseline Chrome and Safari negotiate is `42e01f` (constraint_set2). The
//! bitstream is baseline, so setting that flag matches the SDP fmtp.

use std::process::Command;
use std::sync::OnceLock;

const WIDTH: &str = "1280";
const HEIGHT: &str = "720";

pub fn h264_access_units() -> Result<&'static [Vec<u8>], String> {
    static UNITS: OnceLock<Result<Vec<Vec<u8>>, String>> = OnceLock::new();
    match UNITS.get_or_init(encode_pattern) {
        Ok(units) => Ok(units.as_slice()),
        Err(err) => Err(err.clone()),
    }
}

fn encode_pattern() -> Result<Vec<Vec<u8>>, String> {
    let output = Command::new("ffmpeg")
        .args([
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            &format!("testsrc=size={WIDTH}x{HEIGHT}:rate=30"),
            "-frames:v",
            "15",
            "-an",
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-level",
            "3.1",
            "-pix_fmt",
            "yuv420p",
            "-x264-params",
            "bframes=0:keyint=1:min-keyint=1:scenecut=0:repeat-headers=1",
            "-f",
            "h264",
            "pipe:1",
        ])
        .output()
        .map_err(|err| format!("ffmpeg: {err}"))?;
    if !output.status.success() {
        let err = String::from_utf8_lossy(&output.stderr);
        return Err(format!("ffmpeg exited {}: {err}", output.status));
    }
    let mut bytes = output.stdout;
    let patched = patch_constrained_baseline(&mut bytes);
    if patched == 0 {
        return Err("test pattern SPS was not constrained baseline".into());
    }
    let units = split_access_units(&bytes);
    if units.is_empty() {
        return Err("ffmpeg produced no H.264 access units".into());
    }
    Ok(units)
}

/// `67 42 c0 1f` → `67 42 e0 1f` so the in-band SPS matches `42e01f`.
fn patch_constrained_baseline(bytes: &mut [u8]) -> usize {
    let mut patched = 0;
    let mut i = 0;
    while i + 4 < bytes.len() {
        if bytes[i] == 0x67 && bytes[i + 1] == 0x42 && bytes[i + 2] == 0xc0 && bytes[i + 3] == 0x1f
        {
            bytes[i + 2] = 0xe0;
            patched += 1;
            i += 4;
            continue;
        }
        i += 1;
    }
    patched
}

fn split_access_units(data: &[u8]) -> Vec<Vec<u8>> {
    let starts = start_codes(data);
    if starts.is_empty() {
        return Vec::new();
    }
    let mut units = Vec::new();
    let mut current: Vec<u8> = Vec::new();
    let mut has_vcl = false;
    for (index, &start) in starts.iter().enumerate() {
        let end = starts.get(index + 1).copied().unwrap_or(data.len());
        let nal_type = nal_header(data, start) & 0x1f;
        let vcl = (1..=5).contains(&nal_type);
        let boundary = !current.is_empty() && (nal_type == 7 || nal_type == 9 || (vcl && has_vcl));
        if boundary {
            units.push(std::mem::take(&mut current));
            has_vcl = false;
        }
        current.extend_from_slice(&data[start..end]);
        if vcl {
            has_vcl = true;
        }
    }
    if !current.is_empty() {
        units.push(current);
    }
    units
}

fn start_codes(data: &[u8]) -> Vec<usize> {
    let mut out = Vec::new();
    let mut i = 0;
    while i + 3 <= data.len() {
        if data[i] == 0 && data[i + 1] == 0 && data[i + 2] == 1 {
            let at = if i > 0 && data[i - 1] == 0 { i - 1 } else { i };
            if out.last().copied() != Some(at) {
                out.push(at);
            }
            i += 3;
        } else {
            i += 1;
        }
    }
    out
}

fn nal_header(data: &[u8], start: usize) -> u8 {
    let offset = if data[start..].starts_with(&[0, 0, 0, 1]) {
        4
    } else {
        3
    };
    data.get(start + offset).copied().unwrap_or(0)
}
