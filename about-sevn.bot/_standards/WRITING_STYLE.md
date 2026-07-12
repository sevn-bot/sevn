# Writing style for about-sevn.bot

Audience: people who use sevn.bot, not engineers maintaining the codebase.

## Voice

- Second person ("you", "your").
- Short sentences. Say what happens and what to do next.
- Use product names users see: Telegram, Mission Control, Skills, Tools.

## Forbidden in user-visible pages

- Links or mentions of internal engineering folders or documents.
- Python module paths (`src/...`).
- Spec numbers, wave labels, or ADR references.

## Hand-editing workflow

1. Edit `_sources/<page>.yaml` for prose.
2. Run `make about-site` to regenerate HTML.
3. Commit both YAML and generated HTML together.

Catalog pages (Telegram menu, tools, skills, settings table) pull live data from the product; only edit their intro text in YAML unless you add overrides in the same file.
