#!/usr/bin/env bash
#
# Adnacom Monitor SDK installer.
#
# Detects the distribution and Python version, installs the required
# system packages, creates the adnacom-venv virtual environment with a
# Python that matches the SDK's pre-compiled modules, and installs the
# application into it. Run it from the SDK directory:
#
#     ./install.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_ROOT/adnacom-venv"
PKG_DIR="$REPO_ROOT/adnacom_monitor"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Privilege helper (containers may not have sudo; desktops usually do)
# ---------------------------------------------------------------------------

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null || die "This script needs root privileges to install system packages, and 'sudo' was not found. Re-run as root."
    SUDO="sudo"
fi

# ---------------------------------------------------------------------------
# Which Python versions does this SDK build ship?
# ---------------------------------------------------------------------------

supported_versions() {
    local so
    for so in "$PKG_DIR"/Protocol.cpython-3*.so; do
        [ -e "$so" ] || continue
        local tag=${so##*/Protocol.cpython-3}   # e.g. 10-x86_64-linux-gnu.so
        printf '3.%s\n' "${tag%%-*}"
    done | sort -uV
}

SUPPORTED=$(supported_versions)
[ -n "$SUPPORTED" ] || die "No pre-compiled modules found in $PKG_DIR — is this a complete SDK checkout?"

python_version_of() {
    "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null
}

is_supported() {
    printf '%s\n' "$SUPPORTED" | grep -qx "$1"
}

# ---------------------------------------------------------------------------
# Detect the distribution and install system dependencies
# ---------------------------------------------------------------------------

if command -v apt-get >/dev/null; then
    PKGMGR="apt"
elif command -v dnf >/dev/null; then
    PKGMGR="dnf"
elif command -v zypper >/dev/null; then
    PKGMGR="zypper"
elif command -v pacman >/dev/null; then
    PKGMGR="pacman"
else
    die "Unsupported distribution: none of apt, dnf, zypper or pacman found."
fi

info "Installing system dependencies ($PKGMGR)…"
case "$PKGMGR" in
    apt)
        $SUDO apt-get update -q
        $SUDO apt-get install -y python3-venv python3-gi python3-gi-cairo \
            gir1.2-gtk-3.0 gir1.2-glib-2.0
        ;;
    dnf)
        $SUDO dnf install -y python3-gobject gtk3 gobject-introspection
        ;;
    zypper)
        $SUDO zypper --non-interactive install python3-gobject gtk3 \
            gobject-introspection
        ;;
    pacman)
        $SUDO pacman -S --needed --noconfirm python-gobject gtk3 \
            gobject-introspection
        ;;
esac

# ---------------------------------------------------------------------------
# Pick an interpreter that matches a shipped pre-compiled module.
# The distro's own python3 is preferred: its version matches the distro's
# GTK bindings (python3-gi), so nothing has to be compiled.
# ---------------------------------------------------------------------------

PYTHON=""
SYSTEM_PY_VERSION="$(python_version_of python3 || true)"

if [ -n "$SYSTEM_PY_VERSION" ] && is_supported "$SYSTEM_PY_VERSION"; then
    PYTHON="python3"
else
    for candidate in python3.13 python3.12 python3.11 python3.10; do
        v="$(python_version_of "$candidate" || true)"
        if [ -n "$v" ] && is_supported "$v"; then
            PYTHON="$candidate"
            break
        fi
    done
fi

[ -n "$PYTHON" ] || die "No installed Python matches this SDK's pre-compiled modules.
       System python3 is ${SYSTEM_PY_VERSION:-not found}; supported versions: $(echo $SUPPORTED | tr '\n' ' ').
       Install one of the supported versions and re-run this script."

info "Using $PYTHON (Python $(python_version_of "$PYTHON"))"

# ---------------------------------------------------------------------------
# Create the virtual environment and install the application
# ---------------------------------------------------------------------------

if [ "$PYTHON" = "python3" ]; then
    # System interpreter: reuse the distro GTK bindings via system site-packages.
    VENV_FLAGS="--system-site-packages"
    NEEDS_PYGOBJECT=0
else
    # Non-default interpreter: the distro gi bindings are compiled for the
    # system python3 and cannot be reused — build PyGObject in a clean venv.
    VENV_FLAGS=""
    NEEDS_PYGOBJECT=1
    info "Installing PyGObject build dependencies…"
    case "$PKGMGR" in
        apt)
            $SUDO apt-get install -y "${PYTHON}-dev" "${PYTHON}-venv" \
                libgirepository1.0-dev libcairo2-dev pkg-config gcc
            ;;
        dnf)
            $SUDO dnf install -y gobject-introspection-devel cairo-devel \
                cairo-gobject-devel pkgconf gcc python3-devel
            ;;
        zypper)
            $SUDO zypper --non-interactive install gobject-introspection-devel \
                cairo-devel pkgconf gcc python3-devel
            ;;
        pacman)
            $SUDO pacman -S --needed --noconfirm gobject-introspection cairo \
                pkgconf gcc
            ;;
    esac
fi

info "Creating virtual environment at $VENV_DIR…"
rm -rf "$VENV_DIR"
# shellcheck disable=SC2086
"$PYTHON" -m venv $VENV_FLAGS "$VENV_DIR"

info "Installing adnacom-monitor…"
"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel >/dev/null
if [ "$NEEDS_PYGOBJECT" -eq 1 ]; then
    # <3.52 because PyGObject 3.52+ needs girepository-2.0 (absent on Ubuntu 22.04)
    "$VENV_DIR/bin/pip" install pycairo "PyGObject<3.52"
fi
"$VENV_DIR/bin/pip" install "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

info "Verifying the installation…"
"$VENV_DIR/bin/python" -c "
import gi
from adnacom_monitor.Protocol import DeviceDataReader
from adnacom_monitor import __version__
print('  adnacom-monitor %s OK (gi: %s)' % (__version__, gi.__file__))
"

cat <<EOF

Installation complete. PCIe device access requires root, so run:

    sudo $VENV_DIR/bin/adnacom-monitor

If you see a "cannot open display" error, run this first, then retry:

    xhost +SI:localuser:root
    sudo env DISPLAY=\$DISPLAY XAUTHORITY=\$XAUTHORITY $VENV_DIR/bin/adnacom-monitor

To run without sudo long-term, see "Running Without Root (udev rule)" in README.md.
EOF
