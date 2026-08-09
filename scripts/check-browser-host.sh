#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# C8.1 — host preflight for the browser/GUI compose overlays.
#
# The overlays run Brave with the Chromium renderer sandbox ON (no
# --no-sandbox anywhere in the shipped compose files). Brave builds that
# sandbox by creating a user namespace and chroot-ing into it; if the host or
# the container runtime refuses, Brave aborts at startup with an opaque
#
#     Failed to move to new namespace: … errno = Operation not permitted
#     FATAL … zygote_host_impl_linux.cc
#
# which surfaces as "the browser silently doesn't work" long after `compose up`
# reported success. This script proves the capability up front.
#
# It probes the REAL condition rather than inferring it from a sysctl: it runs
# `unshare -U` in a throwaway container under the exact security context the
# overlays use (cap_drop:ALL + no-new-privileges + the pinned seccomp profile).
# Inference from /proc/sys/kernel/apparmor_restrict_unprivileged_userns would be
# wrong — GitHub's ubuntu-24.04 runners ship that sysctl set to 1 and Brave
# still sandboxes correctly there, because the restriction does not apply to
# processes under Docker's own AppArmor profile. A sysctl-based gate would
# refuse to start on hosts that work fine.
#
# The complementary static assertion — that the overlays pin the profile at all
# — lives in scripts/check-compose-default.sh, which runs in `make ci-infra`.
# This script is about the machine, so it runs on the deploy path only.
#
# Fails closed when the probe runs and userns is denied. When the probe cannot
# run at all (no daemon, image unavailable) it warns and exits 0 — an
# unreachable Docker daemon is not evidence about the sandbox, and `compose up`
# will fail on its own. Set SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT=1 to bypass.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
seccomp_profile="${repo_root}/infra/docker/seccomp-browser.json"
probe_image="${SEVN_BROWSER_PREFLIGHT_IMAGE:-busybox:1.36}"

if [ "${SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT:-0}" = "1" ]; then
  echo "check-browser-host: skipped (SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT=1)"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "check-browser-host: skipped (docker CLI not on PATH)" >&2
  exit 0
fi

if ! docker info >/dev/null 2>&1; then
  echo "check-browser-host: skipped (Docker daemon not reachable)" >&2
  exit 0
fi

if [ ! -f "$seccomp_profile" ]; then
  echo "error: missing browser seccomp profile at ${seccomp_profile}" >&2
  exit 1
fi

# Probe under the overlays' exact security context.
probe_output=""
probe_rc=0
probe_output="$(
  docker run --rm \
    --cap-drop=ALL \
    --security-opt=no-new-privileges:true \
    --security-opt "seccomp=${seccomp_profile}" \
    --user=10001:10001 \
    --entrypoint sh \
    "$probe_image" -c 'unshare -U true' 2>&1
)" || probe_rc=$?

if [ "$probe_rc" -eq 0 ]; then
  echo "check-browser-host: ok (renderer sandbox can create user namespaces)"
  exit 0
fi

# Distinguish "the sandbox is blocked" from "the probe itself could not run"
# (missing image, no network to pull it, unrelated daemon error). Only the
# former is evidence, and only the former may fail the deploy.
case "$probe_output" in
  *"Operation not permitted"* | *"operation not permitted"* | *"unshare"*)
    : # genuine denial — fall through to the hard failure below
    ;;
  *)
    echo "check-browser-host: skipped (probe could not run: ${probe_output})" >&2
    exit 0
    ;;
esac

cat >&2 <<EOF
error: this host will not let the browser container create a user namespace.

       Probe (the exact context the browser/gui overlays use):
         docker run --rm --cap-drop=ALL --security-opt=no-new-privileges:true \\
           --security-opt seccomp=${seccomp_profile} \\
           --user=10001:10001 ${probe_image} unshare -U true
       -> ${probe_output}

       Brave's renderer sandbox cannot start, and the overlays no longer fall
       back to --no-sandbox (C8.1): the container would come up and the browser
       would abort before CDP binds.

       Common causes and remediations:

       1. A custom Docker seccomp default that blocks clone(CLONE_NEWUSER).
          Confirm 'seccomp' is not listed under 'Security Options' with a
          non-default profile in \`docker info\`.

       2. A hardened kernel with user namespaces disabled outright:
            sysctl user.max_user_namespaces      # must be > 0
            sysctl kernel.unprivileged_userns_clone  # must be 1 where present

       3. AppArmor userns mediation applied to the container itself. Note the
          stock Ubuntu 24.04 default (apparmor_restrict_unprivileged_userns=1)
          does NOT cause this: containers run under Docker's own profile, and
          the hardened Brave smoke passes on a stock ubuntu-24.04 runner with
          that sysctl set to 1.

          If your host genuinely does mediate userns for containers, note that
          loading a policy is not enough on its own — the container has to
          SELECT it, otherwise Docker applies 'docker-default' regardless:

            security_opt:
              - apparmor=<your-profile>

          sevn does not ship such a profile (no supported host has been
          observed to need one), so this is operator-supplied: add the profile
          to the host, then select it on sevn-gateway via your own compose
          override alongside the shipped overlay. Please also report the host,
          since it would mean the shipped overlays need a first-class option.

       See docker/README.md "Browser sandbox (C8.1)" and
       docs/readmes/security.md §C8.1.

       Bypass once another mitigation is accepted:
         SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT=1 make compose-browser-up
EOF
exit 1
