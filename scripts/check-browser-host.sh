#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# C8.1 — host preflight for the browser/GUI compose overlays.
#
# The overlays run Brave with the Chromium renderer sandbox ON (no
# --no-sandbox anywhere in the shipped compose files). Two preconditions must
# hold; both fail at runtime with the same opaque abort:
#
#     Failed to move to new namespace: … errno = Operation not permitted
#     FATAL … zygote_host_impl_linux.cc
#
#   1. Container syscall policy — the overlays pin
#      infra/docker/seccomp-browser.json. That is a property of the committed
#      compose files, so `scripts/check-compose-default.sh` asserts it (and it
#      runs in `make ci-infra`).
#   2. Host user-namespace policy — THIS script. It is a property of the
#      machine, which is why it runs on the `compose-browser-up` /
#      `compose-gui-up` path and deliberately NOT in CI's static gates: a CI
#      runner's host policy says nothing about whether the repo is correct.
#
# Fails closed so an operator is told before `compose up` rather than
# discovering a browser that never starts. Set
# SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT=1 to bypass after accepting another
# mitigation.
set -euo pipefail

if [ "${SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT:-0}" = "1" ]; then
  echo "check-browser-host: skipped (SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT=1)"
  exit 0
fi

userns_sysctl=/proc/sys/kernel/apparmor_restrict_unprivileged_userns

# Absent on macOS/Colima hosts and on kernels without the AppArmor restriction:
# nothing to assert, and the container runtime's own VM governs the sandbox.
if [ ! -r "$userns_sysctl" ]; then
  echo "check-browser-host: ok (no AppArmor userns restriction on this host)"
  exit 0
fi

value="$(cat "$userns_sysctl")"
if [ "$value" = "0" ]; then
  echo "check-browser-host: ok (unprivileged user namespaces permitted)"
  exit 0
fi

cat >&2 <<EOF
error: this host restricts unprivileged user namespaces
       (${userns_sysctl} = ${value}).

       Brave's renderer sandbox cannot start, and the browser/gui overlays no
       longer fall back to --no-sandbox (C8.1). The container would come up and
       the browser would abort before CDP binds.

       Remediation — prefer the app-scoped AppArmor policy:

         sudo tee /etc/apparmor.d/sevn-browser >/dev/null <<'PROFILE'
         abi <abi/4.0>,
         include <tunables/global>
         profile sevn-browser flags=(unconfined) {
           userns,
         }
         PROFILE
         sudo apparmor_parser -r /etc/apparmor.d/sevn-browser

       Host-wide alternative (weaker — affects every process on the host):

         echo 0 | sudo tee ${userns_sysctl}
         # persist via /etc/sysctl.d/60-apparmor-userns.conf

       See docker/README.md "Browser sandbox (C8.1)" and
       docs/readmes/security.md §C8.1.

       Bypass once another mitigation is accepted:
         SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT=1 make compose-browser-up
EOF
exit 1
