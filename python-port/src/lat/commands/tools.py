"""Implementation of the `Tools` sub-commands (utility / debug helpers).

Each function mirrors a `Tools <Name>` invocation in the .NET tool. The
group is gathered into a single module because every command here is small
and stateless.

| Python                          | .NET equivalent                  | Ref                           |
|---------------------------------|----------------------------------|-------------------------------|
| `tools generate-prefix`         | `Tools GeneratePrefix`           | Tools/GeneratePrefix.cs       |
| `tools runid-to-datetime`       | `Tools RunIDToDateTime`          | Tools/RunIDToDatetime.cs      |
| `tools decode-zstd`             | `Tools DecodeZSTD`               | Program.cs:957-972 inline call|
| `tools get-mi-token`            | `Tools GetMIToken`               | Program.cs:882-898            |
| `tools restart`                 | `Tools Restart`                  | Tools/Restart.cs              |
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import typer

from ..arm import restart_site
from ..auth import DEFAULT_AUDIENCE, retrieve_token
from ..storage.compression import decompress
from ..storage.prefix import generate

# .NET DateTime constants
_LONG_MAX = (1 << 63) - 1          # System.Int64.MaxValue
_TICKS_PER_SECOND = 10_000_000     # 100-nanosecond intervals
_EPOCH_TICKS_AT_UNIX = 621_355_968_000_000_000  # .NET ticks of 1970-01-01T00:00:00Z


# ---------------------------------------------------------------------------
# Tools GeneratePrefix
# ---------------------------------------------------------------------------


def generate_prefix(
    la: str = typer.Option(..., "-la", "--logic-app", help="Logic App name (case sensitive)."),
    wf: str | None = typer.Option(None, "-wf", "--workflow-id", help="Workflow ID (optional)."),
) -> None:
    """Generate Logic App and workflow prefix.

    Mirrors `Tools GeneratePrefix` in the .NET tool. Inputs are NOT lowercased
    — see `Tools/GeneratePrefix.cs:13,23`. Use `lat tools generate-prefix` for
    debug parity with the .NET tool; the in-process production helpers in
    `lat.storage.prefix` lowercase per `Common.cs` semantics.
    """
    la_prefix = generate(la)
    if not wf:
        typer.echo(f"Logic App Prefix: {la_prefix}")
        return
    wf_prefix = generate(wf)
    typer.echo(f"Logic App Prefix: {la_prefix}")
    typer.echo(f"Workflow Prefix: {wf_prefix}")
    typer.echo(f"Combined prefix: {la_prefix}{wf_prefix}")


# ---------------------------------------------------------------------------
# Tools RunIDToDateTime
# ---------------------------------------------------------------------------


def _decode_run_id(run_id: str) -> datetime:
    """Decode the trigger UTC time embedded in a workflow run ID.

    Mirrors `Tools/RunIDToDatetime.cs`. The first 20 digits of the run ID
    are `long.MaxValue - .NET DateTime.Ticks` (a reversed-ticks scheme so
    newer runs sort first lexicographically in storage).
    """
    if len(run_id) < 20:
        raise typer.BadParameter("Run ID must have at least 20 leading digits.")
    head = run_id[:20]
    try:
        reversed_ticks = int(head)
    except ValueError as e:
        raise typer.BadParameter(
            f"First 20 chars of run ID must be digits, got {head!r}."
        ) from e
    ticks = _LONG_MAX - reversed_ticks
    unix_seconds = (ticks - _EPOCH_TICKS_AT_UNIX) / _TICKS_PER_SECOND
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)


def runid_to_datetime(
    run_id: str = typer.Option(
        ..., "-id", "--run-id",
        help="Run ID of Logic App workflow (eg: 08584737551867954143243946780CU57).",
    ),
) -> None:
    """Get workflow start time from a run ID."""
    dt = _decode_run_id(run_id)
    # Match the .NET tool's format exactly: 2024-10-02T06:48:18Z
    typer.echo(f"Datetime of RunID {run_id} is {dt.strftime('%Y-%m-%dT%H:%M:%SZ')}")


# ---------------------------------------------------------------------------
# Tools DecodeZSTD
# ---------------------------------------------------------------------------


def decode_zstd(
    content: str = typer.Option(
        ..., "-c", "--content",
        help="Base64-encoded compressed content (e.g. DefinitionCompressed).",
    ),
) -> None:
    """Decode a base64-encoded compressed value (ZSTD or legacy Deflate)."""
    try:
        raw = base64.b64decode(content)
    except (ValueError, base64.binascii.Error) as e:
        raise typer.BadParameter(f"Input is not valid base64: {e}") from e
    decoded = decompress(raw)
    if decoded is None:
        raise typer.BadParameter("Input decoded to None (empty bytes).")
    # Match .NET formatting: blank line, header, payload.
    typer.echo(f"\nDecoded content:\n{decoded}")


# ---------------------------------------------------------------------------
# Tools GetMIToken
# ---------------------------------------------------------------------------


def get_mi_token(
    audience: str = typer.Option(
        DEFAULT_AUDIENCE, "-a", "--audience",
        help="Audience for the token. Defaults to https://management.azure.com.",
    ),
) -> None:
    """Acquire a Managed Identity (or fallback) token and print it as JSON.

    Replaces the .NET tool's hand-rolled IMDS POST; backed by
    `azure.identity.ManagedIdentityCredential` (or DefaultAzureCredential
    chain for local development).
    """
    token = retrieve_token(audience)
    typer.echo(json.dumps(token.to_dict(), indent=2))


# ---------------------------------------------------------------------------
# Tools Restart
# ---------------------------------------------------------------------------


def restart(
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip the restart confirmation prompt.",
    ),
) -> None:
    """Restart the Logic App Standard site via ARM (`web_apps.restart`)."""
    if not yes:
        typer.confirm(
            "Restart the Logic App? In-flight workflow runs may be interrupted.",
            abort=True,
        )
    restart_site()
    typer.echo("Restart request accepted.")


# ---------------------------------------------------------------------------
# Registration with the `tools` Typer sub-app.
# ---------------------------------------------------------------------------


def register(tools_app: typer.Typer) -> None:
    """Register all available `Tools` sub-commands."""
    tools_app.command("generate-prefix", help="Generate Logic App / workflow prefix.")(
        generate_prefix
    )
    tools_app.command("runid-to-datetime", help="Decode workflow start time from a run ID.")(
        runid_to_datetime
    )
    tools_app.command("decode-zstd", help="Decode a base64 compressed value.")(
        decode_zstd
    )
    tools_app.command("get-mi-token", help="Acquire and print a Managed Identity token.")(
        get_mi_token
    )
    tools_app.command("restart", help="Restart the Logic App site via ARM.")(
        restart
    )
