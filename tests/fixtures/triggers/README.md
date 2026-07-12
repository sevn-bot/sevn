# Trigger fixtures

Golden webhook bodies for HTTP integration tests should live here. Prefer faker-style
tokens only — no production signing secrets (`specs/30-non-interactive-triggers.md` §10.5).
Vectors for GitHub HMAC are computed inline in `tests/triggers/test_webhook_github.py`.
