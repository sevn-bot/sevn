#!/usr/bin/env bash
# Reject downloader-piped-to-shell installer patterns under .github/ and Makefile (C11.3).
#
# Scans the same surfaces as tests/infra/test_prod_ready_release_pipeline_w9_red.py
# (W9.5). Wired into ``make ci-infra`` / ``CI_STEPS`` so new pipes fail the gate
# before merge. Includes a self-test that deliberate pipe-to-shell samples are caught.
#
# Note: avoid writing the forbidden pattern as contiguous text in comments on scanned
# surfaces (Makefile / .github/) — the scanner matches source text literally.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
# Align with W9.5 RED suite: any chars up to the pipe (quotes, $(), etc.), not a
# narrow URL charset that missed ``curl "…" | sh`` and ``curl $(…) | sh``.
pattern='(curl|wget)[^|]*\|[[:space:]]*(sudo[[:space:]]+)?(ba)?sh'

offenders=()
_scan_file() {
  local path="$1"
  if grep -nE "${pattern}" "${path}" >/dev/null 2>&1; then
    offenders+=("${path#"${repo_root}"/}")
  fi
}

_scan_file "${repo_root}/Makefile"
while IFS= read -r -d '' path; do
  _scan_file "${path}"
done < <(
  find "${repo_root}/.github" \( -name '*.yml' -o -name '*.yaml' -o -name '*.sh' -o -name '*.md' -o -name 'Makefile' \) \
    -type f -print0 2>/dev/null
)

# Self-test: the gate must reject common pipe-to-shell spellings (including ones
# that bypass a URL-charset-only pattern).
_self_test_samples=(
  $'curl -LsSf https://example.invalid/install.sh | sh\n'
  $'curl -LsSf "https://example.invalid/install.sh" | sh\n'
  $'curl -fsSL $(echo https://example.invalid/install.sh) | bash\n'
  $'wget -qO- https://example.invalid/install.sh | sudo sh\n'
)
for _sample in "${_self_test_samples[@]}"; do
  if ! printf '%s' "${_sample}" | grep -nE "${pattern}" >/dev/null 2>&1; then
    echo "check_no_curl_pipe_sh: self-test failed — pattern missed:" >&2
    printf '  %q\n' "${_sample}" >&2
    exit 1
  fi
done

if ((${#offenders[@]} > 0)); then
  echo "check_no_curl_pipe_sh: downloader-piped-to-shell still present in:" >&2
  printf '  %s\n' "${offenders[@]}" >&2
  echo "(C11.3 — use SHA-pinned actions or checksum-verified downloads)" >&2
  exit 1
fi

echo "check_no_curl_pipe_sh: ok (no downloader-piped-to-shell under .github/ or Makefile)"
