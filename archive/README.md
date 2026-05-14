# Archive

This folder contains material that's no longer part of the active project
but is kept for historical reference.

## Contents

| Path | Why it's here |
| --- | --- |
| `skills/logicapp-std-tool-python-port/` | The "porting" skill that drove the initial migration of `LogicAppAdvancedTool` (.NET 8) to Python (`python-port/`). The port is complete — this skill has no remaining runtime purpose. Kept as a record of how the port was constructed (Murmur32/64 spec, ZSTD framing, partition-key derivation, table-naming, etc.). |
| `readme_old.md` | The original .NET tool's README from the upstream repo (`microsoft/Logic-App-STD-Advanced-Tools`). Used as a style reference when writing `python-port/README.md`. Kept for traceability. |

## Notes

- Files here are **NOT** discovered by any tool (Copilot CLI, build, tests).
- The runtime skill that **is** discovered lives at `.github/skills/logicapp-std-operator/`.
- If you need to port the .NET tool to another language, the references and
  playbooks under `skills/logicapp-std-tool-python-port/` are still useful
  starting points — copy them out of `archive/` and adapt.
- Anything in this folder can be safely deleted if disk space matters; no
  active code depends on it.
