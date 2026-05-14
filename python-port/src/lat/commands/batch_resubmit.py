"""`BatchResubmit` — bulk re-run of historical workflow runs by status + date.

Mirrors `Operations/BatchResubmit.cs`. Lists runs via the hostruntime API,
filters out already-processed runs from a per-invocation log file (so a
restart of the tool doesn't re-resubmit the same runs), then loops
through the remaining ones, sleeping 60s on HTTP 429 throttling.

The .NET tool uses the trigger/histories shape for resubmit:
    `.../workflows/{wf}/triggers/{trigger}/histories/{run_id}/resubmit`
We match that via `arm.resubmit_trigger_history()`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import typer

from .. import arm

# .NET sleeps 60s after a 429; keep parity unless tests override.
_THROTTLE_SLEEP_SECONDS = 60


@dataclass
class _RunInfo:
    run_id: str
    trigger: str


def _safe_timestamp_suffix(ts: str) -> str:
    """Mirror `DateTime.Parse(startTime).ToString("yyyyMMddHHmmss")` for log naming."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt).strftime("%Y%m%d%H%M%S")
        except ValueError:
            continue
    # Fall back to sanitised input
    return "".join(ch for ch in ts if ch.isalnum())


def _load_processed(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()
    return {
        line.strip()
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _is_throttle_error(err: BaseException) -> bool:
    msg = str(err)
    return "429" in msg or "Too Many Requests" in msg


def _collect_candidate_runs(
    workflow: str, status: str, start_time: str, end_time: str
) -> list[_RunInfo]:
    out: list[_RunInfo] = []
    for run in arm.list_runs(
        workflow, status=status, start_time=start_time, end_time=end_time
    ):
        name = run.get("name")
        trigger = (run.get("properties") or {}).get("trigger", {}).get("name")
        if name and trigger:
            out.append(_RunInfo(run_id=name, trigger=trigger))
    return out


def batch_resubmit(
    workflow: str = typer.Option(
        ..., "-wf", "--workflow", help="Workflow name."
    ),
    start_time: str = typer.Option(
        ..., "-st", "--start-time",
        help="UTC start (e.g. 2026-05-14T00:00:00Z). Inclusive of microseconds via ARM filter.",
    ),
    end_time: str = typer.Option(
        ..., "-et", "--end-time", help="UTC end (e.g. 2026-05-15T00:00:00Z).",
    ),
    status: str = typer.Option(
        "Failed", "-s", "--status",
        help="Run status filter — Failed (default), Succeeded, Cancelled, etc.",
    ),
    ignore_processed: bool = typer.Option(
        True, "-ignore", "--ignore-processed/--no-ignore-processed",
        help="Skip runs whose IDs already appear in the log file (default: True).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip both confirmation prompts.",
    ),
    log_path: Path | None = typer.Option(
        None, "--log-path",
        help="Override the default log file (BatchResubmit_<wf>_<status>_<st>_<et>.log).",
    ),
    sleep_seconds: int = typer.Option(
        _THROTTLE_SLEEP_SECONDS, "--throttle-sleep", hidden=True,
        help="(test seam) Seconds to sleep on HTTP 429.",
    ),
) -> None:
    """Bulk-resubmit runs matching a status / time range, throttle-aware."""
    if not yes:
        typer.confirm(
            "Before execute the command, please make sure that the Logic App "
            "managed identity has Reader + Logic App Standard Contributor on "
            "the resource group. Continue?",
            abort=True,
        )

    default_log = Path.cwd() / (
        f"BatchResubmit_{workflow}_{status}_"
        f"{_safe_timestamp_suffix(start_time)}_{_safe_timestamp_suffix(end_time)}.log"
    )
    log_file = log_path or default_log

    processed: set[str] = set()
    if ignore_processed:
        typer.echo(
            f"Detected setting to ignore resubmitted {status} runs, "
            f"loading {log_file} for resubmitted records"
        )
        processed = _load_processed(log_file)
        typer.echo(
            f"{len(processed)} records founds, will ignore those runs."
            if processed
            else "Resubmitted records file not found, will resubmit all matching runs."
        )

    candidates = [
        info
        for info in _collect_candidate_runs(workflow, status, start_time, end_time)
        if info.run_id not in processed
    ]
    if not candidates:
        typer.echo("No failed run detected.")
        raise typer.Exit(code=0)

    typer.echo(f"Detected {len(candidates)} {status} runs.")
    if not yes:
        typer.confirm(
            "Are you sure to resubmit all detected failed runs?", abort=True
        )

    remaining = list(candidates)
    while remaining:
        typer.echo(
            f"Start to resubmit {status} runs, remain {len(remaining)} runs."
        )
        progressed_in_pass = False
        # Iterate in reverse so we can pop on success without skipping items.
        for idx in range(len(remaining) - 1, -1, -1):
            info = remaining[idx]
            try:
                arm.resubmit_trigger_history(workflow, info.trigger, info.run_id)
            except Exception as err:  # noqa: BLE001 - matches .NET catch-all
                if _is_throttle_error(err):
                    typer.echo(
                        f"Hit throttling limitation of Azure management API, "
                        f"pause for {sleep_seconds} seconds and then continue. "
                        f"Still have {len(remaining)} runs need to be resubmitted"
                    )
                    time.sleep(sleep_seconds)
                    break  # restart outer loop
                raise
            else:
                with log_file.open("a", encoding="utf-8") as fh:
                    fh.write(f"{info.run_id}\n")
                remaining.pop(idx)
                progressed_in_pass = True
        if not progressed_in_pass and remaining:
            # Avoid tight infinite loops if every attempt 429s without a break
            # (shouldn't happen because we always break on the first 429).
            break

    typer.echo(f"All {status} run resubmitted successfully")


def register(runs_app: typer.Typer) -> None:
    runs_app.command(
        "batch-resubmit",
        help="Bulk resubmit runs by status + date range (throttle-aware).",
    )(batch_resubmit)
