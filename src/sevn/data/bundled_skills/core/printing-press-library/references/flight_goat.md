# Flight Goat CLI Reference (`flight-goat-pp-cli`)

> Vendored from upstream `cli-skills/pp-flight-goat/SKILL.md` — run `scripts/sync_printing_press_starter_pack.sh` to refresh.

**Binary:** `flight-goat-pp-cli`
**Go module:** `github.com/mvanhorn/printing-press-library/library/travel/flight-goat/cmd/flight-goat-pp-cli`
**License:** Apache-2.0
**Author:** Matt Van Horn

## Install

```bash
npx -y @mvanhorn/printing-press-library install flight-goat --cli-only
# or: go install github.com/mvanhorn/printing-press-library/library/travel/flight-goat/cmd/flight-goat-pp-cli@latest
```

## Auth (optional)

```bash
export FLIGHTAWARE_API_KEY="<your-key>"  # FlightAware AeroAPI — optional, enriches reliability data
```

## Key capabilities

- **Google Flights search** — price calendar, nonstop filters, cabin class, passengers
- **Kayak long-haul scan** — routes >8h, cheapest-first ranking
- **FlightAware reliability** — on-time %, delay history (requires FLIGHTAWARE_API_KEY)
- **`which "<query>"`** — NL → best matching command

## Example invocations

```bash
# Non-stop long-haul from Seattle, Dec 24–Jan 1, 4 passengers
flight-goat-pp-cli flights search SEA LHR --depart 2026-12-24 --return 2027-01-01 \
  --passengers 4 --nonstop --sort price --agent

# Cheapest flights any month (price calendar)
flight-goat-pp-cli flights calendar SEA LHR --agent

# Discover command
flight-goat-pp-cli which "cheapest nonstop from Seattle to London" --agent
```

## Agent mode

Add `--agent`: `--json --compact --no-input --no-color --yes`.
