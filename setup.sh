#!/bin/sh
cd `dirname $0`

# Create a virtual environment to run our code.
VENV_NAME="venv"
PYTHON="$VENV_NAME/bin/python"
ENV_ERROR="This module requires Python >=3.10, pip, and virtualenv to be installed."

SUDO="sudo"
if [ "$(id -u)" = "0" ] || ! command -v sudo >/dev/null 2>&1; then
    SUDO=""
fi

apt_install() {
    command -v apt-get >/dev/null 2>&1 || return 1
    $SUDO apt-get -qq update >/dev/null 2>&1
    $SUDO apt-get install -qqy "$@" >/dev/null 2>&1
}

# --- virtualenv -----------------------------------------------------------
if ! python3 -m venv $VENV_NAME >/dev/null 2>&1; then
    echo "Failed to create virtualenv."
    if command -v apt-get >/dev/null 2>&1; then
        echo "Detected Debian/Ubuntu, attempting to install python3-venv automatically."
        if ! apt_install python3-venv python3.12-venv || ! python3 -m venv $VENV_NAME >/dev/null 2>&1; then
            echo "$ENV_ERROR" >&2
            exit 1
        fi
    else
        echo "$ENV_ERROR" >&2
        exit 1
    fi
fi

# --- python dependencies --------------------------------------------------
echo "Virtualenv found/created. Installing/upgrading Python packages..."
if ! [ -f .installed ]; then
    $PYTHON -m pip install -Uqq pip >/dev/null 2>&1
    if ! $PYTHON -m pip install -r requirements.txt -Uqq; then
        exit 1
    fi
    # bleak is the one dependency that can fail to load without a runtime stack;
    # verify it imports before declaring success.
    if ! $PYTHON -c "import bleak" >/dev/null 2>&1; then
        echo "ERROR: bleak failed to import after install." >&2
        exit 1
    fi
    touch .installed
fi

# --- Bluetooth runtime check (advisory, never fatal) ----------------------
# Unlike a missing compiled library, a missing/blocked Bluetooth adapter is
# fixable at runtime (plug in a dongle, unblock rfkill). Dying here would stop
# viam-server from even starting the module to report the problem - so we warn
# loudly and exit 0, letting the component come up and surface the error in its
# readings ("connected": false).
if command -v bluetoothctl >/dev/null 2>&1; then
    if ! bluetoothctl list 2>/dev/null | grep -q .; then
        echo "WARNING: no Bluetooth adapter found (bluetoothctl list is empty)." >&2
        echo "         Plug in a USB BLE adapter or check rfkill; the module will" >&2
        echo "         start but report 'connected: false' until an adapter exists." >&2
    fi
else
    echo "NOTE: bluetoothctl not found; cannot pre-check the Bluetooth adapter." >&2
fi

exit 0
