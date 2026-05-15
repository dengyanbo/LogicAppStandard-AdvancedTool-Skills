# Install — `logicapp-std-operator` skill

The skill ships at `.github/skills/logicapp-std-operator/` in this repo, so
**there are two ways to get it loaded into Copilot CLI**:

## Option A — Repo-scoped (zero install)

If you already have this repo cloned, just run `copilot` from inside it.
The CLI walks up from your cwd looking for `.github/skills/` and auto-loads
every `SKILL.md` it finds.

```bash
git clone https://github.com/dengyanbo/LogicAppStandard-AdvancedTool-Skills.git
cd LogicAppStandard-AdvancedTool-Skills           # or any subdirectory
copilot
# verify with: /env
```

Pros: zero install, always tracks the repo's version.
Cons: only works when your cwd is inside this repo.

## Option B — User-global (works anywhere)

Copy the skill to `~/.agents/skills/`, which Copilot CLI scans for every
session regardless of cwd. Use the bundled installer:

### Windows (PowerShell)

```powershell
cd .github\skills\logicapp-std-operator
.\install.ps1
```

### Linux / Mac (bash)

```bash
cd .github/skills/logicapp-std-operator
./install.sh
```

The installer is idempotent — re-run it after pulling new commits to
update the global copy. Pass `-Force` (PS) or `--force` (bash) to skip the
"target exists" prompt.

Pros: skill is available in any directory.
Cons: you have to remember to re-run after `git pull` to pick up updates.

## Verify

In your Copilot CLI session:

```
/env
```

Look under "Skills". You should see `logicapp-std-operator` listed
alongside the builtins. The `source` column will say `Local` (repo-scoped)
or `personal-agents` (global).

If you don't see it:

1. `/skills reload` to force a rescan
2. `/restart` to reload the session
3. Check `/env` again

## Uninstall

### Global

```powershell
# Windows
Remove-Item -Recurse $env:USERPROFILE\.agents\skills\logicapp-std-operator
```

```bash
# Linux / Mac
rm -rf ~/.agents/skills/logicapp-std-operator
```

### Repo-scoped

Don't run `copilot` from inside this repo, or delete the
`.github/skills/logicapp-std-operator/` folder.

## Layout (after install)

```
~/.agents/skills/logicapp-std-operator/
├── SKILL.md
├── overview.md
├── setup.md
├── command-safety-matrix.md
├── playbooks/
│   ├── restore-deleted-workflow.md
│   ├── triage-failed-runs.md
│   ├── diagnose-storage-issue.md
│   ├── safe-cleanup.md
│   ├── snapshot-and-rollback.md
│   ├── bulk-resubmit-or-cancel.md
│   ├── unblock-connector-firewall.md
│   ├── merge-run-history.md
│   └── diagnostic-first.md
├── references/
│   ├── env-vars.md
│   ├── aad-vs-connstring.md
│   ├── nsp-troubleshooting.md
│   ├── dotnet-command-mapping.md
│   └── time-helpers.md
└── validation/
    └── skill-smoke-tests.md
```

The installer omits `install.ps1`, `install.sh`, and this `INSTALL.md` from
the destination — they're scaffolding, not part of the runtime skill.

## Prerequisite — install `lat`

This skill drives the `lat` CLI. Install `lat` first:

```bash
cd <repo>/python-port
uv pip install -e .      # or: pip install -e .
lat --help
```

The skill assumes `lat` is on PATH when you invoke any playbook.
