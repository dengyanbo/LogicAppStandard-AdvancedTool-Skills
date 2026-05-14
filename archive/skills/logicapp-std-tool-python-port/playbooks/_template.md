# Playbook — `<CommandName>`

> Skeleton every per-command playbook file follows. Copy-paste this into a
> new file under the right category folder and fill in each section. Keep
> sections in this order so the agent can scan playbooks consistently.

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `<TopLevel> [SubCommand]` (e.g. `Backup`, `RetrieveFailures Date`, `Tools DecodeZSTD`) |
| Category | `workflow-management` / `run-history` / `cleanup` / `validation` / `site-management` / `tools` |
| C# entry binding | `Program.cs:<lines>` |
| C# implementation | `Operations/<File>.cs` or `Tools/<File>.cs` |
| Python target | `src/lat/commands/<command>.py`, registered on `<sub-app>` |
| Risk level | safe / mutating / destructive / experimental |

## 2. CLI options (parity table)

| .NET flag | Python flag | Required | Type | Default | Notes |
| --- | --- | --- | --- | --- | --- |
| `-wf/--workflow` | `--workflow / -wf` | yes | str | — | |
| ... | ... | ... | ... | ... | |

If the .NET command takes sub-commands, list each here with its own row
group.

## 3. Behavior summary

A short prose description of what the command does, in operator terms.
*Do not* paraphrase the C# code — describe the user-observable effect.

## 4. C# logic walk-through

Step-by-step description of the C# implementation, with file:line
citations. The goal is to give the agent enough detail to verify the
Python re-implementation behaves identically without re-reading the C#
themselves.

Example structure:

1. `Operations/Backup.cs:13-24` — create `./Backup` folder.
2. `Operations/Backup.cs:21-31` — try to fetch app settings via
   `AppSettings.GetRemoteAppsettings()`; on failure, log and continue.
3. … etc.

## 5. Python implementation outline

Concrete pseudo-code or skeleton showing the intended structure. The
agent fills this in line-for-line.

```python
# src/lat/commands/<command>.py
import typer
from pathlib import Path
from ..settings import settings
from ..storage import tables, compression

def register(parent: typer.Typer) -> None:
    @parent.command("<name>")
    def _cmd(
        # CLI options in parity-table order
    ) -> None:
        """<one-line help>"""
        # 1. ...
        # 2. ...
        # 3. ...
```

## 6. Side effects & preconditions

* **Reads**: which storage tables / blobs / ARM endpoints
* **Writes**: which storage tables / blobs / files on disk / ARM endpoints
* **Required env vars**: subset of the standard set
* **Required RBAC**: e.g. "MI must have Reader on subscription"
* **Preconditions**: e.g. "workflow must currently exist", "wwwroot must
  contain `<workflow>/workflow.json`"

## 7. Safety

* Does this command prompt for confirmation? Where? What banner?
* Does it print an experimental-feature warning?
* What does the `--yes` bypass do?
* Is it reversible? If not, document under §9.

## 8. Output format

What the user sees on stdout. If the .NET tool uses `ConsoleTable`, list
the columns. Use `rich.table.Table` for parity.

## 9. Failure modes & known issues

* What errors are surfaced from C# as `UserInputException` /
  `ExpectedException`? Reproduce as `typer.BadParameter` and `RuntimeError`
  respectively.
* Anything in `references/09-known-traps.md` that applies here? Cross-link
  by trap number.

## 10. Parity test

```python
# tests/parity/test_<command>.py
@pytest.mark.live
def test_<command>_matches_dotnet(sandbox):
    # 1. snapshot storage state
    # 2. run .NET tool with args X
    # 3. snapshot
    # 4. restore initial state
    # 5. run Python port with args X
    # 6. snapshot
    # 7. assert step (3) and (6) diff is empty
```

Specify exactly:
* args to use for both runs
* which storage/blob state to compare (table names, columns)
* tolerances (Timestamp column, ETag, etc.)

## 11. Registration

What the agent must add to `src/lat/cli.py`:

```python
from .commands.<command> import register as _reg_<command>
_reg_<command>(<sub_app>)
```
