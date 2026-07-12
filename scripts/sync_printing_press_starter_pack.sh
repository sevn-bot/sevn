#!/usr/bin/env bash
# Vendor upstream Printing Press starter-pack SKILL.md files into references/.
#
# Usage: bash scripts/sync_printing_press_starter_pack.sh [--dry-run]
#
# Fetches cli-skills/pp-{espn,flight-goat,movie-goat,recipe-goat}/SKILL.md from
# https://github.com/mvanhorn/printing-press-library (main branch) and writes
# them to src/sevn/data/bundled_skills/core/printing-press-library/references/.
# Updates UPSTREAM_VERSION with the current UTC timestamp.
#
# Preserves the sevn-owned SKILL.md overlay (never overwrites it).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DIR="${REPO_ROOT}/src/sevn/data/bundled_skills/core/printing-press-library"
REFS_DIR="${SKILL_DIR}/references"
UPSTREAM_BASE="https://raw.githubusercontent.com/mvanhorn/printing-press-library/main/cli-skills"
DRY_RUN=0

for arg in "$@"; do
  [[ "$arg" == "--dry-run" ]] && DRY_RUN=1
done

slugs=(espn flight-goat movie-goat recipe-goat)
local_names=(espn flight_goat movie_goat recipe_goat)

echo "sync_printing_press_starter_pack: syncing ${#slugs[@]} upstream SKILL.md files..."

for i in "${!slugs[@]}"; do
  slug="${slugs[$i]}"
  local="${local_names[$i]}"
  src="${UPSTREAM_BASE}/pp-${slug}/SKILL.md"
  dst="${REFS_DIR}/${local}.md"

  echo "  fetching ${src} -> ${dst}"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] would write ${dst}"
  else
    tmp="$(mktemp)"
    if curl -fsSL "${src}" -o "${tmp}"; then
      mv "${tmp}" "${dst}"
      echo "  ok: ${dst}"
    else
      rm -f "${tmp}"
      echo "  warning: failed to fetch ${src} — skipping" >&2
    fi
  fi
done

if [[ "$DRY_RUN" -eq 0 ]]; then
  synced_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat > "${SKILL_DIR}/UPSTREAM_VERSION" <<EOF
ref=main
synced=${synced_at}
espn_go_module=github.com/mvanhorn/printing-press-library/library/media-and-entertainment/espn/cmd/espn-pp-cli
flight_goat_go_module=github.com/mvanhorn/printing-press-library/library/travel/flight-goat/cmd/flight-goat-pp-cli
movie_goat_go_module=github.com/mvanhorn/printing-press-library/library/media-and-entertainment/movie-goat/cmd/movie-goat-pp-cli
recipe_goat_go_module=github.com/mvanhorn/printing-press-library/library/food-and-dining/recipe-goat/cmd/recipe-goat-pp-cli
EOF
  echo "sync_printing_press_starter_pack: updated UPSTREAM_VERSION (synced=${synced_at})"
fi

echo "sync_printing_press_starter_pack: done."
