//! One-room WebSocket signalling for the spike (offer / answer / candidate).
//!
//! Dropping [`Room`] stops the listener. The URL it publishes is the `signal_url`
//! both peers connect to. The first client is the offerer; the second is the answerer.
//! Messages sent before the other client connects are queued and flushed on join.

use std::fmt;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};

use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::net::TcpListener;
use tokio::sync::{mpsc, oneshot};
use tokio_tungstenite::tungstenite::Message;

#[derive(Debug)]
pub struct Room {
    pub url: String,
    peers: Arc<AtomicUsize>,
    shutdown: Option<oneshot::Sender<()>>,
    thread: Option<JoinHandle<()>>,
}

impl Room {
    /// Clients that have completed the WebSocket handshake. The spike harness
    /// waits for `1` before opening the browser, so the Rust peer is the offerer.
    pub fn peers_connected(&self) -> usize {
        self.peers.load(Ordering::SeqCst)
    }
}

impl Drop for Room {
    fn drop(&mut self) {
        if let Some(tx) = self.shutdown.take() {
            let _ = tx.send(());
        }
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    Failed(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Failed(message) => f.write_str(message),
        }
    }
}

impl std::error::Error for Error {}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Sig {
    Role {
        role: String,
    },
    Offer {
        sdp: String,
    },
    Answer {
        sdp: String,
    },
    Candidate {
        candidate: String,
        #[serde(default, rename = "sdpMid")]
        sdp_mid: Option<String>,
        #[serde(default, rename = "sdpMLineIndex")]
        sdp_mline_index: Option<u16>,
    },
}

struct RoomState {
    slots: [Option<mpsc::UnboundedSender<String>>; 2],
    pending: [Vec<String>; 2],
}

impl RoomState {
    /// Claim a slot, queue the role message, then flush anything already relayed.
    /// The role is first so the client can read it before the offer.
    fn claim(&mut self, tx: mpsc::UnboundedSender<String>, hello: String) -> Option<usize> {
        let index = self.slots.iter().position(|slot| slot.is_none())?;
        if tx.send(hello).is_err() {
            return None;
        }
        let queued = std::mem::take(&mut self.pending[index]);
        for message in queued {
            if tx.send(message).is_err() {
                self.slots[index] = None;
                return None;
            }
        }
        self.slots[index] = Some(tx);
        Some(index)
    }

    fn relay(&mut self, from: usize, text: String) {
        let to = 1 - from;
        if let Some(tx) = &self.slots[to] {
            let _ = tx.send(text);
        } else {
            self.pending[to].push(text);
        }
    }

    fn remove(&mut self, index: usize) {
        self.slots[index] = None;
    }
}

pub fn serve_one_room() -> Result<Room, Error> {
    let (url_tx, url_rx) = std::sync::mpsc::channel();
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let peers = Arc::new(AtomicUsize::new(0));
    let peers_bg = Arc::clone(&peers);

    let thread = thread::Builder::new()
        .name("spike-signal".into())
        .spawn(move || {
            let rt = match tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
            {
                Ok(rt) => rt,
                Err(err) => {
                    let _ = url_tx.send(Err(err.to_string()));
                    return;
                }
            };
            rt.block_on(run_server(url_tx, shutdown_rx, peers_bg));
        })
        .map_err(|err| Error::Failed(err.to_string()))?;

    let url = match url_rx.recv() {
        Ok(Ok(url)) => url,
        Ok(Err(err)) => return Err(Error::Failed(err)),
        Err(_) => return Err(Error::Failed("signal server stopped before bind".into())),
    };

    Ok(Room {
        url,
        peers,
        shutdown: Some(shutdown_tx),
        thread: Some(thread),
    })
}

async fn run_server(
    url_tx: std::sync::mpsc::Sender<Result<String, String>>,
    mut shutdown_rx: oneshot::Receiver<()>,
    peers: Arc<AtomicUsize>,
) {
    let listener = match TcpListener::bind("127.0.0.1:0").await {
        Ok(listener) => listener,
        Err(err) => {
            let _ = url_tx.send(Err(err.to_string()));
            return;
        }
    };
    let port = match listener.local_addr() {
        Ok(addr) => addr.port(),
        Err(err) => {
            let _ = url_tx.send(Err(err.to_string()));
            return;
        }
    };
    if url_tx.send(Ok(format!("ws://127.0.0.1:{port}"))).is_err() {
        return;
    }

    let state = Arc::new(Mutex::new(RoomState {
        slots: [None, None],
        pending: [Vec::new(), Vec::new()],
    }));
    let mut tasks = Vec::new();

    loop {
        tokio::select! {
            _ = &mut shutdown_rx => break,
            accepted = listener.accept() => {
                let Ok((stream, _)) = accepted else { continue };
                let state = Arc::clone(&state);
                let peers = Arc::clone(&peers);
                tasks.push(tokio::spawn(async move {
                    if let Err(err) = handle_client(stream, state, peers).await {
                        spike_log(&format!("signal client: {err}"));
                    }
                }));
            }
        }
    }

    for task in tasks {
        task.abort();
    }
}

async fn handle_client(
    stream: tokio::net::TcpStream,
    state: Arc<Mutex<RoomState>>,
    peers: Arc<AtomicUsize>,
) -> Result<(), Error> {
    let ws = tokio_tungstenite::accept_async(stream)
        .await
        .map_err(|err| Error::Failed(err.to_string()))?;
    let (mut write, mut read) = ws.split();
    let (tx, mut rx) = mpsc::unbounded_channel::<String>();

    let index = {
        let mut guard = state.lock().expect("signal state");
        let next = guard.slots.iter().position(|slot| slot.is_none());
        let Some(next) = next else {
            return Err(Error::Failed("signal room is full".into()));
        };
        let role = if next == 0 { "offerer" } else { "answerer" };
        let hello = serde_json::to_string(&Sig::Role {
            role: role.to_owned(),
        })
        .map_err(|err| Error::Failed(err.to_string()))?;
        guard
            .claim(tx.clone(), hello)
            .ok_or_else(|| Error::Failed("signal room is full".into()))?
    };
    peers.fetch_add(1, Ordering::SeqCst);

    let writer = tokio::spawn(async move {
        while let Some(text) = rx.recv().await {
            if write.send(Message::text(text)).await.is_err() {
                break;
            }
        }
    });

    while let Some(message) = read.next().await {
        let message = match message {
            Ok(message) => message,
            Err(_) => break,
        };
        if message.is_close() {
            break;
        }
        let Ok(text) = message.to_text() else {
            continue;
        };
        if text.is_empty() {
            continue;
        }
        state
            .lock()
            .expect("signal state")
            .relay(index, text.to_owned());
    }

    state.lock().expect("signal state").remove(index);
    peers.fetch_sub(1, Ordering::SeqCst);
    writer.abort();
    Ok(())
}

/// A connected signalling client. `role` is `offerer` or `answerer`.
pub struct Conn {
    pub role: String,
    tx: mpsc::UnboundedSender<String>,
    rx: mpsc::UnboundedReceiver<String>,
}

impl Conn {
    pub fn send(&self, message: &Sig) -> Result<(), Error> {
        queue(&self.tx, message)
    }

    /// Clone of the outgoing queue so ICE callbacks can signal without `&mut Conn`.
    pub fn outgoing(&self) -> mpsc::UnboundedSender<String> {
        self.tx.clone()
    }

    pub fn into_split(
        self,
    ) -> (
        String,
        mpsc::UnboundedSender<String>,
        mpsc::UnboundedReceiver<String>,
    ) {
        (self.role, self.tx, self.rx)
    }

    pub async fn recv(&mut self) -> Result<Sig, Error> {
        let text = self
            .rx
            .recv()
            .await
            .ok_or_else(|| Error::Failed("signal connection closed".into()))?;
        serde_json::from_str(&text).map_err(|err| Error::Failed(err.to_string()))
    }
}

pub fn queue(tx: &mpsc::UnboundedSender<String>, message: &Sig) -> Result<(), Error> {
    let text = serde_json::to_string(message).map_err(|err| Error::Failed(err.to_string()))?;
    tx.send(text)
        .map_err(|_| Error::Failed("signal connection closed".into()))
}

pub async fn connect(url: &str) -> Result<Conn, Error> {
    let (ws, _) = tokio_tungstenite::connect_async(url)
        .await
        .map_err(|err| Error::Failed(err.to_string()))?;
    let (mut write, mut read) = ws.split();
    let (out_tx, mut out_rx) = mpsc::unbounded_channel::<String>();
    let (in_tx, mut in_rx) = mpsc::unbounded_channel::<String>();

    tokio::spawn(async move {
        while let Some(text) = out_rx.recv().await {
            if write.send(Message::text(text)).await.is_err() {
                break;
            }
        }
    });
    tokio::spawn(async move {
        while let Some(message) = read.next().await {
            let Ok(message) = message else { break };
            if message.is_close() {
                break;
            }
            if let Ok(text) = message.to_text()
                && !text.is_empty()
                && in_tx.send(text.to_owned()).is_err()
            {
                break;
            }
        }
    });

    let first = in_rx
        .recv()
        .await
        .ok_or_else(|| Error::Failed("signal closed before role".into()))?;
    let role = match serde_json::from_str::<Sig>(&first) {
        Ok(Sig::Role { role }) => role,
        Ok(other) => {
            return Err(Error::Failed(format!(
                "expected role message, got {other:?}"
            )));
        }
        Err(err) => return Err(Error::Failed(err.to_string())),
    };

    Ok(Conn {
        role,
        tx: out_tx,
        rx: in_rx,
    })
}

fn spike_log(message: &str) {
    if std::env::var_os("SPIKE_DEBUG").is_some() {
        eprintln!("spike-signal: {message}");
    }
}
