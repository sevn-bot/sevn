# ESPN CLI Reference (`espn-pp-cli`)

> Vendored from upstream `cli-skills/pp-espn/SKILL.md` — run `scripts/sync_printing_press_starter_pack.sh` to refresh.

**Binary:** `espn-pp-cli`
**Go module:** `github.com/mvanhorn/printing-press-library/library/media-and-entertainment/espn/cmd/espn-pp-cli`
**License:** Apache-2.0
**Author:** Matt Van Horn

## Install

```bash
npx -y @mvanhorn/printing-press-library install espn --cli-only
# or: go install github.com/mvanhorn/printing-press-library/library/media-and-entertainment/espn/cmd/espn-pp-cli@latest
```

## Key commands

| Command | Purpose |
|---------|---------|
| `news <sport> <league> [--limit N]` | Latest news articles for a sport + league (default 25) |
| `today` | Scores across all major sports in one call |
| `scoreboard <league>` | Live scoreboard with date filtering |
| `standings <league>` | Conference/division standings |
| `summary --event <id>` | Detailed game summary (box score, odds, win probability) |
| `boxscore <event_id>` | Per-player box score |
| `plays --event <id>` | Play-by-play feed |
| `leaders [--category]` | Statistical leaders |
| `trending` | Most-followed athletes and teams |
| `dashboard` | Favorite teams from config |
| `watch --event <id>` | Live score updates (polls every 30s) |
| `rankings <league>` | Poll rankings (NCAAF/NCAAM) |
| `injuries <league>` | Active injury report |
| `h2h --sport --league <t1> <t2>` | Head-to-head detail |

## Example invocations

```bash
# Tonight's NBA scores
espn-pp-cli scoreboard nba --agent

# NFL standings
espn-pp-cli standings nfl --agent

# Game summary
espn-pp-cli summary --event 401671793 --agent

# Cross-league today
espn-pp-cli today --agent

# Latest news for a sport + league (NOT a free-text query)
espn-pp-cli news basketball nba --limit 10 --agent
espn-pp-cli news football nfl --agent

# World Cup / international soccer news
espn-pp-cli news soccer fifa.world --limit 10 --agent
```

> **News takes `<sport> <league>`, not a natural-language phrase.** `news "World Cup
> news"` fails with `unknown command`. Use `news soccer fifa.world` (World Cup),
> `news soccer eng.1` (EPL), `news basketball nba`, `news football nfl`, etc.

## Agent mode

Add `--agent` to any command: `--json --compact --no-input --no-color --yes`.

## Leagues

Scoreboard/standings league slugs: `nfl`, `nba`, `mlb`, `nhl`, `ncaaf`, `ncaam`,
`mls`, `epl`, `wnba`, `nascar`.

`news` uses `<sport> <league>` pairs, e.g. `basketball nba`, `football nfl`,
`baseball mlb`, `hockey nhl`, `soccer fifa.world` (World Cup), `soccer eng.1` (EPL).
