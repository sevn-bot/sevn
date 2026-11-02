# sevn on Linux

This page covers installing the host on Ubuntu 24.04 and on Omarchy (or plain Arch Linux),
running it as a user service, where secrets live, the bubblewrap sandbox, and running the host
in Docker. `sevn doctor` reports each of these on the host it runs on.

## Install

`deploy/install.sh` is a POSIX `sh` script. Read it first, then run it as your normal user:

```bash
curl -fsSLO https://raw.githubusercontent.com/sevn-bot/sevn/HEAD/deploy/install.sh
less install.sh
sh install.sh
```

It runs these steps in order and stops at the first failure:

1. **System packages.** It prints the command, then runs it through `sudo` (sudo is used for
   this step only):
   - Ubuntu and Debian (`apt-get`): `bubblewrap git curl ca-certificates libsecret-1-0`
   - Arch and Omarchy (`pacman`): `bubblewrap git curl libsecret`

   The distro comes from `/etc/os-release`. Omarchy reports `ID=omarchy` and `ID_LIKE=arch`, so
   it takes the `pacman` path. With no `apt-get` or `pacman`, the script prints both lists and
   carries on without installing anything.
2. **uv.** The `uv` on `PATH` (or in `~/.local/bin`) is used as is. Without one, the script
   downloads uv's release tarball into `~/.local/bin` and checks it against the SHA-256 that
   release publishes.
3. **The host.** `uv tool install` installs the sevn wheel with Python 3.13. Without `--wheel`,
   the script downloads `SHA256SUMS` from the latest GitHub release, then the
   `sevn-<version>-py3-none-any.whl` that file names, and refuses to install on a checksum
   mismatch. `SEVN_RELEASE_BASE` points it at another release directory (`https://` or
   `file://`).
4. **The service.** `sevn service install` (skip it with `--no-service`).
5. **`sevn doctor`**, last, so you see what the host found.

| Option | Effect |
|--------|--------|
| `--wheel PATH\|URL` | Install this wheel. A URL needs a `SHA256SUMS` file next to it. |
| `--no-system-deps` | Skip the package step. |
| `--no-service` | Do not install the user service. |
| `--home PATH` | `SEVN_HOME` for the service and the doctor run. |

The script sends no telemetry. When `~/.local/bin` is not on `PATH` and you run it from a
terminal, it asks before running `uv tool update-shell`, the only change it makes to a shell
profile. Piped or non-interactive runs never touch a profile; they print the directory to add.

From a checkout, build the wheel with the web app inside and install that:

```bash
make wheel                                    # dist/sevn-<version>-py3-none-any.whl + dist/SHA256SUMS
sh deploy/install.sh --wheel dist/sevn-*-py3-none-any.whl
```

On Arch, `pacman -S` fails with a 404 when the package databases are stale. Run
`sudo pacman -Syu` and start the script again.

## The user service

`sevn service install` writes `~/.config/systemd/user/sevn.service` (`ExecStart=<sevn> serve`,
`Restart=on-failure`) and runs `systemctl --user enable --now sevn`.

```bash
sevn service status        # running, stopped, failed or not-installed (--json for scripts)
sevn service logs -f       # journalctl --user -u sevn
sevn service restart
sevn service uninstall
```

Installing again with the same settings leaves the unit as it is (`unchanged`) but restarts the
service when it is running, so re-running `install.sh` for an upgrade takes effect. A stopped or
failed service is not restarted. A unit with other content is replaced only with `--force`.
`--home PATH` and `--port N` go into the unit.

A user service stops when your last session ends. To keep sevn running after you log out (on a
server, or across reboots before you log in), enable lingering for your user yourself:

```bash
loginctl enable-linger "$USER"
```

`sevn service install` prints this hint when lingering is off. sevn never runs it, and
`sevn doctor` shows `linger: on|off`.

## Secrets: the keyring

On a Linux desktop, secrets go to the Secret Service (GNOME Keyring, KeePassXC, or any other
`org.freedesktop.secrets` provider) through libsecret. When `[secrets] backend` is not set in
`$SEVN_HOME/config.toml`, the host picks:

1. `age-file` when `$SEVN_HOME` already has an age secrets file. Existing secrets are never moved
   on their own.
2. `secret-service` when a session bus is up and the default collection is unlocked, checked
   within 2 seconds and without opening an unlock prompt.
3. `age-file` otherwise, for example on a headless server or over SSH without a desktop session.

When `sevn serve` picks `secret-service` this way, it writes `backend = "secret-service"` under
`[secrets]` in `config.toml`. From then on, a locked or missing keyring stops the host with
`secrets_locked` or `secrets_unavailable` instead of starting on an empty age file with a new
host identity. Unlock the keyring (log in to the desktop session) and start it again. If the
keyring locks or goes away while the host runs, calls that need a secret (listing models,
creating a bot) answer `secrets_locked` or `secrets_unavailable`, and routing carries on without
jev until the keyring answers again.

To move an existing host between backends, use `sevn secret migrate`. It copies every secret,
reads each one back, writes the new backend to `config.toml`, and only then deletes the old
copies. A failure leaves the source untouched.

```bash
sevn secret migrate --to secret-service     # age file -> keyring
sevn secret migrate --to age-file           # keyring -> age file (for a headless host)
```

`sevn doctor` shows the backend in use as `secrets_backend`, marked `locked` when the keyring is
locked.

## The sandbox: bubblewrap

The `workspace` access level runs the shell inside bubblewrap (`bwrap`) in new namespaces.
`sevn doctor` runs a real `bwrap` probe and reports:

| `bubblewrap` | Meaning |
|--------------|---------|
| `ok` | The `workspace` level works. |
| `missing` | Install the `bubblewrap` package. |
| `userns-blocked` | The kernel or AppArmor refuses the user namespace (see Ubuntu 24.04 below). |
| `unavailable-in-container` | The host runs in a container that blocks namespaces (see Docker below). |

When bubblewrap cannot start, a `workspace` command fails with the `bwrap:` line as its stderr
and exit code 1. sevn never falls back to running it unconfined.

### Ubuntu 24.04

Ubuntu 24.04 sets `kernel.apparmor_restrict_unprivileged_userns=1`. An unconfined program can
still create a user namespace, but AppArmor strips its capabilities inside it, so `bwrap` fails
with one of:

```text
bwrap: setting up uid map: Permission denied
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
```

and `sevn doctor` reports `userns-blocked`, naming `kernel.apparmor_restrict_unprivileged_userns`.
The fix is an AppArmor profile that lets `bwrap` alone create user namespaces. Create
`/etc/apparmor.d/bwrap`:

```text
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,

  include if exists <local/bwrap>
}
```

then reload AppArmor and check again:

```bash
sudo systemctl reload apparmor
sevn doctor
```

Putting the profile in `complain` mode does not help; it has to be `unconfined` with `userns`.
Keep the sysctl as Ubuntu ships it and do not make `bwrap` setuid: the profile above opens user
namespaces to `bwrap` only, not to every program on the machine.

Omarchy and Arch allow unprivileged user namespaces by default, so `bwrap` needs no extra setup
there.

## Docker

`deploy/compose.yaml` runs the image from `deploy/Dockerfile` on `127.0.0.1:8787`, with the
database on the `sevn-data` volume and the user's home (where CLI logins land) on `sevn-home`.
`deploy/Dockerfile.ubuntu` builds the same image on Ubuntu 24.04 (`make image-ubuntu`). Run
compose from the repository root:

```bash
docker compose -f deploy/compose.yaml up -d
curl -fsS http://127.0.0.1:8787/health
```

Set `SEVN_ALLOWED_HOSTS` (in the shell or `deploy/.env`) to every non-loopback `Host` that
clients use.

### On a tailnet

The `tailscale` profile adds a Tailscale sidecar that serves `https://<TS_HOSTNAME>.<tailnet>.ts.net`
and proxies it to the host. Start it by naming the `sevn-tailnet` service; the auth key is read
from your shell and reaches the sidecar only as a compose secret:

```bash
docker compose -f deploy/compose.yaml down          # stop the loopback variant first
TS_AUTHKEY=… docker compose -f deploy/compose.yaml up -d sevn-tailnet
```

A bare `docker compose -f deploy/compose.yaml --profile tailscale up` fails on purpose:
`sevn` and `sevn-tailnet` share the container name `sevn` and both volumes, so compose refuses to
start two hosts on one database.

### Logging in to the CLIs

The images ship pinned copies of the Claude, OpenCode, Codex and Cursor CLIs under
`/opt/sevn/runtimes` (read-only to the `sevn` user). Log in to each one inside the container;
the credentials stay in `/home/sevn` on the `sevn-home` volume and survive
`docker compose down` and `up` (but not `down -v`):

```bash
docker exec -it sevn claude                 # then /login
docker exec -it sevn opencode auth login
docker exec -it sevn codex login
docker exec -it sevn cursor-agent login
docker exec -it sevn sevn runtimes list     # which copy the host uses
```

sevn never reads or copies these credentials.

### The sandbox in a container

Docker's default seccomp profile blocks the user namespaces bubblewrap needs, so the `workspace`
level cannot start in a container and `sevn doctor` reports `unavailable-in-container`. Pick
one of two setups:

1. **Recommended: give container bots the `full` access level.** Their boundary is the
   container itself, which already keeps them away from the machine running Docker.
2. **Run `workspace` inside the container.** Opt in to both options on the `sevn` service in
   `deploy/compose.yaml`:

   ```yaml
   security_opt:
     - seccomp=unconfined
     - systempaths=unconfined
   ```

   (`docker run --security-opt seccomp=unconfined --security-opt systempaths=unconfined`). On a
   host with AppArmor (Ubuntu), Docker's `docker-default` profile may also refuse the mounts;
   add `apparmor=unconfined` there. `seccomp=unconfined` alone is not enough: `bwrap` then fails
   with `Can't mount proc on /newroot/proc: Operation not permitted`, because Docker masks parts
   of `/proc`. `systempaths=unconfined` removes that masking, which also exposes `/proc/kcore`,
   `/proc/keys`, `/proc/timer_list` and similar paths inside the container. That is why the
   `full` level is the recommended container setup.

## Managed CLI runtimes

`sevn runtimes install` puts pinned, SHA-256-verified copies of the CLI runtimes under
`$SEVN_HOME/runtimes/<name>/<version>/` and switches `current` atomically. It never touches
your CLI logins.

```bash
sevn runtimes install claude        # or opencode, codex, cursor-agent, or --all
sevn runtimes list                  # managed versions, the system copy, and which one is used
sevn runtimes remove opencode
```

The host uses the managed copy first, then the one on `PATH` (unless
`[runtimes.<name>] use_system = false`), then, for Claude only, the CLI bundled with the SDK.
`SEVN_RUNTIMES_DIR` (or `[runtimes] dir`) moves the root; the images set it to
`/opt/sevn/runtimes`. On a root you cannot write to (that image directory is read-only to the
`sevn` user), `install` and `remove` stop with `read_only_root` and the path, before any
download or change.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `sevn: command not found` after the install | Add `~/.local/bin` to `PATH`, or run `uv tool update-shell`. |
| The service stops when you log out | `loginctl enable-linger "$USER"` |
| `sevn serve` exits with `secrets_locked` | Unlock the keyring, or `sevn secret migrate --to age-file` on a headless host. |
| `bubblewrap: userns-blocked` on Ubuntu | Add the `/etc/apparmor.d/bwrap` profile above. |
| `bubblewrap: unavailable-in-container` | Use the `full` level, or the container options above. |
| `checksum mismatch` from `install.sh` | The download does not match `SHA256SUMS`; nothing was installed. Try again, or pass `--wheel` with a wheel you built. |
