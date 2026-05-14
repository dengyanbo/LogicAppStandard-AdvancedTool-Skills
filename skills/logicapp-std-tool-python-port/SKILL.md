---
name: logicapp-std-tool-python-port
description: |
  Port the Azure Logic Apps Standard Advanced Tool (LogicAppAdvancedTool, .NET 8
  console app) to a from-scratch Python re-implementation with full command
  parity (~35 top-level commands plus 7 Tools sub-commands), using the Azure
  SDK for Python and Typer for the CLI. The Python port must reproduce the
  byte-for-byte storage prefix hashing (Murmur32/64), ZSTD/Deflate framing,
  table/blob naming conventions, MSI-based ARM auth, and run-history rewiring
  used by the original .NET tool, so that operations against a live Logic App
  Standard storage account produce identical results.

  Invoke this skill when:
    * The user wants to port LogicAppAdvancedTool to Python
    * The user wants to rebuild any subset of its commands in Python
    * The user is investigating how the .NET tool talks to Logic App Standard
      storage and needs an authoritative reference
allowed-tools: [view, grep, glob, edit, create, powershell]
target-source: https://github.com/Drac-Zhang/Logic-App-STD-Advanced-Tools
target-source-canonical: https://github.com/microsoft/Logic-App-STD-Advanced-Tools
target-language: python>=3.11
---

# Skill: Port `LogicAppAdvancedTool` to Python

> Drives a full-parity Python rewrite of the `LogicAppAdvancedTool` .NET 8
> console application. Use this skill when you need to recreate (in whole or
> in part) the Logic App Standard storage-level tooling in Python without
> depending on the original `LogicAppAdvancedTool.exe`.

## 1. What you (the agent) are doing

You are porting a Windows-only .NET 8 console application to Python. The
application directly manipulates the Azure Storage account behind an Azure
Logic Apps Standard site (Tables, Blobs, Queues, File Share) and calls the
Azure Resource Manager (ARM) API through the site's Managed Identity.

**Non-negotiable correctness constraints** — the port is wrong if any of
these differ from the .NET implementation:

1. The Murmur32 and Murmur64 hashes used to derive table/queue/blob names
   from `WEBSITE_SITE_NAME` and `flowId` must match the .NET output byte-for-
   byte. See `references/01-storage-prefix-hashing.md`.
2. The compressed-payload format detection (the *algorithm byte* in
   `DefinitionCompressed`, `InputsLinkCompressed`, `OutputsLinkCompressed`)
   and the variable-length-integer prefix must be decoded identically. See
   `references/03-compression-codec.md`.
3. The partition-key derivation for action/variable tables (Murmur32 of the
   pre-underscore part of the RowKey, modulo 1,048,576, formatted `X5`) must
   match. See `references/02-partition-key.md`.
4. RowKey rewriting during `MergeRunHistory` is case-sensitive on the GUID
   (uppercase). See `references/09-known-traps.md`.

If any of these are wrong the port will produce orphan rows, unreadable
definitions, or operations that silently target the wrong workflow.

## 2. How to use this skill

The skill is structured as a **read-then-act** playbook. Do the steps in
order.

1. Read [`overview.md`](./overview.md) — condensed model of what the .NET
   tool does and how it is laid out.
2. Read [`port-process.md`](./port-process.md) — the step-by-step procedure
   to follow.
3. For every non-trivial mechanism, read the relevant file under
   [`references/`](./references/) **before** writing the Python equivalent.
   These documents cite specific files and line ranges in the C# source so
   you can verify against them.
4. Generate the Python project from [`scaffolding/`](./scaffolding/). The
   scaffold has stubs for every shared utility (settings, MSI, ARM,
   storage helpers, prefix hashing, compression, network probes) — fill
   them in using the reference docs.
5. Port commands one at a time using the per-command files under
   [`playbooks/`](./playbooks/). Each playbook follows the same template
   (`playbooks/_template.md`).
6. Validate using [`validation/`](./validation/) — set up a throwaway
   Logic App Standard, run both the .NET tool and the Python port against
   it, diff resulting storage state and console output.
7. Consult [`troubleshooting.md`](./troubleshooting.md) whenever a parity
   check fails.

## 3. Project layout you will produce

```
<output-project>/
├─ pyproject.toml
├─ README.md
├─ src/lat/
│  ├─ cli.py                   # Typer entry, registers every command
│  ├─ settings.py              # Env-var resolver (mirrors Shared/AppSettings.cs)
│  ├─ msi.py                   # Managed Identity token retrieval + cache
│  ├─ arm.py                   # ARM HTTP helpers
│  ├─ network.py               # DNS / TCP / SSL probes
│  ├─ storage/
│  │   ├─ tables.py            # Paged queries, batched transactions
│  │   ├─ blobs.py
│  │   ├─ shares.py
│  │   ├─ queues.py
│  │   ├─ prefix.py            # MurmurHash32/64 ports + naming helpers
│  │   └─ compression.py       # ZSTD/Deflate framing
│  └─ commands/                # One module per .NET command
└─ tests/
   ├─ unit/                    # Hash vectors, framing vectors, parsers
   └─ parity/                  # Live tests against a sandbox Logic App
```

## 4. Command coverage (full parity)

All commands in `Program.cs` of the source repo must be ported. Group by
category — `playbooks/` mirrors this structure.

* **workflow-management/** — Backup, Revert, Decode, Clone, ConvertToStateful,
  ListVersions, ListWorkflows, RestoreWorkflowWithVersion,
  RestoreSingleWorkflow (deprecated), IngestWorkflow (experimental),
  ValidateWorkflows
* **run-history/** — RetrieveFailures (Date, Run), SearchInHistory,
  GenerateRunHistoryUrl, RetrieveActionPayload, BatchResubmit, CancelRuns,
  MergeRunHistory (experimental, irreversible), ClearJobQueue (deprecated)
* **cleanup/** — CleanUpContainers, CleanUpTables, CleanUpRunHistory
* **validation/** — ValidateStorageConnectivity, ValidateSPConnectivity,
  EndpointValidation, ScanConnections, WhitelistConnectorIP
* **site-management/** — Snapshot (Create, Restore), SyncToLocal (Normal,
  Auto, Batch), FilterHostLogs, GenerateTablePrefix
* **tools/** — ImportAppsettings, CleanEnvironmentVariable, GetMIToken,
  Restart, GeneratePrefix, RunIDToDateTime, DecodeZSTD

## 5. Defaults assumed by this skill

You may override any of these with explicit user direction, but they are the
recommended baseline:

| Concern | Choice |
| --- | --- |
| Python version | 3.11+ |
| CLI library | `typer` (Click under the hood) |
| Async / HTTP | `httpx` |
| ZSTD codec | `zstandard` |
| Deflate codec | stdlib `zlib` |
| Azure SDKs | `azure-data-tables`, `azure-storage-blob`, `azure-storage-file-share`, `azure-storage-queue`, `azure-identity` |
| JSON model layer | `pydantic` v2 |
| Tests | `pytest`; live parity tests gated behind `--live` marker + sandbox env vars |
| Packaging | `pyproject.toml` (PEP 621) with `hatchling` build backend |

## 6. Safety notes (carry these into the port)

* Destructive operations (`MergeRunHistory`, `IngestWorkflow`, `Revert`,
  `CleanUp*`, `CancelRuns`, `ClearJobQueue`) must keep the .NET tool's
  interactive confirmation prompt and experimental-feature banner. Port the
  prompt to a Typer `typer.confirm` (with `--yes` flag to bypass for CI).
* Honor the Storage Tables 100-entity-per-transaction limit when batching
  upserts inside `MergeRunHistory`. See `references/04-table-schema.md`.
* Honor the ARM Resubmit throttle (~50 calls per 5 minutes) inside
  `BatchResubmit` — pause and retry, do not fail. See
  `playbooks/run-history/BatchResubmit.md`.
* Never log the MSI token or the storage connection string. The .NET tool
  caches the token in `Temp/MIToken.json` (gitignored); the Python port
  should follow the same convention but with `~/.cache/lat/mi-token.json`.

## 7. Where to start

If this is a fresh session, do this in order:

1. `view ./overview.md`
2. `view ./port-process.md`
3. `view ./references/01-storage-prefix-hashing.md`
4. `view ./scaffolding/pyproject.toml`
5. Begin Phase 1 of `port-process.md`.
