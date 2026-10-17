use std::env;
use std::process::ExitCode;

#[link(name = "CoreGraphics", kind = "framework")]
unsafe extern "C" {
    fn CGPreflightScreenCaptureAccess() -> bool;
}

#[link(name = "ApplicationServices", kind = "framework")]
unsafe extern "C" {
    fn AXIsProcessTrusted() -> bool;
}

fn word(value: bool) -> &'static str {
    if value {
        "true"
    } else {
        "false"
    }
}

fn probe() {
    let screen = unsafe { CGPreflightScreenCaptureAccess() };
    let trusted = unsafe { AXIsProcessTrusted() };
    println!("screen_capture={}", word(screen));
    println!("accessibility={}", word(trusted));
}

fn main() -> ExitCode {
    match env::args().nth(1).as_deref() {
        Some("--health") => ExitCode::SUCCESS,
        Some("--probe-tcc") => {
            probe();
            ExitCode::SUCCESS
        }
        _ => {
            eprintln!("usage: sevn-helper --health | --probe-tcc");
            ExitCode::from(2)
        }
    }
}
