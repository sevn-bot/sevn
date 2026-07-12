---
name: yt-dlp
description: Download video/audio and metadata with yt-dlp (YouTube, Vimeo, X, TikTok, and allowlisted hosts).
version: "1.0.0"
see_also:
  - sandbox_exec
  - get_page_content
  - process
egress:
  - youtube.com
  - youtu.be
  - googlevideo.com
  - ytimg.com
  - youtubei.googleapis.com
  - vimeo.com
  - player.vimeo.com
  - twitter.com
  - x.com
  - twimg.com
  - video.twimg.com
  - tiktok.com
  - tiktokcdn.com
  - tiktokv.com
  - twitch.tv
  - ttvnw.net
  - jtvnw.net
  - instagram.com
  - cdninstagram.com
  - facebook.com
  - fbcdn.net
  - soundcloud.com
  - redd.it
  - reddit.com
  - v.redd.it
  - dailymotion.com
  - archive.org
  - streamable.com
  - rumble.com
scripts:
  - path: scripts/download.py
    description: Download video or audio to a workspace directory (allowlisted flags only).
    args_overview: "--url URL --out REL_DIR [--audio-only] [--audio-format mp3|m4a|aac|wav|flac|opus] [--write-subs] [--dry-run]"
    abortable: true
  - path: scripts/metadata.py
    description: Export compact JSON metadata without downloading media.
    args_overview: "--url URL [--dry-run]"
    abortable: true
---

# yt-dlp

yt-dlp is a powerful open-source command-line video/audio downloader. It's a fork of youtube-dl with tons of additional features.

## Core Capabilities

| Feature | What it does |
|---|---|
| Video download | Download videos from YouTube, Vimeo, Twitter/X, TikTok, and allowlisted hosts |
| Audio extraction | Pull audio as MP3, AAC, FLAC, WAV, Opus, etc. |
| Subtitles & captions | Download .vtt, .srt, .ass auto-generated or uploaded subtitles |
| Thumbnails | Download video thumbnails in various sizes |
| Playlists & channels | Download entire playlists or channels in one command |
| Live streams | Download ongoing or past live streams |
| NFO/metadata | Export video metadata (title, description, views, upload date) |

## Advanced Features

- Resume interrupted downloads — --fragmented + partial downloads
- Merge formats — download video + audio separately and merge (e.g. best video + best audio → MKV)
- SponsorBlock integration — skip/mark sponsor segments automatically
- Chapters — download chapter markers as timestamps
- Comments — extract YouTube comments (with limitations)
- Age-gated & private videos — works with cookies for auth
- Custom output templates — --output "%(playlist)s/%(title)s.%(ext)s"
- Rate limiting — throttle download speed with -r
- Proxy support — route downloads through a proxy

## Common Commands

```bash
# Basic download
yt-dlp "https://www.youtube.com/watch?v=..."

# Best audio as MP3
yt-dlp -x --audio-format mp3 "URL"

# Download playlist, best quality
yt-dlp -f "bv+ba/b" --embed-thumbnail "PLAYLIST_URL"

# Download with subtitles + metadata
yt-dlp --write-subs --write-auto-subs --embed-metadata "URL"

# Skip sponsor segments
yt-dlp --sponsorblock-remove all "URL"
```

## yt-dlp vs youtube-dl

yt-dlp adds ~1000+ improvements over youtube-dl — faster extraction, better regex patterns for modern sites, more format options, and better metadata handling. It's the go-to fork these days.

## sevn integration notes

- Use **allowlisted wrapper scripts** in `scripts/`; do not pass unvalidated user strings directly as extra CLI args.
- URL hosts must match the **`egress:`** frontmatter list (enforced in Python before subprocess).
- Respect **site ToS** and **rate limits**; use workspace **egress proxy** / `HTTP_PROXY` per `specs/08-sandbox.md`.
- Large downloads write under workspace paths and return a compact descriptor to the model.
- Install optional dependency when needed:

```bash
uv sync --extra yt-dlp
```

Set **`SEVN_WORKSPACE`** (injected by the skill runner). Output paths must stay under the workspace root.
