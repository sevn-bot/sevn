# Movie Goat CLI Reference (`movie-goat-pp-cli`)

> Vendored from upstream `cli-skills/pp-movie-goat/SKILL.md` — run `scripts/sync_printing_press_starter_pack.sh` to refresh.

**Binary:** `movie-goat-pp-cli`
**Go module:** `github.com/mvanhorn/printing-press-library/library/media-and-entertainment/movie-goat/cmd/movie-goat-pp-cli`
**License:** Apache-2.0
**Author:** Trevin Chow

## Install

```bash
npx -y @mvanhorn/printing-press-library install movie-goat --cli-only
# or: go install github.com/mvanhorn/printing-press-library/library/media-and-entertainment/movie-goat/cmd/movie-goat-pp-cli@latest
```

## Auth

```bash
export TMDB_API_KEY="<your-key>"   # required — free at https://www.themoviedb.org/settings/api
export OMDB_API_KEY="<your-key>"   # optional — enables IMDb/RT/Metacritic enrichment
```

Run `movie-goat-pp-cli doctor` to verify setup.

## Key commands

| Command | Purpose |
|---------|---------|
| `tonight` | Streaming-filtered shortlist for tonight |
| `ratings <id>` | Multi-source ratings card (TMDb + IMDb + RT + Metacritic) |
| `marathon "<franchise>"` | Franchise marathon with watch order |
| `career "<person>"` | Filmography with ratings |
| `versus <id1> <id2>` | Side-by-side comparison |
| `movies search <title>` | Search movies |
| `movies popular` | Popular movies |
| `watchlist list` | Local SQLite watchlist |
| `discover movies` | Filtered discovery |

## Example invocations

```bash
# Tonight's thriller on Netflix/Max
movie-goat-pp-cli tonight --mood thriller --max-runtime 120 --providers netflix,max --region US --agent

# Multi-source ratings for Fight Club (id 550)
movie-goat-pp-cli ratings 550 --agent

# Mission Impossible marathon
movie-goat-pp-cli marathon "Mission: Impossible" --order release --agent

# Search for a title
movie-goat-pp-cli movies search "Dune" --agent
```

## Agent mode

Add `--agent`: `--json --compact --no-input --no-color --yes`.
Use `--select` to filter fields: `--select "results.title,results.rating"`.
