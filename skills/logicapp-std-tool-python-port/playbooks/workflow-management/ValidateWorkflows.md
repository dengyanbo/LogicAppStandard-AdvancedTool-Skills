# Playbook — `ValidateWorkflows`

## 1. Identity

| Field | Value |
| --- | --- |
| .NET command | `ValidateWorkflows` |
| Category | workflow-management |
| C# entry binding | `Program.cs:751-762` |
| C# implementation | `Operations/ValidateWorkflows.cs` |
| Python target | `src/lat/commands/validate_workflows.py` → `workflow_app` |
| Risk level | safe (POSTs to hostruntime *validate* endpoint, no writes) |

## 2. CLI options

None.

## 3. Behavior summary

Iterates every direct subdirectory of `wwwroot` that contains a
`workflow.json`, POSTs each one to the LA runtime's design-time
*validate* endpoint, and reports `Validation passed` / `Validation failed`
with the runtime's error message.

## 4. C# walk-through

1. `Operations/ValidateWorkflows.cs:16-22` — enumerate subdirs containing
   `workflow.json`; throw if none.
2. `:26` — retrieve MI token for `management.azure.com`.
3. `:30-53` — for each directory:
   * Build body as `{"properties": <workflow.json contents>}`.
   * POST `<ManagementBaseUrl>/hostruntime/runtime/webhooks/workflow/api/management/workflows/<name>/validate?api-version=2018-11-01`.
   * 400 → record `Validation failed - <message>`.
   * Other non-success → throw.
   * Success → record `Validation passed`.

## 5. Python outline

```python
# src/lat/commands/validate_workflows.py
import json, typer
import httpx
from ..settings import settings
from ..msi import retrieve_token, verify_token

def register(parent: typer.Typer) -> None:
    @parent.command("validate-workflows")
    def _cmd() -> None:
        root = settings.root_folder
        dirs = [d for d in root.iterdir()
                if d.is_dir() and (d / "workflow.json").is_file()]
        if not dirs:
            raise typer.BadParameter("No workflows found")
        typer.echo(f"Found {len(dirs)} workflow(s), start to validate...")

        token = verify_token(retrieve_token())
        for d in dirs:
            body = '{"properties":' + (d / "workflow.json").read_text() + '}'
            url = (
              f"{settings.management_base_url}"
              "/hostruntime/runtime/webhooks/workflow/api/management/workflows/"
              f"{d.name}/validate?api-version=2018-11-01"
            )
            r = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Content-Type": "application/json",
                },
                content=body,
                timeout=60.0,
            )
            if r.is_success:
                typer.echo(f"{d.name}: Validation passed.")
            elif r.status_code == 400:
                typer.echo(f"{d.name}: Validation failed - {r.text}")
            else:
                raise RuntimeError(
                  f"Failed to validate, status code {r.status_code}\n"
                  f"Detail message: {r.text}"
                )
```

## 6. Side effects

* Read-only on disk and storage.
* Calls hostruntime validate API per workflow.

## 7. Safety

Always safe. No prompts.

## 8. Output

One line per workflow:

```
<name>: Validation passed.
<name>: Validation failed - <runtime error message>
```

## 9. Failure modes

* No workflows → `BadParameter`.
* MI lacks site contributor → 401/403 from hostruntime → `RuntimeError`.
* hostruntime not running (cold-start) → 503/504 → re-issue after 30 s.

## 10. Parity test

Args: `ValidateWorkflows`.

Capture stdout from both tools. The order of lines depends on filesystem
iteration order — sort lines before comparing.

## 11. Registration

```python
from .commands.validate_workflows import register as _reg_vw
_reg_vw(workflow_app)
```
