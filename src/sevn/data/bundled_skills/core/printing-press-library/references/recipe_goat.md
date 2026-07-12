# Recipe Goat CLI Reference (`recipe-goat-pp-cli`)

> Vendored from upstream `cli-skills/pp-recipe-goat/SKILL.md` — run `scripts/sync_printing_press_starter_pack.sh` to refresh.

**Binary:** `recipe-goat-pp-cli`
**Go module:** `github.com/mvanhorn/printing-press-library/library/food-and-dining/recipe-goat/cmd/recipe-goat-pp-cli`
**License:** Apache-2.0
**Author:** Trevin Chow

## Install

```bash
npx -y @mvanhorn/printing-press-library install recipe-goat --cli-only
# or: go install github.com/mvanhorn/printing-press-library/library/food-and-dining/recipe-goat/cmd/recipe-goat-pp-cli@latest
```

## Auth (optional)

```bash
export USDA_FDC_API_KEY="<your-key>"  # USDA FoodData Central — enables nutrition lookups
```

Run `recipe-goat-pp-cli doctor` to verify setup.

## Key commands

| Command | Purpose |
|---------|---------|
| `which "<query>"` | NL → best matching command |
| `foods search <query>` | USDA FoodData Central ingredient search |
| `foods get <fdc-id>` | Get food by USDA FDC ID |
| `foods list` | List foods paginated |

## Example invocations

```bash
# Find the best carbonara recipe (via which for NL routing)
recipe-goat-pp-cli which "best spaghetti carbonara recipe" --agent

# USDA nutrition for chicken breast
recipe-goat-pp-cli foods search "chicken breast" --agent

# Get specific food by FDC ID
recipe-goat-pp-cli foods get 171477 --agent
```

## Agent mode

Add `--agent`: `--json --compact --no-input --no-color --yes`.
Use `--select` to filter fields for large nutrition payloads.
