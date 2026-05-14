#!/usr/bin/env bash
# Install the logicapp-std-operator skill into ~/.agents/skills/ so Copilot
# CLI auto-loads it from any directory.
#
# Usage:
#   ./install.sh            # interactive prompt if target exists
#   ./install.sh --force    # overwrite without prompting
#   TARGET=/custom/path ./install.sh

set -euo pipefail

SOURCE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TARGET="${TARGET:-${HOME}/.agents/skills/logicapp-std-operator}"
FORCE=false
for arg in "$@"; do
    case "$arg" in
        --force|-f) FORCE=true ;;
        --help|-h)
            head -n 12 "$0" | sed -e 's/^# //' -e 's/^#//'
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 1
            ;;
    esac
done

if [ ! -f "${SOURCE_DIR}/SKILL.md" ]; then
    echo "install.sh must be run from inside the skill folder (no SKILL.md in ${SOURCE_DIR})." >&2
    exit 1
fi

if [ -e "${TARGET}" ]; then
    if [ "${FORCE}" != "true" ]; then
        echo "Target already exists: ${TARGET}"
        read -r -p "Overwrite? (y/N) " reply
        case "${reply}" in
            y|Y) ;;
            *) echo "Aborted."; exit 1 ;;
        esac
    fi
    rm -rf "${TARGET}"
fi

mkdir -p "$( dirname "${TARGET}" )"
cp -r "${SOURCE_DIR}" "${TARGET}"

# Strip scaffolding from the destination.
for scaffold in install.ps1 install.sh INSTALL.md; do
    rm -f "${TARGET}/${scaffold}"
done

echo
echo "Installed to ${TARGET}"
echo
echo "Next steps:"
echo "  1. In your Copilot CLI session, run: /skills reload"
echo "     (or /restart if /skills reload doesn't pick it up)"
echo "  2. Verify with: /env"
echo "     -- look for 'logicapp-std-operator' under Skills."
echo "  3. Make sure 'lat' is installed and on PATH:"
echo "     cd <repo>/python-port && uv pip install -e ."
echo
