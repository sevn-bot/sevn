#!/usr/bin/env bash
# Reject downloader-piped-to-shell installer patterns under .github/ and Makefile (C11.3).
#
# Scans the same surfaces as tests/infra/test_prod_ready_release_pipeline_w9_red.py
# (W9.5). Wired into ``make ci-infra`` / ``CI_STEPS`` so new pipes fail the gate
# before merge. Includes a self-test that deliberate pipe-to-shell samples are caught.
#
# Note: avoid writing the forbidden pattern as contiguous text in comments on scanned
# surfaces (Makefile / .github/) — the scanner matches source text literally.
# Physical backslash-continuations are joined before matching so
# ``curl … \\`` / ``| sh`` cannot evade a line-oriented scan.
#
# Every regular file under ``.github/`` is considered (not an extension allowlist);
# binaries (NUL in the first 8KiB) are skipped by content. Override the scan root
# with ``SEVN_CURL_PIPE_SCAN_ROOT`` for tests.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
scan_root="${SEVN_CURL_PIPE_SCAN_ROOT:-${repo_root}}"

offenders=()

# Collapse backslash-newline continuations, then match with a Python regex that
# mirrors W9.5 (any chars up to the pipe — quotes, $(), newlines after join).
# Exit 0 = match (offender), 1 = clean/skip, 2 = unreadable.
_file_matches_pipe_sh() {
  local path="$1"
  python3 - "$path" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    raw = path.read_bytes()
except OSError as exc:
    print(f"check_no_curl_pipe_sh: cannot read {path}: {exc}", file=sys.stderr)
    sys.exit(2)
# Skip binaries by content — extension allowlists miss install.bash / extensionless helpers.
if b"\0" in raw[:8192]:
    sys.exit(1)
text = raw.decode("utf-8", errors="replace")
pattern = re.compile(
    r"(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b",
    re.IGNORECASE,
)
logical = re.sub(r"\\\r?\n", "", text)
sys.exit(0 if pattern.search(logical) else 1)
PY
}

_scan_file() {
  local path="$1"
  local rc=0
  _file_matches_pipe_sh "${path}" || rc=$?
  if ((rc == 0)); then
    offenders+=("${path#"${scan_root}"/}")
  elif ((rc == 2)); then
    exit 2
  fi
}

_text_matches_pipe_sh() {
  local text="$1"
  python3 -c '
import re, sys
pattern = re.compile(
    r"(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b",
    re.IGNORECASE,
)
logical = re.sub(r"\\\r?\n", "", sys.argv[1])
sys.exit(0 if pattern.search(logical) else 1)
' "${text}"
}

_scan_file "${scan_root}/Makefile"
if [[ -d "${scan_root}/.github" ]]; then
  while IFS= read -r -d '' path; do
    _scan_file "${path}"
  done < <(
    find "${scan_root}/.github" -type f -print0 2>/dev/null
  )
fi

# Self-test: the gate must reject common pipe-to-shell spellings (including ones
# that bypass a URL-charset-only pattern or a physical-line-only grep).
_self_test_samples=(
  $'curl -LsSf https://example.invalid/install.sh | sh\n'
  $'curl -LsSf "https://example.invalid/install.sh" | sh\n'
  $'curl -fsSL $(echo https://example.invalid/install.sh) | bash\n'
  $'wget -qO- https://example.invalid/install.sh | sudo sh\n'
  $'curl -LsSf https://example.invalid/install.sh \\\n| sh\n'
)
for _sample in "${_self_test_samples[@]}"; do
  if ! _text_matches_pipe_sh "${_sample}"; then
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
