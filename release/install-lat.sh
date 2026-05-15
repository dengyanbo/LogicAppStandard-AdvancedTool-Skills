#!/usr/bin/env bash
# One-click installer for the `lat` Python CLI.
#
# Sets up a Python venv under python-port/ and installs `lat` editably.
# Auto-detects `uv` and uses it if present (much faster than pip); falls
# back to python -m venv + pip.
#
# Usage:
#   ./release/install-lat.sh
#   PYTHON=python3.12 ./release/install-lat.sh
#   FORCE_VENV=1 ./release/install-lat.sh

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "${SCRIPT_DIR}/.." && pwd )"
PY_PORT_DIR="${REPO_ROOT}/python-port"
VENV_DIR="${PY_PORT_DIR}/.venv"

if [ ! -f "${PY_PORT_DIR}/pyproject.toml" ]; then
    echo "Error: could not find python-port/pyproject.toml under ${REPO_ROOT}" >&2
    exit 1
fi

# Decide Python interpreter.
PYTHON="${PYTHON:-}"
if [ -z "${PYTHON}" ]; then
    for candidate in python3 python; do
        if command -v "${candidate}" >/dev/null 2>&1; then
            PYTHON="${candidate}"
            break
        fi
    done
fi
if [ -z "${PYTHON}" ]; then
    echo "Error: no Python interpreter found on PATH." >&2
    echo "Install Python >= 3.11 (https://www.python.org/) and retry." >&2
    exit 1
fi

# Check Python version.
ver_line=$("${PYTHON}" -c "import sys; print('{}.{}'.format(sys.version_info.major, sys.version_info.minor))")
ver_major=$(echo "${ver_line}" | cut -d. -f1)
ver_minor=$(echo "${ver_line}" | cut -d. -f2)
if [ "${ver_major}" -lt 3 ] || { [ "${ver_major}" -eq 3 ] && [ "${ver_minor}" -lt 11 ]; }; then
    echo "Error: Python ${ver_line} found, but lat needs Python >= 3.11." >&2
    exit 1
fi

# Detect uv.
HAVE_UV=0
if command -v uv >/dev/null 2>&1; then
    HAVE_UV=1
fi

echo "Installing lat Python CLI..."
echo "  Repo root:    ${REPO_ROOT}"
echo "  python-port:  ${PY_PORT_DIR}"
echo "  Python:       ${PYTHON} (${ver_line})"
echo "  Backend:      $([ ${HAVE_UV} -eq 1 ] && echo 'uv (preferred)' || echo 'pip via venv')"
echo "  Venv:         ${VENV_DIR}"
echo

# Step 1: create venv.
if [ -n "${FORCE_VENV:-}" ] && [ -d "${VENV_DIR}" ]; then
    echo "Removing existing venv..."
    rm -rf "${VENV_DIR}"
fi
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating venv..."
    (
        cd "${PY_PORT_DIR}"
        if [ ${HAVE_UV} -eq 1 ]; then
            uv venv --python "${PYTHON}"
        else
            "${PYTHON}" -m venv .venv
        fi
    )
else
    echo "Venv already exists — reusing (set FORCE_VENV=1 to recreate)."
fi

# Step 2: install lat editably.
echo "Installing lat (editable)..."
(
    cd "${PY_PORT_DIR}"
    if [ ${HAVE_UV} -eq 1 ]; then
        uv pip install -e .
    else
        "${VENV_DIR}/bin/pip" install -e .
    fi
)

# Step 3: verify.
echo
echo "========================================================="
echo "lat installed successfully"
echo "========================================================="
echo
echo "To use lat in your current shell, activate the venv:"
echo "  source ${VENV_DIR}/bin/activate"
echo
echo "Then verify:"
echo "  lat --help"
echo
echo "Or run lat directly without activating:"
echo "  ${VENV_DIR}/bin/lat --help"
echo
