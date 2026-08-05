#!/usr/bin/env bash
# Delete GHCR package versions that only carry quarantine-* tags for a given SHA.
#
# Used by container-supply-chain when the job fails or is cancelled (C12.3 / W11.5)
# so unscanned quarantine tags do not accumulate. Safe against promoted digests:
# a version that also carries a SHA or version tag is left alone.
#
# Usage (from Actions, with GH_TOKEN set):
#   source scripts/ghcr_quarantine_cleanup.sh
#   delete_quarantine_tags "<owner/repo>" "<github.sha>"
#
# SPDX-License-Identifier: MIT
set -euo pipefail

delete_quarantine_tags() {
  local image_repository="${1:?image_repository (owner/repo) required}"
  local sha="${2:?git sha required}"
  local owner="${image_repository%%/*}"
  local repo="${image_repository#*/}"
  local qtag="quarantine-${sha}"
  local name pkg enc api_base version_id tags

  if [[ -z "${GH_TOKEN:-}" && -z "${GITHUB_TOKEN:-}" ]]; then
    echo "ghcr_quarantine_cleanup: GH_TOKEN or GITHUB_TOKEN required" >&2
    return 1
  fi
  export GH_TOKEN="${GH_TOKEN:-$GITHUB_TOKEN}"

  for name in sandbox proxy gateway gateway.browser gateway.gui; do
    pkg="${repo}/${name}"
    enc="$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "${pkg}")"
    api_base=""
    if gh api "/orgs/${owner}/packages/container/${enc}" >/dev/null 2>&1; then
      api_base="/orgs/${owner}/packages/container/${enc}"
    elif gh api "/users/${owner}/packages/container/${enc}" >/dev/null 2>&1; then
      api_base="/users/${owner}/packages/container/${enc}"
    else
      echo "skip ${pkg}: package not found (may never have been pushed)"
      continue
    fi

    while IFS=$'\t' read -r version_id tags; do
      [[ -z "${version_id}" ]] && continue
      echo "Deleting ${pkg} version ${version_id} (tags=${tags})"
      gh api --method DELETE "${api_base}/versions/${version_id}" >/dev/null
    done < <(
      # Do not swallow API errors: a silent skip leaves unscanned quarantine tags
      # (W11.5). The workflow step uses continue-on-error so cleanup noise cannot
      # mask the original supply-chain failure.
      gh api --paginate "${api_base}/versions" \
        --jq ".[]
          | select(.metadata.container.tags != null)
          | select(.metadata.container.tags | index(\"${qtag}\"))
          | select([.metadata.container.tags[] | startswith(\"quarantine-\")] | all)
          | [.id, (.metadata.container.tags | join(\",\"))]
          | @tsv"
    )
  done
}
