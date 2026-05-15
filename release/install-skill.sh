#!/usr/bin/env bash
# One-click installer for the logicapp-std-operator skill.
#
# Installs the agent skill to ~/.agents/skills/ so Copilot CLI auto-loads it
# from any directory. Wraps the skill-bundled installer at
# .github/skills/logicapp-std-operator/install.sh.
#
# Usage:
#   ./release/install-skill.sh
#   ./release/install-skill.sh --force
#   TARGET=/custom/path ./release/install-skill.sh

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "${SCRIPT_DIR}/.." && pwd )"
SKILL_BUNDLED="${REPO_ROOT}/.github/skills/logicapp-std-operator/install.sh"

if [ ! -f "${SKILL_BUNDLED}" ]; then
    echo "Error: could not find skill installer at ${SKILL_BUNDLED}" >&2
    echo "Is this script running from inside the repo?" >&2
    exit 1
fi

echo "Installing logicapp-std-operator skill..."
echo "  Repo root:     ${REPO_ROOT}"
echo "  Delegating to: ${SKILL_BUNDLED}"
echo

exec "${SKILL_BUNDLED}" "$@"
