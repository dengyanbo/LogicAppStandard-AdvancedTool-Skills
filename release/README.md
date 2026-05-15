# Release / installer scripts

One-click installers for the artifacts in this repo. Pick one of three.

## Quick start

| You want to... | Run (PowerShell) | Run (bash) |
| --- | --- | --- |
| **Install everything** (lat CLI + agent skill) | `.\release\install-all.ps1` | `./release/install-all.sh` |
| Install just the **agent skill** (globally) | `.\release\install-skill.ps1` | `./release/install-skill.sh` |
| Install just **`lat`** (Python CLI) | `.\release\install-lat.ps1` | `./release/install-lat.sh` |

All scripts:

- Self-locate the repo root (work from any cwd)
- Idempotent: safe to re-run after `git pull` to upgrade
- Print exact paths and next steps when done

## What gets installed where

### `install-skill.*`

Wraps the skill-bundled installer at
[`.github/skills/logicapp-std-operator/install.ps1`](../.github/skills/logicapp-std-operator/install.ps1).
Copies the skill folder to:

| OS | Target |
| --- | --- |
| Windows | `%USERPROFILE%\.agents\skills\logicapp-std-operator\` |
| Linux / Mac | `~/.agents/skills/logicapp-std-operator/` |

That path is auto-scanned by Copilot CLI on every session — the skill becomes
available regardless of your current directory.

**Flags / env:**
- `-Force` (PS) / `--force` (bash) — overwrite existing install without prompt
- `-Target <path>` (PS) / `TARGET=<path>` (bash) — install somewhere else

### `install-lat.*`

Sets up a Python venv under `python-port/.venv/` and installs the `lat` CLI
editably (`pip install -e python-port/`). The result is:

| Component | Location |
| --- | --- |
| Venv | `<repo>/python-port/.venv/` |
| `lat` executable | `<repo>/python-port/.venv/Scripts/lat.exe` (Win) / `<repo>/python-port/.venv/bin/lat` (POSIX) |

**Auto-detects** `uv` and uses it if present (much faster than pip). Falls
back to `python -m venv` + `pip` otherwise.

**Requirements:**
- Python ≥ 3.11 on `PATH` (the script will check and refuse if older)
- Either `uv` (recommended) or `pip` available

**Flags / env:**
- `-ForceVenv` (PS) / `FORCE_VENV=1` (bash) — recreate venv from scratch
- `-Python <interpreter>` (PS) / `PYTHON=<interpreter>` (bash) — override
  Python (default: `python` or `python3`, whichever resolves first)

### `install-all.*`

Composite: runs `install-lat.*` then `install-skill.*`, aborting if either
fails. Use this for first-time setup. Accepts both sets of flags:

```powershell
# PowerShell — full reinstall with all flags
.\release\install-all.ps1 -Force -ForceVenv -Python python3.12
```

```bash
# bash
FORCE_VENV=1 PYTHON=python3.12 ./release/install-all.sh --force
```

## Verifying the install

After running, open a Copilot CLI session in any directory:

```
copilot
/skills reload
/env
```

The `Skills` section should list `logicapp-std-operator` with source
`personal-agents` and a path under `~/.agents/skills/`.

Also verify `lat`:

```powershell
# PowerShell — activate venv first
<repo>\python-port\.venv\Scripts\Activate.ps1
lat --help
```

```bash
# bash
source <repo>/python-port/.venv/bin/activate
lat --help
```

You should see six sub-apps: `workflow`, `runs`, `cleanup`, `validate`,
`site`, `tools`.

## Upgrading

```bash
git pull
./release/install-all.sh   # idempotent; rerun to pull in changes
```

## Uninstalling

### Remove the skill

```powershell
# Windows
Remove-Item -Recurse $env:USERPROFILE\.agents\skills\logicapp-std-operator
```

```bash
# Linux / Mac
rm -rf ~/.agents/skills/logicapp-std-operator
```

### Remove `lat`

```bash
# From the repo root
rm -rf python-port/.venv
```

(The source code under `python-port/` stays — only the venv is removed.)

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `Python 3.10 found, but lat needs Python >= 3.11` | Old Python on PATH | Install Python 3.11+ and either set `-Python` / `PYTHON=` or update `PATH` |
| `No Python interpreter found on PATH` | Python not installed | Install from python.org or use the OS package manager |
| `Could not find skill installer at ...` | Script run from outside the repo | Run from inside the cloned repo; the script self-locates the repo root |
| Skill installed but `/env` doesn't show it | Cache not refreshed | Run `/skills reload` first, then `/env`. If still missing, `/restart` |
| `release/install-skill.sh: Permission denied` | Executable bit lost on download | `chmod +x release/*.sh` |

## What's NOT in the installers

These installers handle the **client side** (your workstation or the LA's
Kudu container). They do **not**:

- Install Copilot CLI itself — get it from
  https://docs.github.com/copilot/concepts/agents/about-copilot-cli
- Configure Azure credentials (run `az login` separately)
- Touch any Azure resources (no Logic App changes are made by installing
  the tools — they're only side-effect free once you *invoke* the skill)
