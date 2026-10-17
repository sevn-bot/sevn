//! D5 measurements. S-LAN writes `results/s-lan-<lib>.json`.
//! S-TURN writes `results/s-turn-<lib>-<transport>.json` when the parent
//! process has put relay settings in the environment.

use std::env;
use std::fs;
use std::path::PathBuf;
use std::thread;
use std::time::{Duration, Instant};

use common::{CHANNEL_FILES, CHANNEL_RPC, Peer};

const LIBS: [&str; 2] = ["webrtcrs", "str0m"];
const BLOB: usize = 10 * 1024 * 1024;
const RUNS: usize = 20;

fn main() {
    let scenario = arg_value("--scenario").unwrap_or_else(|| "s-lan".to_owned());
    match scenario.as_str() {
        "s-turn" => measure_turn(),
        "s-lan" => {
            for lib in LIBS {
                match measure_lan(lib) {
                    Ok(None) => {}
                    Ok(Some(summary)) => {
                        let path = results_path(&format!("s-lan-{lib}.json"));
                        fs::write(&path, summary.to_json(lib)).unwrap_or_else(|err| {
                            eprintln!("spike-measure: write {}: {err}", path.display());
                            std::process::exit(1);
                        });
                        println!(
                            "{lib} connect p50 {:.1} ms p95 {:.1} ms  {:.2} MiB/s  ice {:.1} ms  frame {:.1} ms",
                            summary.connect_p50_ms,
                            summary.connect_p95_ms,
                            summary.mbps_10mb,
                            summary.ice_restart_ms,
                            summary.first_frame_ms,
                        );
                    }
                    Err(err) => {
                        eprintln!("spike-measure: {lib}: {err}");
                        std::process::exit(1);
                    }
                }
            }
        }
        "stability" => {
            let count = arg_value("--count")
                .and_then(|value| value.parse().ok())
                .unwrap_or(100);
            for lib in LIBS {
                match connect_storm(lib, count) {
                    Ok((ok, failed)) => {
                        let path = results_path(&format!("stability-{lib}.json"));
                        let body = format!(
                            "{{\n  \"scenario\": \"stability\",\n  \"lib\": \"{lib}\",\n  \"connects\": {count},\n  \"ok\": {ok},\n  \"failed\": {failed}\n}}\n"
                        );
                        fs::write(&path, body).unwrap_or_else(|err| {
                            eprintln!("spike-measure: write {}: {err}", path.display());
                            std::process::exit(1);
                        });
                        println!("{lib} stability {ok}/{count} failed {failed}");
                    }
                    Err(err) => {
                        eprintln!("spike-measure: {lib}: {err}");
                        std::process::exit(1);
                    }
                }
            }
        }
        other => {
            eprintln!("spike-measure: unknown scenario {other}");
            std::process::exit(2);
        }
    }
}

struct Summary {
    connect_p50_ms: f64,
    connect_p95_ms: f64,
    mbps_10mb: f64,
    ice_restart_ms: f64,
    first_frame_ms: f64,
    rss_mb: f64,
    cpu_pct: f64,
}

impl Summary {
    fn to_turn_json(&self, lib: &str, transport: &str) -> String {
        format!(
            "{{\n  \"scenario\": \"s-turn\",\n  \"lib\": \"{lib}\",\n  \"transport\": \"{transport}\",\n  \"ice_transport_policy\": \"relay\",\n  \"candidate_type\": \"relay\",\n  \"runs\": {RUNS},\n  \"connect_p50_ms\": {p50},\n  \"connect_p95_ms\": {p95},\n  \"mbps_10mb\": {mbps},\n  \"ice_restart_ms\": {ice},\n  \"first_frame_ms\": {frame},\n  \"rss_mb\": {rss},\n  \"cpu_pct\": {cpu}\n}}\n",
            p50 = num(self.connect_p50_ms),
            p95 = num(self.connect_p95_ms),
            mbps = num(self.mbps_10mb),
            ice = num(self.ice_restart_ms),
            frame = num(self.first_frame_ms),
            rss = num(self.rss_mb),
            cpu = num(self.cpu_pct),
        )
    }

    fn to_json(&self, lib: &str) -> String {
        format!(
            "{{\n  \"scenario\": \"s-lan\",\n  \"lib\": \"{lib}\",\n  \"runs\": {RUNS},\n  \"connect_p50_ms\": {p50},\n  \"connect_p95_ms\": {p95},\n  \"mbps_10mb\": {mbps},\n  \"ice_restart_ms\": {ice},\n  \"first_frame_ms\": {frame},\n  \"rss_mb\": {rss},\n  \"cpu_pct\": {cpu}\n}}\n",
            p50 = num(self.connect_p50_ms),
            p95 = num(self.connect_p95_ms),
            mbps = num(self.mbps_10mb),
            ice = num(self.ice_restart_ms),
            frame = num(self.first_frame_ms),
            rss = num(self.rss_mb),
            cpu = num(self.cpu_pct),
        )
    }
}

struct Run {
    connect_ms: f64,
    mbps: f64,
    ice_ms: f64,
    frame_ms: f64,
    pauses: u64,
}

fn measure_turn() {
    let transport = env::var("SPIKE_TURN_TRANSPORT").unwrap_or_default();
    if transport != "udp" && transport != "tls443" {
        eprintln!("relay transport is unset");
        std::process::exit(2);
    }
    if env::var("SPIKE_TURN_URL")
        .ok()
        .is_none_or(|value| value.is_empty())
    {
        eprintln!("relay measurement env is unset");
        std::process::exit(1);
    }
    let official = run_count() == RUNS;
    let mut failed = false;
    for lib in LIBS {
        match measure_lan(lib) {
            Ok(None) => {}
            Ok(Some(summary)) => {
                let path = results_path(&format!("s-turn-{lib}-{transport}.json"));
                fs::write(&path, summary.to_turn_json(lib, &transport)).unwrap_or_else(|err| {
                    eprintln!("spike-measure: write {}: {err}", path.display());
                    std::process::exit(1);
                });
                println!(
                    "{lib} {transport} connect p50 {:.1} ms p95 {:.1} ms  {:.2} MiB/s  ice {:.1} ms",
                    summary.connect_p50_ms,
                    summary.connect_p95_ms,
                    summary.mbps_10mb,
                    summary.ice_restart_ms,
                );
            }
            Err(err) => {
                let reason = safe_reason(&err);
                eprintln!("spike-measure: {lib}: {reason}");
                failed = true;
                if official {
                    let path = results_path(&format!("s-turn-{lib}-{transport}.json"));
                    let body = format!(
                        "{{\n  \"scenario\": \"s-turn\",\n  \"lib\": \"{lib}\",\n  \"transport\": \"{transport}\",\n  \"ice_transport_policy\": \"relay\",\n  \"ok\": false,\n  \"reason\": \"{reason}\"\n}}\n"
                    );
                    fs::write(&path, body).unwrap_or_else(|err| {
                        eprintln!("spike-measure: write {}: {err}", path.display());
                        std::process::exit(1);
                    });
                }
            }
        }
    }
    if failed && !official {
        std::process::exit(1);
    }
}

fn run_count() -> usize {
    env::var("SPIKE_RUNS")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(RUNS)
}

fn relay_on() -> bool {
    env::var("SPIKE_TURN_URL")
        .ok()
        .is_some_and(|value| !value.is_empty())
}

fn probe_wait() -> Duration {
    if relay_on() {
        Duration::from_secs(15)
    } else {
        Duration::from_secs(5)
    }
}

fn blob_wait() -> Duration {
    if relay_on() {
        Duration::from_secs(180)
    } else {
        Duration::from_secs(90)
    }
}

fn safe_reason(err: &str) -> String {
    let leaked = err.contains("turn:")
        || err.contains("credential")
        || err.contains("token")
        || err.contains("SPIKE_TURN")
        || ipv4(err);
    if leaked {
        "relay measurement failed".to_owned()
    } else {
        err.replace('"', "'")
    }
}

fn ipv4(text: &str) -> bool {
    text.split(|ch: char| !ch.is_ascii_digit() && ch != '.')
        .any(|part| {
            let octets: Vec<_> = part.split('.').collect();
            octets.len() == 4
                && octets
                    .iter()
                    .all(|octet| !octet.is_empty() && octet.parse::<u16>().is_ok_and(|n| n <= 255))
        })
}

fn measure_lan(lib: &str) -> Result<Option<Summary>, String> {
    let runs = run_count();
    let (_rss_before, cpu_before) = usage();
    let wall = Instant::now();
    let mut samples = Vec::with_capacity(RUNS);
    for index in 0..runs {
        let run = one_run(lib).map_err(|err| format!("run {}: {err}", index + 1))?;
        println!(
            "{lib} run {} connect {:.0} ms {:.2} MiB/s ice {:.0} ms frame {:.0} ms pauses {}",
            index + 1,
            run.connect_ms,
            run.mbps,
            run.ice_ms,
            run.frame_ms,
            run.pauses,
        );
        samples.push(run);
    }
    let wall_s = wall.elapsed().as_secs_f64().max(0.001);
    let (rss_after, cpu_after) = usage();
    let cpu_pct = cpu_after
        .checked_sub(cpu_before)
        .unwrap_or_default()
        .as_secs_f64()
        / wall_s
        * 100.0;
    if runs != RUNS {
        println!("{lib} debug runs {runs}; not writing json");
        return Ok(None);
    }
    Ok(Some(Summary {
        connect_p50_ms: percentile(
            &mut samples.iter().map(|run| run.connect_ms).collect::<Vec<_>>(),
            50.0,
        ),
        connect_p95_ms: percentile(
            &mut samples.iter().map(|run| run.connect_ms).collect::<Vec<_>>(),
            95.0,
        ),
        mbps_10mb: percentile(
            &mut samples.iter().map(|run| run.mbps).collect::<Vec<_>>(),
            50.0,
        ),
        ice_restart_ms: percentile(
            &mut samples.iter().map(|run| run.ice_ms).collect::<Vec<_>>(),
            50.0,
        ),
        first_frame_ms: percentile(
            &mut samples.iter().map(|run| run.frame_ms).collect::<Vec<_>>(),
            50.0,
        ),
        rss_mb: rss_after as f64 / (1024.0 * 1024.0),
        cpu_pct,
    }))
}

fn one_run(lib: &str) -> Result<Run, String> {
    let room = signal::serve_one_room().map_err(|err| err.to_string())?;
    let left = common::peer_by_name(lib).map_err(|err| err.to_string())?;
    let right = common::peer_by_name(lib).map_err(|err| err.to_string())?;
    left.enable_test_video().map_err(|err| err.to_string())?;
    let url = room.url.clone();
    let started = Instant::now();
    // The video peer must be the offerer: the first signal client offers.
    let url_left = url.clone();
    let left_thread = thread::spawn(move || {
        let joined = left.connect(&url_left).map_err(|err| err.to_string());
        (left, joined)
    });
    while room.peers_connected() < 1 {
        if started.elapsed() > Duration::from_secs(10) {
            return Err("video peer did not join the signal room".into());
        }
        thread::sleep(Duration::from_millis(5));
    }
    let right_thread = thread::spawn(move || {
        let joined = right.connect(&url).map_err(|err| err.to_string());
        (right, joined)
    });
    let (left, left_res) = left_thread
        .join()
        .map_err(|_| "connect thread panicked".to_owned())?;
    let (right, right_res) = right_thread
        .join()
        .map_err(|_| "connect thread panicked".to_owned())?;
    left_res?;
    right_res?;
    // `connect` returns before a data-channel round trip. Time through the
    // first rpc so this is "offer sent → channel usable".
    left.send(CHANNEL_RPC, b"connect")
        .map_err(|err| format!("connect probe send: {err}"))?;
    let probe = right
        .recv_timeout(probe_wait())
        .map_err(|err| format!("connect probe: {err}"))?;
    if probe.channel != CHANNEL_RPC || probe.bytes != b"connect" {
        return Err("connect probe mismatch".into());
    }
    let connect_ms = elapsed_ms(started);
    let frame_ms = wait_frame(&left)?;

    let blob = vec![0x5a_u8; BLOB];
    let transfer = Instant::now();
    let (sent, received) = thread::scope(|scope| {
        let send_handle = scope.spawn(|| {
            left.send(CHANNEL_FILES, &blob)
                .map_err(|err| err.to_string())
        });
        let recv_handle = scope.spawn(|| recv_blob(&right, BLOB));
        (send_handle.join(), recv_handle.join())
    });
    sent.map_err(|_| "send thread panicked".to_owned())??;
    received.map_err(|_| "recv thread panicked".to_owned())??;
    let seconds = transfer.elapsed().as_secs_f64().max(0.001);
    let mbps = (BLOB as f64) / seconds / (1024.0 * 1024.0);

    let restart = Instant::now();
    left.ice_restart()
        .map_err(|err| format!("ice restart: {err}"))?;
    left.send(CHANNEL_RPC, b"restart")
        .map_err(|err| format!("restart probe send: {err}"))?;
    let deadline = Instant::now() + probe_wait();
    loop {
        let left_time = deadline.saturating_duration_since(Instant::now());
        if left_time.is_zero() {
            return Err("ice restart probe timed out".into());
        }
        let message = right
            .recv_timeout(left_time)
            .map_err(|err| format!("restart probe: {err}"))?;
        if message.channel == CHANNEL_RPC && message.bytes == b"restart" {
            break;
        }
    }
    let ice_ms = elapsed_ms(restart);

    Ok(Run {
        connect_ms,
        mbps,
        ice_ms,
        frame_ms,
        pauses: left.metrics().backpressure_pauses,
    })
}

fn wait_frame(peer: &std::sync::Arc<dyn Peer>) -> Result<f64, String> {
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        let ms = peer.metrics().first_frame_ms;
        if ms > 0 {
            return Ok(ms as f64);
        }
        if Instant::now() >= deadline {
            return Err("no video frame within 3s".into());
        }
        thread::sleep(Duration::from_millis(5));
    }
}

fn recv_blob(peer: &std::sync::Arc<dyn Peer>, len: usize) -> Result<(), String> {
    let deadline = Instant::now() + blob_wait();
    let mut got = 0_usize;
    while got < len {
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return Err(format!("file recv stalled at {got}"));
        }
        let message = peer
            .recv_timeout(left)
            .map_err(|err| format!("file recv: {err}"))?;
        if message.channel != CHANNEL_FILES || message.bytes.len() < 24 {
            continue;
        }
        got += message.bytes.len() - 24;
    }
    Ok(())
}

fn connect_storm(lib: &str, count: usize) -> Result<(usize, usize), String> {
    let mut ok = 0_usize;
    let mut failed = 0_usize;
    for index in 0..count {
        match connect_once(lib) {
            Ok(()) => ok += 1,
            Err(err) => {
                failed += 1;
                eprintln!("{lib} connect {} failed: {err}", index + 1);
            }
        }
    }
    Ok((ok, failed))
}

fn connect_once(lib: &str) -> Result<(), String> {
    let room = signal::serve_one_room().map_err(|err| err.to_string())?;
    let left = common::peer_by_name(lib).map_err(|err| err.to_string())?;
    let right = common::peer_by_name(lib).map_err(|err| err.to_string())?;
    let url = room.url.clone();
    let url_left = url.clone();
    let left_thread = thread::spawn(move || {
        let joined = left.connect(&url_left).map_err(|err| err.to_string());
        (left, joined)
    });
    let right_thread = thread::spawn(move || {
        let joined = right.connect(&url).map_err(|err| err.to_string());
        (right, joined)
    });
    let (left, left_res) = left_thread
        .join()
        .map_err(|_| "connect thread panicked".to_owned())?;
    let (right, right_res) = right_thread
        .join()
        .map_err(|_| "connect thread panicked".to_owned())?;
    left_res?;
    right_res?;
    left.send(CHANNEL_RPC, b"ok")
        .map_err(|err| err.to_string())?;
    let message = right
        .recv_timeout(Duration::from_secs(5))
        .map_err(|err| err.to_string())?;
    if message.bytes != b"ok" {
        return Err("probe mismatch".into());
    }
    Ok(())
}

fn percentile(values: &mut [f64], pct: f64) -> f64 {
    values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let rank = (pct / 100.0 * values.len() as f64).ceil() as usize;
    values[rank.saturating_sub(1).min(values.len() - 1)]
}

fn elapsed_ms(start: Instant) -> f64 {
    start.elapsed().as_secs_f64() * 1000.0
}

fn num(value: f64) -> String {
    if !value.is_finite() {
        panic!("non-finite measurement");
    }
    format!("{value:.4}")
}

fn results_path(name: &str) -> PathBuf {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("results");
    fs::create_dir_all(&dir).expect("results dir");
    dir.join(name)
}

fn arg_value(flag: &str) -> Option<String> {
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        if arg == flag {
            return args.next();
        }
    }
    None
}

fn usage() -> (u64, Duration) {
    let mut usage = unsafe { std::mem::zeroed::<libc::rusage>() };
    unsafe {
        libc::getrusage(libc::RUSAGE_SELF, &mut usage);
    }
    let rss = if cfg!(target_os = "macos") || cfg!(target_os = "ios") {
        usage.ru_maxrss as u64
    } else {
        (usage.ru_maxrss as u64).saturating_mul(1024)
    };
    let cpu = timeval(usage.ru_utime) + timeval(usage.ru_stime);
    (rss, cpu)
}

fn timeval(value: libc::timeval) -> Duration {
    Duration::new(
        value.tv_sec as u64,
        (value.tv_usec as u32).saturating_mul(1000),
    )
}
