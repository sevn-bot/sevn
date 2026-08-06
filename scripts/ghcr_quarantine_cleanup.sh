#!/usr/bin/env bash
# Delete GHCR package versions that only carry quarantine-* tags for a given run.
#
# Used by publish-ghcr / container-supply-chain when the job fails or is cancelled
# (C12.3 / W11.5) so unscanned quarantine tags do not accumulate. Safe against
# promoted digests: a version that also carries a SHA or version tag is left alone.
#
# Quarantine tags are run-scoped (`quarantine-<sha>-<run_id>`) so overlapping
# main / v* publishes for the same commit cannot delete each other's versions.
#
# Usage (from Actions, with GH_TOKEN set):
#   source scripts/ghcr_quarantine_cleanup.sh
#   delete_quarantine_tags "<owner/repo>" "<github.sha>" "<github.run_id>"
#
# SPDX-License-Identifier: MIT
set -euo pipefail

# Probe a packages API path. Prints the HTTP status code on stdout.
# Distinguishes expected 404 (package never pushed) from auth/network/5xx failures.
_ghcr_probe_status() {
  local path="${1:?api path required}"
  local headers status rc=0
  # ``gh api -i`` includes the status line; some gh versions still exit non-zero
  # on 4xx, so parse the status when present rather than trusting exit alone.
  headers="$(gh api -i "${path}" 2>/dev/null)" || rc=$?
  status="$(printf '%s\n' "${headers}" | awk 'NR==1 {print $2; exit}')"
  if [[ -z "${status}" ]]; then
    echo "ghcr_quarantine_cleanup: probe request failed for ${path} (exit ${rc})" >&2
    return 1
  fi
  printf '%s\n' "${status}"
}

delete_quarantine_tags() {
  local image_repository="${1:?image_repository (owner/repo) required}"
  local sha="${2:?git sha required}"
  local run_id="${3:?github run_id required}"
  local owner="${image_repository%%/*}"
  local repo="${image_repository#*/}"
  local qtag="quarantine-${sha}-${run_id}"
  local name pkg enc api_base version_id tags versions_tsv
  local org_status user_status

  if [[ -z "${GH_TOKEN:-}" && -z "${GITHUB_TOKEN:-}" ]]; then
    echo "ghcr_quarantine_cleanup: GH_TOKEN or GITHUB_TOKEN required" >&2
    return 1
  fi
  export GH_TOKEN="${GH_TOKEN:-$GITHUB_TOKEN}"

  for name in sandbox proxy gateway gateway.browser gateway.gui; do
    pkg="${repo}/${name}"
    enc="$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "${pkg}")"
    api_base=""

    org_status="$(_ghcr_probe_status "/orgs/${owner}/packages/container/${enc}")" || return 1
    case "${org_status}" in
      200)
        api_base="/orgs/${owner}/packages/container/${enc}"
        ;;
      404)
        user_status="$(_ghcr_probe_status "/users/${owner}/packages/container/${enc}")" || return 1
        case "${user_status}" in
          200)
            api_base="/users/${owner}/packages/container/${enc}"
            ;;
          404)
            echo "skip ${pkg}: package not found (may never have been pushed)"
            continue
            ;;
          *)
            echo "ghcr_quarantine_cleanup: probe /users/${owner}/packages/container/${enc} failed with HTTP ${user_status}" >&2
            return 1
            ;;
        esac
        ;;
      *)
        echo "ghcr_quarantine_cleanup: probe /orgs/${owner}/packages/container/${enc} failed with HTTP ${org_status}" >&2
        return 1
        ;;
    esac

    # Capture API output first — process-substitution exit status is not
    # propagated to the while loop even under set -euo pipefail.
    versions_tsv="$(
      gh api --paginate "${api_base}/versions" \
        --jq ".[]
          | select(.metadata.container.tags != null)
          | select(.metadata.container.tags | index(\"${qtag}\"))
          | select([.metadata.container.tags[] | startswith(\"quarantine-\")] | all)
          | [.id, (.metadata.container.tags | join(\",\"))]
          | @tsv"
    )" || {
      echo "ghcr_quarantine_cleanup: failed to list versions for ${pkg}" >&2
      return 1
    }

    while IFS=$'\t' read -r version_id tags; do
      [[ -z "${version_id}" ]] && continue
      echo "Deleting ${pkg} version ${version_id} (tags=${tags})"
      gh api --method DELETE "${api_base}/versions/${version_id}" >/dev/null
    done <<< "${versions_tsv}"
  done
}
