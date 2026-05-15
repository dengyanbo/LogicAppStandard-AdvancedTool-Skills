# Logic App Standard Advanced Tool

A Python CLI (`lat`) and matching Copilot agent skill for diagnosing,
recovering, and operating **Azure Logic Apps Standard** deployments at a
level below what the Azure portal exposes — workflow restore, version
drilldown, run-history triage, storage cleanup, network validation, and more.

> 📜 **Project history.** This repo started as a fork of the .NET 8
> [`LogicAppAdvancedTool`](https://github.com/microsoft/Logic-App-STD-Advanced-Tools).
> A complete Python port (`lat`) was built with byte-for-byte parity on
> hashing/compression algorithms, plus Entra ID storage support that the
> original lacked. As of this revision, **the project has standardized on
> Python**; the original .NET source has been archived under
> [`archive/dotnet/`](archive/dotnet/) for reference but is no longer the
> primary supported tool.

## What you can use

| Component | Path | What it is |
| --- | --- | --- |
| **`lat` CLI** | [`python-port/`](python-port/) | Cross-platform Python re-implementation; 32 commands across 6 sub-apps; supports both classic conn-string and modern Entra ID storage authentication |
| **`logicapp-std-operator` skill** | [`.github/skills/logicapp-std-operator/`](.github/skills/logicapp-std-operator/) | Copilot CLI agent skill that drives `lat` with safety rails (read-only-first, ask-user before any destructive op, .NET-name aliases) |
| **One-click installers** | [`release/`](release/) | PS + bash scripts that install `lat` + the skill in a single command |
| **Archive** | [`archive/`](archive/) | The original .NET source, the porting skill that drove the migration, and other historical material |

## Quick start

```powershell
# Windows
git clone <this-repo>
cd Logic-App-STD-Advanced-Tools
.\release\install-all.ps1
```

```bash
# Linux / Mac
git clone <this-repo>
cd Logic-App-STD-Advanced-Tools
./release/install-all.sh
```

This installs both:

- `lat` Python CLI into a venv under `python-port/.venv/`
- The `logicapp-std-operator` agent skill into `~/.agents/skills/`

After that:

```powershell
# Activate the venv to put lat on PATH (each new shell)
.\python-port\.venv\Scripts\Activate.ps1
lat --help

# Open Copilot CLI; the skill loads automatically
copilot
/env             # confirm logicapp-std-operator is loaded
```

Just want one piece? See [`release/README.md`](release/README.md) for
`install-skill.*` (skill only) and `install-lat.*` (lat only) recipes.

## What `lat` does

Operates Logic Apps Standard **below** the Azure portal layer:

- **Recover a deleted workflow** — the runtime keeps definitions for ~90 days in
  a storage table; the tool restores from there
- **Roll back to a previous version** — read any historical `FLOWVERSION` row,
  decompress the definition, write it back
- **Triage failed runs** at scale — bulk dump every failure on a date, search
  payloads for a keyword, emit Azure-portal monitor URLs
- **Diagnose connectivity** — DNS + TCP + auth probe for every storage
  service endpoint, every Service Provider in `connections.json`, any HTTP
  endpoint
- **Snapshot + restore** entire `wwwroot` and app settings before a risky deploy
- **Clean up old run history** to control storage cost
- **Whitelist Azure Connector IPs** in a downstream Storage / Key Vault /
  Event Hub firewall

See [`python-port/README.md`](python-port/README.md) for the full command list
(32 commands across `workflow`, `runs`, `cleanup`, `validate`, `site`, `tools`).

## Use it with an AI assistant

The agent skill at [`.github/skills/logicapp-std-operator/`](.github/skills/logicapp-std-operator/)
makes `lat` invokable from Copilot CLI in plain English:

> "Help — I accidentally deleted a workflow called `OrderProcessing`. Can I get it back?"

The skill walks the agent through the right diagnostic / recovery playbook,
gates every destructive command on explicit user confirmation, and supports
both English and Chinese prompts plus the classic .NET command names
(`RestoreSingleWorkflow`, `BatchResubmit`, etc. — mapped silently to their
`lat` equivalents).

## Why Python (and not the .NET tool)

| Concern | Python `lat` | Archived .NET tool |
| --- | --- | --- |
| Modern storage auth (managed identity, no shared key) | ✅ supported via `DefaultAzureCredential` | ❌ requires legacy `AzureWebJobsStorage` conn string |
| Cross-platform | ✅ Linux / Mac / Windows / Kudu | Windows + .NET 8 runtime |
| Install | `pip install -e .` | Build via Visual Studio publish, copy exe |
| AI agent integration | ✅ skill at `.github/skills/` calls `lat` | Doesn't compose with the skill |
| Editable / debuggable | ✅ edit a `.py`, instant feedback | Recompile cycle |

The .NET source is preserved in `archive/dotnet/` for users who already
depend on the exe; no active development happens there.

## License

MIT.
