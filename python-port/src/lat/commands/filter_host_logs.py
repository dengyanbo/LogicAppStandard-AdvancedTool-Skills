"""`FilterHostLogs` — extract [Error]/[Warning] runs from LA Standard host logs.

Mirrors `Operations/FilterHostLogs.cs`. The .NET tool hardcodes the log
directory to `C:/home/LogFiles/Application/Functions/Host/`; the Python
port keeps that as the default but accepts `--log-dir` for local runs.

Filtering semantics (kept identical to C# for parity):
  * Lines containing `[Error]` or `[Warning]` are always included.
  * Subsequent (continuation) lines are included until the next
    `[Information]` line, which resets the "include continuation" flag.
  * Other lines that contain neither marker are included only while the
    continuation flag is set.

Output: a single `FilteredLogs_<yyyyMMddHHmmss>.log` file in the current
working directory, one section per source file, separated by a 58-char
`=` rule.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer

_DEFAULT_LOG_DIR = Path(r"C:\home\LogFiles\Application\Functions\Host")
_SEPARATOR = "==========================================================\r\n\r\n"


def _filter_one_file(path: Path) -> tuple[str, int]:
    """Return (filtered_content, hit_count) for a single log file."""
    out: list[str] = []
    hits = 0
    read_next = False
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "[Error]" in line or "[Warning]" in line:
            hits += 1
            out.append(line)
            read_next = True
        elif "[Information]" in line:
            read_next = False
        elif read_next:
            out.append(line)
    return "\r\n".join(out) + ("\r\n" if out else ""), hits


def filter_host_logs(
    log_dir: Path = typer.Option(
        _DEFAULT_LOG_DIR,
        "--log-dir",
        help=f"Directory containing host *.log files. Defaults to {_DEFAULT_LOG_DIR}",
    ),
    out_path: Path | None = typer.Option(
        None,
        "--out",
        help="Output file (defaults to FilteredLogs_<timestamp>.log in cwd).",
    ),
) -> None:
    """Filter error/warning lines from the host log directory."""
    if not log_dir.exists() or not log_dir.is_dir():
        typer.echo(f"Log directory does not exist: {log_dir}")
        raise typer.Exit(code=1)

    files = sorted(log_dir.glob("*.log"))
    if not files:
        typer.echo("No log files detected.")
        return

    target = out_path or Path.cwd() / f"FilteredLogs_{datetime.now():%Y%m%d%H%M%S}.log"

    total_hits = 0
    with target.open("a", encoding="utf-8", newline="") as fh:
        for path in files:
            typer.echo(f"Scanning {path}")
            content, hits = _filter_one_file(path)
            total_hits += hits
            if content:
                fh.write(f"Error and Warning logs in {path}\r\n")
                fh.write(content)
                fh.write(_SEPARATOR)

    if total_hits == 0:
        typer.echo("There's no warning or error messages found in current logs.")
        # Mirror .NET behavior: don't keep an empty output file
        if target.exists() and target.stat().st_size == 0:
            target.unlink()
        return

    typer.echo(f"All logs filters, please open {target} for detail information.")


def register(site_app: typer.Typer) -> None:
    site_app.command("filter-host-logs", help="Filter error/warning lines from host logs.")(
        filter_host_logs
    )
