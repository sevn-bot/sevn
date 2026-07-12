# Telegram test fixtures

Golden payloads and sample `Update` JSON blobs for `tests/channels/test_telegram_*.py` live next to this README.

- **Markdown escape goldens** (`markdown_escape_*.txt`) — expected output of the adapter’s Markdown-escape step used before `sendMessage` / `editMessageText` (`specs/18-channel-telegram.md` §10.4).

Forum topic service messages (`forum_topic_created` / `forum_topic_edited`) should mirror Bot API field names so `TelegramAdapter` topic-name caching stays aligned with `specs/18-channel-telegram.md` §3.1.
