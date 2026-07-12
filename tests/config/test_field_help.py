"""Tests for packaged config field help loading."""

from __future__ import annotations

from sevn.config.field_help import field_help_for, load_config_field_help, urls_in_help_text


def test_load_config_field_help_includes_tunnel_token() -> None:
    help_map = load_config_field_help()
    entry = help_map.get("infrastructure.tunnel.cloudflare.token")
    assert entry is not None
    assert "how_to_collect" in entry
    # Collection hint mentions cloudflared regardless of the dashboard-flow wording
    # (the copy was reworded to the "Install as service" flow in the tunnel work).
    assert "cloudflared" in entry["how_to_collect"].lower()


def test_field_help_for_known_tunnel_path() -> None:
    entry = field_help_for("infrastructure.tunnel.ngrok.authtoken")
    assert entry is not None
    assert "ngrok" in entry["long_description"].lower()


def test_urls_in_help_text_deduplicates() -> None:
    text = "See https://example.com/a and https://example.com/a again"
    assert urls_in_help_text(text) == ("https://example.com/a",)
