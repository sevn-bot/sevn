//! Relay allocation for S-TURN.
//!
//! str0m gathers no relay candidates itself. This module allocates one
//! Cloudflare relay and feeds str0m only the unwrapped peer datagrams, with
//! the receive destination set to that relay address. TLS carries self-delimited
//! TURN messages (no ICE-TCP length prefix).

use std::collections::HashSet;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::{Duration, Instant};

use bytes::BytesMut;
use rtc_shared::error::Error as TurnError;
use rtc_shared::turn_framing::TurnStreamDecoder;
use rtc_shared::{TransportContext, TransportMessage, TransportProtocol};
use rtc_turn::client::{Client, ClientConfig, Event};
use rustls::pki_types::ServerName;
use sansio::Protocol;
use tokio::io::{AsyncReadExt, AsyncWriteExt, ReadHalf, WriteHalf, split};
use tokio::net::{TcpStream, UdpSocket};
use tokio::sync::mpsc;
use tokio_rustls::TlsConnector;
use tokio_rustls::client::TlsStream;

use super::Error;

pub(super) struct Creds {
    url: String,
    username: String,
    password: String,
}

pub(super) struct Bringup {
    pub side: TurnSide,
    pub sock: Arc<UdpSocket>,
    pub net_rx: mpsc::UnboundedReceiver<Vec<u8>>,
    pub tls: bool,
}

pub(super) struct TurnSide {
    client: Client,
    relayed: SocketAddr,
    server: SocketAddr,
    local: SocketAddr,
    udp: Option<Arc<UdpSocket>>,
    tls_write: Option<WriteHalf<TlsStream<TcpStream>>>,
    permitted: HashSet<SocketAddr>,
    pending: HashSet<SocketAddr>,
}

struct Target {
    secure: bool,
    host: String,
    port: u16,
}

pub(super) fn credentials() -> Result<Option<Creds>, Error> {
    let Ok(url) = std::env::var("SPIKE_TURN_URL") else {
        return Ok(None);
    };
    if url.is_empty() {
        return Ok(None);
    }
    let username = std::env::var("SPIKE_TURN_USERNAME").unwrap_or_default();
    let password = std::env::var("SPIKE_TURN_CREDENTIAL").unwrap_or_default();
    if username.is_empty() || password.is_empty() {
        return Err(Error::Failed("relay measurement env is unset".into()));
    }
    Ok(Some(Creds {
        url,
        username,
        password,
    }))
}

pub(super) async fn allocate(creds: Creds) -> Result<Bringup, Error> {
    let target = parse_target(&creds.url)?;
    if target.secure {
        allocate_tls(&target, creds.username, creds.password).await
    } else {
        allocate_udp(&target, creds.username, creds.password).await
    }
}

impl TurnSide {
    pub(super) fn relayed(&self) -> SocketAddr {
        self.relayed
    }

    pub(super) fn local(&self) -> SocketAddr {
        self.local
    }

    pub(super) fn server(&self) -> SocketAddr {
        self.server
    }

    pub(super) fn permit(&mut self, peer: SocketAddr) -> Result<(), Error> {
        if self.permitted.contains(&peer) || self.pending.contains(&peer) {
            return Ok(());
        }
        self.pending.insert(peer);
        let created = {
            let mut allocation = self
                .client
                .relay(self.relayed)
                .map_err(|_| Error::Failed("relay allocation failed".into()))?;
            allocation.create_permission(Instant::now(), peer)
        };
        match created {
            Ok(None) => {
                self.pending.remove(&peer);
                self.permitted.insert(peer);
                Ok(())
            }
            Ok(Some(_)) => Ok(()),
            Err(_) => {
                self.pending.remove(&peer);
                Err(Error::Failed("relay permission failed".into()))
            }
        }
    }

    pub(super) fn send_payload(&mut self, peer: SocketAddr, bytes: &[u8]) -> Result<(), Error> {
        if !self.permitted.contains(&peer) {
            self.permit(peer)?;
            return Ok(());
        }
        let sent = {
            let mut allocation = self
                .client
                .relay(self.relayed)
                .map_err(|_| Error::Failed("relay allocation failed".into()))?;
            allocation.send_to(Instant::now(), bytes, peer)
        };
        if let Err(err) = sent {
            if err == TurnError::ErrNoPermission {
                self.permitted.remove(&peer);
                self.permit(peer)?;
                return Ok(());
            }
            return Err(Error::Failed("relay send failed".into()));
        }
        Ok(())
    }

    pub(super) fn ingest(&mut self, data: &[u8]) -> Result<Vec<(SocketAddr, Vec<u8>)>, Error> {
        let proto = if self.tls_write.is_some() {
            TransportProtocol::TCP
        } else {
            TransportProtocol::UDP
        };
        if ingest_raw(&mut self.client, self.local, self.server, proto, data).is_err() {
            return Ok(Vec::new());
        }
        let mut inbound = Vec::new();
        while let Some(event) = Protocol::poll_event(&mut self.client) {
            match event {
                Event::DataIndicationOrChannelData(_, peer, bytes) => {
                    inbound.push((peer, bytes.to_vec()));
                }
                Event::CreatePermissionResponse(_, peer) => {
                    self.pending.remove(&peer);
                    self.permitted.insert(peer);
                }
                Event::CreatePermissionError(_, _) => {
                    self.pending.clear();
                }
                Event::AllocateError(_, _) => {
                    return Err(Error::Failed("relay allocation failed".into()));
                }
                _ => {}
            }
        }
        Ok(inbound)
    }

    pub(super) async fn flush(&mut self) -> Result<(), Error> {
        let _ = Protocol::handle_timeout(&mut self.client, Instant::now());
        let packets = drain_writes(&mut self.client);
        if let Some(write) = &mut self.tls_write {
            for packet in &packets {
                write
                    .write_all(packet)
                    .await
                    .map_err(|_| Error::Failed("relay send failed".into()))?;
            }
            if !packets.is_empty() {
                write
                    .flush()
                    .await
                    .map_err(|_| Error::Failed("relay send failed".into()))?;
            }
        } else if let Some(sock) = &self.udp {
            for packet in &packets {
                sock.send(packet)
                    .await
                    .map_err(|_| Error::Failed("relay send failed".into()))?;
            }
        }
        Ok(())
    }
}

async fn allocate_udp(
    target: &Target,
    username: String,
    password: String,
) -> Result<Bringup, Error> {
    let server = resolve(target).await?;
    let sock = UdpSocket::bind("0.0.0.0:0")
        .await
        .map_err(|_| Error::Failed("relay allocation failed".into()))?;
    sock.connect(server)
        .await
        .map_err(|_| Error::Failed("relay allocation failed".into()))?;
    let local = sock
        .local_addr()
        .map_err(|_| Error::Failed("relay allocation failed".into()))?;
    let mut client = make_client(local, server, username, password, TransportProtocol::UDP)?;
    client
        .allocate(Instant::now())
        .map_err(|_| Error::Failed("relay allocation failed".into()))?;
    let sock = Arc::new(sock);
    let relayed = wait_udp(&mut client, &sock, local, server).await?;
    let (tx, net_rx) = mpsc::unbounded_channel();
    drop(tx);
    Ok(Bringup {
        side: TurnSide {
            client,
            relayed,
            server,
            local,
            udp: Some(Arc::clone(&sock)),
            tls_write: None,
            permitted: HashSet::new(),
            pending: HashSet::new(),
        },
        sock,
        net_rx,
        tls: false,
    })
}

async fn wait_udp(
    client: &mut Client,
    sock: &UdpSocket,
    local: SocketAddr,
    server: SocketAddr,
) -> Result<SocketAddr, Error> {
    let deadline = Instant::now() + Duration::from_secs(15);
    let mut buf = vec![0_u8; 2048];
    loop {
        let packets = drain_writes(client);
        for packet in &packets {
            sock.send(packet)
                .await
                .map_err(|_| Error::Failed("relay allocation failed".into()))?;
        }
        if let Some(addr) = poll_alloc(client)? {
            return Ok(addr);
        }
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return Err(Error::Failed("relay allocation failed".into()));
        }
        match tokio::time::timeout(left.min(Duration::from_millis(200)), sock.recv(&mut buf)).await
        {
            Ok(Ok(size)) => {
                let _ = ingest_raw(client, local, server, TransportProtocol::UDP, &buf[..size]);
            }
            Ok(Err(_)) => return Err(Error::Failed("relay allocation failed".into())),
            Err(_) => {
                let _ = Protocol::handle_timeout(client, Instant::now());
            }
        }
    }
}

async fn allocate_tls(
    target: &Target,
    username: String,
    password: String,
) -> Result<Bringup, Error> {
    let server = resolve(target).await?;
    let tcp = TcpStream::connect(server)
        .await
        .map_err(|_| Error::Failed("relay tls failed".into()))?;
    tcp.set_nodelay(true)
        .map_err(|_| Error::Failed("relay tls failed".into()))?;
    let local = tcp
        .local_addr()
        .map_err(|_| Error::Failed("relay tls failed".into()))?;
    let name = ServerName::try_from(target.host.clone())
        .map_err(|_| Error::Failed("relay tls failed".into()))?;
    let connector = TlsConnector::from(Arc::new(tls_config()?));
    let mut stream = connector
        .connect(name, tcp)
        .await
        .map_err(|_| Error::Failed("relay tls failed".into()))?;
    let mut client = make_client(local, server, username, password, TransportProtocol::TCP)?;
    client
        .allocate(Instant::now())
        .map_err(|_| Error::Failed("relay allocation failed".into()))?;
    let mut decoder = TurnStreamDecoder::new();
    let mut buf = vec![0_u8; 8192];
    let deadline = Instant::now() + Duration::from_secs(15);
    let mut read_bytes = 0_usize;
    let relayed = loop {
        write_tls(&mut client, &mut stream).await?;
        if let Some(addr) = poll_alloc(&mut client)? {
            break addr;
        }
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            let reason = if read_bytes == 0 {
                "relay tls failed"
            } else {
                "relay allocation failed"
            };
            return Err(Error::Failed(reason.into()));
        }
        match tokio::time::timeout(left.min(Duration::from_millis(200)), stream.read(&mut buf))
            .await
        {
            Ok(Ok(0)) | Ok(Err(_)) => return Err(Error::Failed("relay allocation failed".into())),
            Ok(Ok(size)) => {
                read_bytes = read_bytes.saturating_add(size);
                decoder.extend_from_slice(&buf[..size]);
                while let Some(frame) = decoder
                    .next_message()
                    .map_err(|_| Error::Failed("relay allocation failed".into()))?
                {
                    let _ = ingest_raw(&mut client, local, server, TransportProtocol::TCP, &frame);
                }
            }
            Err(_) => {
                let _ = Protocol::handle_timeout(&mut client, Instant::now());
            }
        }
    };
    let (read, write) = split(stream);
    let (tx, net_rx) = mpsc::unbounded_channel();
    tokio::spawn(read_tls(read, decoder, tx));
    let sock = Arc::new(
        UdpSocket::bind("127.0.0.1:0")
            .await
            .map_err(|_| Error::Failed("relay allocation failed".into()))?,
    );
    Ok(Bringup {
        side: TurnSide {
            client,
            relayed,
            server,
            local,
            udp: None,
            tls_write: Some(write),
            permitted: HashSet::new(),
            pending: HashSet::new(),
        },
        sock,
        net_rx,
        tls: true,
    })
}

async fn write_tls(client: &mut Client, stream: &mut TlsStream<TcpStream>) -> Result<(), Error> {
    let packets = drain_writes(client);
    for packet in &packets {
        stream
            .write_all(packet)
            .await
            .map_err(|_| Error::Failed("relay allocation failed".into()))?;
    }
    if !packets.is_empty() {
        stream
            .flush()
            .await
            .map_err(|_| Error::Failed("relay allocation failed".into()))?;
    }
    Ok(())
}

async fn read_tls(
    mut read: ReadHalf<TlsStream<TcpStream>>,
    mut decoder: TurnStreamDecoder,
    tx: mpsc::UnboundedSender<Vec<u8>>,
) {
    let mut buf = vec![0_u8; 8192];
    loop {
        match read.read(&mut buf).await {
            Ok(0) | Err(_) => break,
            Ok(size) => {
                decoder.extend_from_slice(&buf[..size]);
                loop {
                    match decoder.next_message() {
                        Ok(Some(frame)) => {
                            if tx.send(frame).is_err() {
                                return;
                            }
                        }
                        Ok(None) => break,
                        Err(_) => return,
                    }
                }
            }
        }
    }
}

fn make_client(
    local: SocketAddr,
    server: SocketAddr,
    username: String,
    password: String,
    proto: TransportProtocol,
) -> Result<Client, Error> {
    let provider = rtc_turn::crypto::default_provider()
        .map_err(|_| Error::Failed("relay allocation failed".into()))?;
    Client::new(
        ClientConfig {
            stun_serv_addr: String::new(),
            turn_serv_addr: server.to_string(),
            local_addr: local,
            transport_protocol: proto,
            username,
            password,
            realm: String::new(),
            software: String::new(),
            rto_in_ms: 0,
            allocation_refresh_interval_cap: None,
        },
        provider,
    )
    .map_err(|_| Error::Failed("relay allocation failed".into()))
}

fn drain_writes(client: &mut Client) -> Vec<BytesMut> {
    let _ = Protocol::handle_timeout(client, Instant::now());
    let mut packets = Vec::new();
    while let Some(transmit) = Protocol::poll_write(client) {
        packets.push(transmit.message);
    }
    packets
}

fn poll_alloc(client: &mut Client) -> Result<Option<SocketAddr>, Error> {
    while let Some(event) = Protocol::poll_event(client) {
        match event {
            Event::AllocateResponse(_, addr) => return Ok(Some(addr)),
            Event::AllocateError(_, _) | Event::TransactionTimeout(_) => {
                return Err(Error::Failed("relay allocation failed".into()));
            }
            _ => {}
        }
    }
    Ok(None)
}

fn ingest_raw(
    client: &mut Client,
    local: SocketAddr,
    server: SocketAddr,
    proto: TransportProtocol,
    data: &[u8],
) -> Result<(), Error> {
    Protocol::handle_read(
        client,
        TransportMessage {
            now: Instant::now(),
            transport: TransportContext {
                local_addr: local,
                peer_addr: server,
                transport_protocol: proto,
                ecn: None,
            },
            message: BytesMut::from(data),
        },
    )
    .map_err(|_| Error::Failed("relay allocation failed".into()))
}

fn parse_target(url: &str) -> Result<Target, Error> {
    let (secure, rest) = if let Some(rest) = url.strip_prefix("turns:") {
        (true, rest)
    } else if let Some(rest) = url.strip_prefix("turn:") {
        (false, rest)
    } else {
        return Err(Error::Failed("relay url scheme".into()));
    };
    let (hostport, query) = rest.split_once('?').unwrap_or((rest, ""));
    let hostport = hostport
        .rsplit_once('@')
        .map(|(_, host)| host)
        .unwrap_or(hostport);
    if !secure && query.contains("transport=tcp") {
        return Err(Error::Failed("relay transport".into()));
    }
    let (host, port) = hostport
        .rsplit_once(':')
        .ok_or_else(|| Error::Failed("relay url port".into()))?;
    let port = port
        .parse()
        .map_err(|_| Error::Failed("relay url port".into()))?;
    if host.is_empty() {
        return Err(Error::Failed("relay url host".into()));
    }
    Ok(Target {
        secure,
        host: host.to_owned(),
        port,
    })
}

async fn resolve(target: &Target) -> Result<SocketAddr, Error> {
    let addrs = tokio::net::lookup_host((target.host.as_str(), target.port))
        .await
        .map_err(|_| Error::Failed("relay dns failed".into()))?;
    for addr in addrs {
        if addr.is_ipv4() {
            return Ok(addr);
        }
    }
    Err(Error::Failed("relay dns failed".into()))
}

fn tls_config() -> Result<rustls::ClientConfig, Error> {
    let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();
    let mut roots = rustls::RootCertStore::empty();
    roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    Ok(rustls::ClientConfig::builder()
        .with_root_certificates(roots)
        .with_no_client_auth())
}
