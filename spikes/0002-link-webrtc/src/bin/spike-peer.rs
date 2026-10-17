//! Browser-facing peer for the S1 harness.
//!
//! Prints `READY <url>` after this process has joined the signalling room, so
//! the browser is the answerer. Serves `harness/index.html` and `harness/peer.ts`.

use std::io::{Read, Write};
use std::net::TcpListener;
use std::thread;
use std::time::{Duration, Instant};

use common::Peer;

const INDEX_HTML: &str = include_str!("../../harness/index.html");
const PEER_JS: &str = include_str!("../../harness/peer.ts");
const FILE_LEN: usize = 10 * 1024 * 1024;

fn main() {
    let (lib, scenario) = match parse_args() {
        Ok(parsed) => parsed,
        Err(err) => {
            eprintln!("spike-peer: {err}");
            std::process::exit(2);
        }
    };

    let room = match signal::serve_one_room() {
        Ok(room) => room,
        Err(err) => {
            eprintln!("spike-peer: signal: {err}");
            std::process::exit(1);
        }
    };
    let peer = match common::peer_by_name(&lib) {
        Ok(peer) => peer,
        Err(err) => {
            eprintln!("spike-peer: {err}");
            std::process::exit(1);
        }
    };

    let signal_url = room.url.clone();
    let scenario_thread = scenario.clone();
    let peer_thread = std::sync::Arc::clone(&peer);
    thread::spawn(move || {
        if let Err(err) = drive(&peer_thread, &signal_url, &scenario_thread) {
            eprintln!("spike-peer: {err}");
        }
    });

    let joined = Instant::now();
    while room.peers_connected() < 1 {
        if joined.elapsed() > Duration::from_secs(10) {
            eprintln!("spike-peer: timed out waiting to join the signal room");
            std::process::exit(1);
        }
        thread::sleep(Duration::from_millis(5));
    }

    let http_bind = std::env::var("SPIKE_HTTP_BIND").unwrap_or_else(|_| "127.0.0.1".to_owned());
    let http_host = std::env::var("SPIKE_HTTP_HOST").unwrap_or_else(|_| "127.0.0.1".to_owned());
    let listener = match TcpListener::bind((http_bind.as_str(), 0)) {
        Ok(listener) => listener,
        Err(err) => {
            eprintln!("spike-peer: {err}");
            std::process::exit(1);
        }
    };
    let port = match listener.local_addr() {
        Ok(addr) => addr.port(),
        Err(err) => {
            eprintln!("spike-peer: {err}");
            std::process::exit(1);
        }
    };
    let relay = if std::env::var("SPIKE_TURN_URL")
        .ok()
        .is_some_and(|value| !value.is_empty())
    {
        "&relay=1"
    } else {
        ""
    };
    let page = format!(
        "http://{http_host}:{port}/?scenario={}&signal={}{relay}",
        query_encode(&scenario),
        query_encode(&room.url),
    );
    println!("READY {page}");
    let _ = std::io::stdout().flush();

    for stream in listener.incoming() {
        let Ok(mut stream) = stream else { continue };
        let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
        let mut buf = [0_u8; 2048];
        let n = stream.read(&mut buf).unwrap_or(0);
        let request = String::from_utf8_lossy(&buf[..n]);
        let path = request
            .split_whitespace()
            .nth(1)
            .unwrap_or("/")
            .split('?')
            .next()
            .unwrap_or("/");
        let ice = ice_json();
        let (status, content_type, body) = if path == "/peer.ts" {
            ("200 OK", "text/javascript; charset=utf-8", PEER_JS)
        } else if path == "/ice.json" {
            ("200 OK", "application/json", ice.as_str())
        } else if path == "/" {
            ("200 OK", "text/html; charset=utf-8", INDEX_HTML)
        } else {
            ("404 Not Found", "text/plain; charset=utf-8", "not found")
        };
        let header = format!(
            "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        let _ = stream.write_all(header.as_bytes());
        let _ = stream.write_all(body.as_bytes());
    }
}

fn drive(peer: &std::sync::Arc<dyn Peer>, signal_url: &str, scenario: &str) -> Result<(), String> {
    if scenario == "video" {
        peer.enable_test_video().map_err(|err| err.to_string())?;
    }
    peer.connect(signal_url).map_err(|err| err.to_string())?;
    peer.open_channels().map_err(|err| err.to_string())?;
    if scenario == "file" {
        let deadline = Instant::now() + Duration::from_secs(20);
        loop {
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return Err("timed out waiting for browser ready".into());
            }
            let message = peer
                .recv_timeout(left)
                .map_err(|err| format!("ready: {err}"))?;
            if message.channel == common::CHANNEL_RPC && message.bytes == b"ready" {
                break;
            }
        }
        peer.send(common::CHANNEL_FILES, &file_bytes())
            .map_err(|err| err.to_string())?;
    }
    thread::park();
    Ok(())
}

fn file_bytes() -> Vec<u8> {
    let mut out = vec![0_u8; FILE_LEN];
    for (index, byte) in out.iter_mut().enumerate() {
        *byte = (index % 251) as u8;
    }
    out
}

fn parse_args() -> Result<(String, String), String> {
    let mut lib = None;
    let mut scenario = None;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--lib" => {
                lib = Some(
                    args.next()
                        .ok_or_else(|| "missing --lib value".to_owned())?,
                );
            }
            "--scenario" => {
                scenario = Some(
                    args.next()
                        .ok_or_else(|| "missing --scenario value".to_owned())?,
                );
            }
            other => return Err(format!("unknown argument {other}")),
        }
    }
    let lib = lib.ok_or_else(|| "missing --lib".to_owned())?;
    let scenario = scenario.ok_or_else(|| "missing --scenario".to_owned())?;
    if scenario != "channels" && scenario != "file" && scenario != "video" {
        return Err(format!("unknown scenario {scenario}"));
    }
    Ok((lib, scenario))
}

fn ice_json() -> String {
    let url = std::env::var("SPIKE_TURN_URL").unwrap_or_default();
    let username = std::env::var("SPIKE_TURN_USERNAME").unwrap_or_default();
    let credential = std::env::var("SPIKE_TURN_CREDENTIAL").unwrap_or_default();
    if url.is_empty() || username.is_empty() || credential.is_empty() {
        return "{\"iceServers\":[]}".to_owned();
    }
    format!(
        "{{\"iceServers\":[{{\"urls\":[\"{}\"],\"username\":\"{}\",\"credential\":\"{}\"}}]}}",
        json_escape(&url),
        json_escape(&username),
        json_escape(&credential),
    )
}

fn json_escape(value: &str) -> String {
    let mut out = String::new();
    for ch in value.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            c if c.is_control() => out.push_str(&format!("\\u{:04x}", u32::from(c))),
            c => out.push(c),
        }
    }
    out
}

fn query_encode(value: &str) -> String {
    let mut out = String::new();
    for byte in value.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(byte as char);
            }
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}
