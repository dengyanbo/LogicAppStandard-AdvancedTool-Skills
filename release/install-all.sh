#!/usr/bin/env bash
# One-click installer for everything: `lat` CLI + agent skill.
#
# Composite installer that runs install-lat.sh then install-skill.sh.
# Aborts on first error.
#
# Usage:
#   ./release/install-all.sh
#   ./release/install-all.sh --force
#   FORCE_VENV=1 PYTHON=python3.12 ./release/install-all.sh

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Parse minimal args.
SKILL_ARGS=()
LAT_ARGS=()  # (currently empty — install-lat.sh reads PYTHON / FORCE_VENV from env)
for arg in "$@"; do
    case "$arg" in
        --force|-f) SKILL_ARGS+=("--force") ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

echo
echo "============================================================"
echo "  Installing lat + logicapp-std-operator skill"
echo "============================================================"
echo

# Step 1: lat (PYTHON / FORCE_VENV inherited from env).
"${SCRIPT_DIR}/install-lat.sh" "${LAT_ARGS[@]}"

echo

# Step 2: skill.
"${SCRIPT_DIR}/install-skill.sh" "${SKILL_ARGS[@]}"

echo
echo "============================================================"
echo "  All done!"
echo "============================================================"
echo
echo "Quick checklist:"
echo "  1. Activate the lat venv:"
echo "     source <repo>/python-port/.venv/bin/activate"
echo "  2. Verify lat:        lat --help"
echo "  3. Open Copilot CLI:  copilot"
echo "  4. Verify the skill:  /skills reload  then  /env"
echo
