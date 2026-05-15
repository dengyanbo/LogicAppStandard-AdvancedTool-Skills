# Logic App Standard Advanced Tool

> ⚠️ **Upstream has moved.** The canonical maintained version of the **.NET**
> tool now lives at
> [microsoft/Logic-App-STD-Advanced-Tools](https://github.com/microsoft/Logic-App-STD-Advanced-Tools).
> This fork additionally hosts a **Python port** (`lat`) and an
> **AI agent skill** that drives it.

Three related deliverables live in this repo:

1. **`LogicAppAdvancedTool`** — the original .NET 8 console tool ([`dotnet/`](dotnet/))
2. **`lat`** — a Python re-implementation of the same commands, byte-for-byte
   parity for storage hashing / compression, plus Entra ID storage support
   ([`python-port/`](python-port/))
3. **`logicapp-std-operator`** — a Copilot CLI agent skill that uses `lat` to
   diagnose, recover, and operate Logic Apps Standard at storage / ARM level
   ([`.github/skills/logicapp-std-operator/`](.github/skills/logicapp-std-operator/))

Pick whichever fits your workflow — they all do the same job (port-wise) and
can be used interchangeably.

## Repository layout

| Top-level | What it is | Active? |
| --- | --- | --- |
| **[`.github/skills/`](.github/skills/)** | Copilot CLI agent skill ([`logicapp-std-operator`](.github/skills/logicapp-std-operator/)) — auto-discovered when you run `copilot` from inside this repo | ✅ active |
| **[`dotnet/`](dotnet/)** | Original .NET 8 console tool — sources, project file, vendored DLLs, embedded resources, sample configs, .NET-tool changelog | ✅ active |
| **[`python-port/`](python-port/)** | `lat` Python CLI — full command parity with .NET; supports Entra ID storage; ships with 296 unit tests | ✅ active |
| **[`release/`](release/)** | One-click installers for `lat` + the agent skill | ✅ active |
| **[`archive/`](archive/)** | Historical material no longer in active use (the porting skill that drove the .NET → Python migration; the original .NET README used as a style reference) | 📦 archived |

## Quick start

The fastest way to get everything set up:

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

This installs **both**:

- `lat` Python CLI into a venv under `python-port/.venv/`
- The `logicapp-std-operator` agent skill into `~/.agents/skills/`

After that:

```powershell
# Activate the venv to put `lat` on PATH (each new shell)
.\python-port\.venv\Scripts\Activate.ps1
lat --help

# Open Copilot CLI; the skill loads automatically
copilot
/env             # confirm logicapp-std-operator is loaded
```

Just want one piece? See [`release/README.md`](release/README.md) for
`install-skill.*` (skill only) and `install-lat.*` (lat only) recipes.

## Which to use when

| You want to... | Use |
| --- | --- |
| Run a single ad-hoc command quickly (or you're on Windows + .NET) | `.NET tool` — see [`dotnet/README.md`](dotnet/README.md) |
| Cross-platform usage, scripting, modern auth (Entra ID storage), or you don't want to install .NET | `lat` Python CLI — see [`python-port/README.md`](python-port/README.md) |
| Talk to an AI assistant in plain English ("restore my deleted workflow") and have it drive `lat` for you with safety rails | The `logicapp-std-operator` skill — see [`.github/skills/logicapp-std-operator/INSTALL.md`](.github/skills/logicapp-std-operator/INSTALL.md) |

## What `lat` / the .NET tool does

Both let you operate Logic Apps Standard **below** the Azure portal layer.
Some highlights:

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

See [`dotnet/README.md`](dotnet/README.md) or
[`python-port/README.md`](python-port/README.md) for the full command list.

## License

MIT (matches the upstream .NET source).
