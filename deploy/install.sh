#!/bin/sh
# Install the sevn host on Linux (Ubuntu, Debian, Arch, Omarchy) or macOS.
#
#   sh deploy/install.sh [--wheel PATH|URL] [--no-system-deps] [--no-service] [--home PATH]
#
# Steps, in order:
#   1. System packages (apt-get or pacman), through sudo when not root. The
#      command is printed before it runs. sudo is used for nothing else.
#   2. uv: the one on PATH (or ~/.local/bin), else uv's release tarball,
#      checked against its published SHA-256.
#   3. `uv tool install` of the host wheel. Without --wheel, the wheel named in
#      $SEVN_RELEASE_BASE/SHA256SUMS (default: the latest GitHub release) is
#      downloaded and checked against that file.
#   4. `sevn service install` (a systemd --user unit or a launchd agent),
#      unless --no-service.
#   5. `sevn doctor`.
#
# No telemetry. The only shell profile change is `uv tool update-shell`, and
# only when you answer yes on a terminal. See docs/linux.md.
set -eu

SEVN_RELEASE_BASE=${SEVN_RELEASE_BASE:-https://github.com/sevn-bot/sevn/releases/latest/download}
UV_VERSION=0.13.1
APT_PACKAGES="bubblewrap git curl ca-certificates libsecret-1-0"
PACMAN_PACKAGES="bubblewrap git curl libsecret"

say() {
    printf 'sevn-install: %s\n' "$*"
}

fail() {
    printf 'sevn-install: error: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
usage: install.sh [--wheel PATH|URL] [--no-system-deps] [--no-service] [--home PATH]

  --wheel PATH|URL   install this host wheel instead of the latest release
                     (a URL needs a SHA256SUMS file next to it)
  --no-system-deps   skip the apt-get / pacman step
  --no-service       do not install the user service
  --home PATH        SEVN_HOME for the service and the doctor check
EOF
}

usage_error() {
    printf 'sevn-install: %s\n' "$*" >&2
    usage >&2
    exit 2
}

# --- options (parsed before anything runs) -----------------------------------

wheel=""
system_deps=1
service=1
home=""

while [ "$#" -gt 0 ]; do
    case $1 in
        --wheel)
            [ "$#" -ge 2 ] || usage_error "--wheel needs a path or URL"
            wheel=$2
            shift 2
            ;;
        --wheel=*)
            wheel=${1#--wheel=}
            shift
            ;;
        --home)
            [ "$#" -ge 2 ] || usage_error "--home needs a path"
            home=$2
            shift 2
            ;;
        --home=*)
            home=${1#--home=}
            shift
            ;;
        --no-system-deps)
            system_deps=0
            shift
            ;;
        --no-service)
            service=0
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            usage_error "unknown option: $1"
            ;;
    esac
done

case $wheel in
    --*) usage_error "--wheel needs a path or URL" ;;
    "" | http://* | https://*) ;;
    *) [ -f "$wheel" ] || usage_error "--wheel: no such file: $wheel" ;;
esac
case $home in
    --*) usage_error "--home needs a path" ;;
    "" | /*) ;;
    *) home=$(pwd)/$home ;;
esac

workdir=$(mktemp -d)
cleanup() {
    rm -rf "$workdir"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

# --- helpers -----------------------------------------------------------------

have() {
    command -v "$1" >/dev/null 2>&1
}

# os-release ID and ID_LIKE words, lower case ("omarchy arch", "ubuntu debian").
distro_words() {
    for file in /etc/os-release /usr/lib/os-release; do
        if [ -r "$file" ]; then
            sed -n 's/^ID\(_LIKE\)\{0,1\}=//p' "$file" | tr -d "\"'" | tr '[:upper:]' '[:lower:]' | tr '\n' ' '
            return 0
        fi
    done
    return 0
}

# apt-get or pacman, or nothing. The distro family decides when both exist
# (Omarchy reports ID=omarchy ID_LIKE=arch).
package_manager() {
    words=" $(distro_words) "
    case $words in
        *" arch "*)
            if have pacman; then echo pacman; return 0; fi
            ;;
        *" debian "* | *" ubuntu "*)
            if have apt-get; then echo apt-get; return 0; fi
            ;;
    esac
    if have apt-get && ! have pacman; then
        echo apt-get
    elif have pacman && ! have apt-get; then
        echo pacman
    fi
    return 0
}

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        say "+ $*"
        "$@"
    elif have sudo; then
        say "+ sudo $*"
        sudo "$@"
    else
        fail "this step needs root and sudo is not installed; run it as root: $*"
    fi
}

sha256_of() {
    if have sha256sum; then
        sha256sum "$1" | awk '{print $1}' | tr 'A-F' 'a-f'
    elif have shasum; then
        shasum -a 256 "$1" | awk '{print $1}' | tr 'A-F' 'a-f'
    else
        fail "sha256sum or shasum is needed to check downloads"
    fi
}

fetch() {
    have curl || fail "curl is needed to download $1"
    curl -fsSL --retry 3 -o "$2" "$1" || fail "download failed: $1"
}

# verify FILE NAME SUMS: FILE must have the hash SUMS lists for NAME.
verify() {
    expected=$(awk -v name="$2" '$2 == name || $2 == "*" name {print $1; exit}' "$3" | tr 'A-F' 'a-f')
    [ -n "$expected" ] || fail "checksum for $2 is not listed in SHA256SUMS"
    actual=$(sha256_of "$1")
    if [ "$actual" != "$expected" ]; then
        fail "checksum mismatch for $2: expected $expected, got $actual; nothing was installed"
    fi
    say "checksum ok: $2"
}

# --- 1. system packages ------------------------------------------------------

install_system_packages() {
    manager=$(package_manager)
    case $manager in
        apt-get)
            say "system packages (apt): $APT_PACKAGES"
            # Passed through env, not exported: sudo's env_reset drops exported variables.
            as_root env DEBIAN_FRONTEND=noninteractive apt-get update
            # shellcheck disable=SC2086 # the package list is split on purpose
            as_root env DEBIAN_FRONTEND=noninteractive \
                apt-get install -y --no-install-recommends $APT_PACKAGES
            ;;
        pacman)
            say "system packages (pacman): $PACMAN_PACKAGES"
            # shellcheck disable=SC2086 # the package list is split on purpose
            as_root pacman -S --needed --noconfirm $PACMAN_PACKAGES
            ;;
        *)
            say "no supported package manager (apt-get or pacman) found; on Linux, install these yourself"
            say "(macOS needs none of them):"
            say "  Debian/Ubuntu: $APT_PACKAGES"
            say "  Arch/Omarchy:  $PACMAN_PACKAGES"
            say "continuing as with --no-system-deps"
            ;;
    esac
}

# --- 2. uv -------------------------------------------------------------------

uv_target() {
    arch=$(uname -m)
    case $arch in
        x86_64 | amd64) arch=x86_64 ;;
        aarch64 | arm64) arch=aarch64 ;;
        *) fail "no uv build for $arch; install uv yourself (https://docs.astral.sh/uv/)" ;;
    esac
    case $(uname -s) in
        Linux)
            libc=gnu
            for loader in /lib/ld-musl-*; do
                if [ -e "$loader" ]; then libc=musl; fi
            done
            echo "$arch-unknown-linux-$libc"
            ;;
        Darwin) echo "$arch-apple-darwin" ;;
        *) fail "no uv build for $(uname -s); install uv yourself" ;;
    esac
}

install_uv() {
    target=$(uv_target)
    archive="uv-$target.tar.gz"
    base="https://github.com/astral-sh/uv/releases/download/$UV_VERSION"
    say "uv not found; installing uv $UV_VERSION from $base/$archive"
    fetch "$base/$archive" "$workdir/$archive"
    fetch "$base/$archive.sha256" "$workdir/uv.sha256"
    verify "$workdir/$archive" "$archive" "$workdir/uv.sha256"
    mkdir -p "$workdir/uv" "$uv_bin"
    tar -xzf "$workdir/$archive" -C "$workdir/uv"
    for tool in uv uvx; do
        cp "$workdir/uv/uv-$target/$tool" "$uv_bin/$tool"
        chmod 755 "$uv_bin/$tool"
    done
}

find_uv() {
    uv_bin=${XDG_BIN_HOME:-$HOME/.local/bin}
    if have uv; then
        uv_cmd=$(command -v uv)
    elif [ -x "$uv_bin/uv" ]; then
        uv_cmd=$uv_bin/uv
    else
        install_uv
        uv_cmd=$uv_bin/uv
    fi
    say "using uv: $uv_cmd"
}

# --- 3. the wheel ------------------------------------------------------------

release_wheel() {
    case $SEVN_RELEASE_BASE in
        https://* | file://*) ;;
        *) fail "SEVN_RELEASE_BASE must be an https:// or file:// URL" ;;
    esac
    base=${SEVN_RELEASE_BASE%/}
    sums="$workdir/SHA256SUMS"
    say "fetching $base/SHA256SUMS"
    fetch "$base/SHA256SUMS" "$sums"
    count=$(awk '$2 ~ /^\*?sevn-[^\/]*-py3-none-any\.whl$/ {n++} END {print n + 0}' "$sums")
    [ "$count" -eq 1 ] || fail "SHA256SUMS lists $count sevn wheels, expected one"
    name=$(awk '$2 ~ /^\*?sevn-[^\/]*-py3-none-any\.whl$/ {print $2; exit}' "$sums")
    name=${name#\*}
    say "fetching $base/$name"
    fetch "$base/$name" "$workdir/$name"
    verify "$workdir/$name" "$name" "$sums"
    wheel_path=$workdir/$name
}

url_wheel() {
    case $wheel in
        https://*) ;;
        *) fail "--wheel URL must use https://" ;;
    esac
    name=${wheel##*/}
    case $name in
        *.whl) ;;
        *) fail "--wheel URL must name a .whl file" ;;
    esac
    fetch "${wheel%/*}/SHA256SUMS" "$workdir/SHA256SUMS"
    fetch "$wheel" "$workdir/$name"
    verify "$workdir/$name" "$name" "$workdir/SHA256SUMS"
    wheel_path=$workdir/$name
}

choose_wheel() {
    case $wheel in
        "") release_wheel ;;
        http://* | https://*) url_wheel ;;
        *) wheel_path=$wheel ;;
    esac
}

find_sevn() {
    bin_dir=$("$uv_cmd" tool dir --bin 2>/dev/null || true)
    if [ -n "$bin_dir" ] && [ -x "$bin_dir/sevn" ]; then
        sevn_cmd=$bin_dir/sevn
    elif have sevn; then
        sevn_cmd=$(command -v sevn)
    else
        fail "sevn was installed but cannot be found; check 'uv tool dir --bin'"
    fi
}

offer_path() {
    [ -n "$bin_dir" ] || return 0
    case ":$PATH:" in
        *":$bin_dir:"*) return 0 ;;
    esac
    if [ -t 0 ] && [ -t 1 ]; then
        printf 'sevn-install: %s is not on PATH. Add it to your shell profile (uv tool update-shell)? [y/N] ' "$bin_dir"
        answer=""
        read -r answer || answer=""
        case $answer in
            y | Y | yes | YES)
                "$uv_cmd" tool update-shell
                return 0
                ;;
        esac
    fi
    say "$bin_dir is not on PATH; add it yourself or run: uv tool update-shell"
}

# --- run ---------------------------------------------------------------------

if [ "$system_deps" -eq 1 ]; then
    install_system_packages
fi

find_uv
choose_wheel

say "+ uv tool install --python 3.13 --reinstall-package sevn $wheel_path"
"$uv_cmd" tool install --python 3.13 --reinstall-package sevn "$wheel_path"

find_sevn
offer_path

if [ -n "$home" ]; then
    SEVN_HOME=$home
    export SEVN_HOME
fi

if [ "$service" -eq 1 ]; then
    if [ -n "$home" ]; then
        "$sevn_cmd" service install --home "$home"
    else
        "$sevn_cmd" service install
    fi
fi

"$sevn_cmd" doctor
say "done: $sevn_cmd"
