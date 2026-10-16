//! One-room WebSocket signalling for the spike (offer / answer / candidate).
//!
//! `serve_one_room` is filled in with the peer wave. Dropping [`Room`] stops
//! the listener. The URL it publishes is the `signal_url` both peers connect to.

use std::fmt;

#[derive(Debug)]
pub struct Room {
    pub url: String,
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

pub fn serve_one_room() -> Result<Room, Error> {
    unimplemented!("serve_one_room")
}
