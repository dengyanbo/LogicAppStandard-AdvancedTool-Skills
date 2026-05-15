# Archive

This folder contains material that's no longer part of the active project
but is kept for historical reference.

## Contents

| Path | Why it's here |
| --- | --- |
| `dotnet/` | The original `LogicAppAdvancedTool` .NET 8 console application — sources, project file, vendored DLLs, embedded resources, sample configs, and its CHANGELOG. **Archived because the Python port (`python-port/lat`) has full functional parity, supports Entra ID storage (which the .NET version cannot), and the project has standardized on Python for future development.** The .NET source still builds in Visual Studio / .NET 8 SDK (modulo a pre-existing ClickOnce/.NET-9-SDK issue) — kept for users who still want a single-file binary, and as the canonical reference for the byte-level parity contract. |
| `skills/logicapp-std-tool-python-port/` | The "porting" skill that drove the initial migration of `LogicAppAdvancedTool` to Python. The port is complete — this skill has no remaining runtime purpose. Kept as a record of how the port was constructed (Murmur32/64 spec, ZSTD framing, partition-key derivation, table-naming, etc.). |
| `readme_old.md` | The original .NET tool's README from the upstream repo (`microsoft/Logic-App-STD-Advanced-Tools`). Used as a style reference when writing `python-port/README.md`. Kept for traceability. |

## Notes

- Files here are **NOT** discovered by any tool (Copilot CLI, build, tests).
- The Python port (`../python-port/`) has **zero runtime dependency** on
  anything in this folder — no subprocess calls, no DLL loads, no file
  reads. Verified by grep: every `.NET` / `dotnet` mention in the Python
  source is a docstring or comment for traceability only.
- If you want to build the .NET tool: `cd dotnet && dotnet build` (you may
  need .NET 8 SDK specifically — newer SDKs hit a `GenerateTrustInfo`
  ClickOnce issue that's unrelated to the port).
- If you need to port the .NET tool to another language, the references
  and playbooks under `skills/logicapp-std-tool-python-port/` are useful
  starting points — copy them out of `archive/` and adapt.
- Anything in this folder can be safely deleted if disk space matters; no
  active code depends on it.
