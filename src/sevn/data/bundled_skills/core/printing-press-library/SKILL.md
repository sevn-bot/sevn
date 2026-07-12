---
name: printing-press-library
description: Starter-pack Printing Press CLIs — ESPN, flights, movies, recipes (Go binaries on PATH).
version: "1.0.0"
see_also:
  - load_skill
  - run_skill_script
  - web_fetch
egress:
  - espn.com
  - site.web.api.espn.com
  - sports.core.api.espn.com
  - kayak.com
  - google.com
  - flights.google.com
  - flightaware.com
  - flightxml.flightaware.com
  - themoviedb.org
  - api.themoviedb.org
  - omdbapi.com
  - imdb.com
  - rottentomatoes.com
  - metacritic.com
  - justwatch.com
  - api.justwatch.com
  - fdc.nal.usda.gov
  - api.nal.usda.gov
  - allrecipes.com
  - seriouseats.com
  - bonappetit.com
  - food52.com
  - epicurious.com
scripts:
  - path: scripts/_pp_cli.py
    description: Internal helper — binary resolver and subprocess runner shared by all four wrappers.
  - path: scripts/espn.py
    description: Live sports scores, standings, news (espn-pp-cli).
    args_overview: "[--query TEXT] [-- <espn subcommand args>]"
  - path: scripts/flight_goat.py
    description: Flight search across Google Flights and Kayak (flight-goat-pp-cli).
    args_overview: "[--query TEXT] [-- <flight-goat subcommand args>]"
  - path: scripts/movie_goat.py
    description: Movie discovery, ratings, streaming watchlist (movie-goat-pp-cli).
    args_overview: "[--query TEXT] [-- <movie-goat subcommand args>]"
  - path: scripts/recipe_goat.py
    description: Recipe search, rank, save to cookbook, USDA nutrition (recipe-goat-pp-cli).
    args_overview: "[--query TEXT] [-- <recipe-goat subcommand args>]"
---
# printing-press-library — sevn bundled skill

Exposes four **starter-pack** Printing Press Go CLIs as skill scripts.

## Prerequisites

Install the four Go binaries once:

```bash
make printing-press-starter-pack
# or: npx -y @mvanhorn/printing-press-library install starter-pack
```

Verify: `make printing-press-check`

If binaries are missing, scripts return a `BINARY_MISSING` envelope with the install hint.

## sevn execution model

1. `load_skill("printing-press-library")` — loads this SKILL.md.
2. Choose a script based on the user query:
   - **espn** → live scores, standings, news across 17 sports
   - **flight_goat** → Google Flights + Kayak long-haul search + FlightAware
   - **movie_goat** → TMDb discovery + OMDb ratings + streaming watchlist
   - **recipe_goat** → recipe search, rank, USDA nutrition
3. `run_skill_script(skill_name="printing-press-library", script_path="espn", args=[...])`
4. Read `data.stdout` — JSON envelope `{"ok": true, "data": <cli output>}`.

## Script interface

All scripts share the same interface:

```
<script> --query "natural language"
# or direct CLI passthrough:
<script> -- <subcommand> [flags] --agent
```

`--agent` is appended automatically for agent-mode JSON output.

## Example flows

### ESPN — tonight's NBA games
```
run_skill_script(skill_name="printing-press-library", script_path="espn",
    args=["--", "scoreboard", "nba"])
```

### Flight Goat — non-stop long-haul from Seattle
```
run_skill_script(skill_name="printing-press-library", script_path="flight_goat",
    args=["--query", "non-stop flights from SEA to LHR Dec 24 returning Jan 1"])
```

### Movie Goat — tonight's watchlist
```
run_skill_script(skill_name="printing-press-library", script_path="movie_goat",
    args=["--", "tonight", "--mood", "thriller", "--providers", "netflix,max", "--region", "US"])
```

### Recipe Goat — best carbonara
```
run_skill_script(skill_name="printing-press-library", script_path="recipe_goat",
    args=["--query", "best spaghetti carbonara"])
```

## References

- `references/espn.md` — upstream ESPN CLI command reference
- `references/flight_goat.md` — upstream flight-goat CLI command reference
- `references/movie_goat.md` — upstream movie-goat CLI command reference
- `references/recipe_goat.md` — upstream recipe-goat CLI command reference
