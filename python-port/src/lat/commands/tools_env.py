"""`Tools ImportAppsettings` and `Tools CleanEnvironmentVariable`.

Both commands manipulate **machine-level** environment variables by writing
to `HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment`,
mirroring the .NET tool's `Environment.SetEnvironmentVariable(...,
EnvironmentVariableTarget.Machine)` calls. These edits require
Administrator privileges and only make sense on Windows; the Python port
matches that constraint and raises a clear error on other platforms.

Input file format: the same `{"KEY": "value"}` JSON object exported from
the Azure portal's "Configuration → Advanced edit" view (a flat
string→string dict).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Protocol

import typer

_HKLM_ENV_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
_WM_SETTINGCHANGE = 0x001A
_HWND_BROADCAST = 0xFFFF
_SMTO_ABORTIFHUNG = 0x0002


class EnvWriter(Protocol):
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class _WindowsMachineEnvWriter:
    """Writes to HKLM\\...\\Environment then broadcasts WM_SETTINGCHANGE."""

    def __init__(self) -> None:
        import ctypes
        import winreg

        self._winreg = winreg
        self._ctypes = ctypes
        self._handle = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            _HKLM_ENV_KEY,
            0,
            winreg.KEY_ALL_ACCESS,
        )

    def _broadcast(self) -> None:
        result = self._ctypes.c_long()
        self._ctypes.windll.user32.SendMessageTimeoutW(
            _HWND_BROADCAST,
            _WM_SETTINGCHANGE,
            0,
            "Environment",
            _SMTO_ABORTIFHUNG,
            5000,
            self._ctypes.byref(result),
        )

    def set(self, name: str, value: str) -> None:
        winreg = self._winreg
        # Mirror .NET: REG_EXPAND_SZ when value references other env vars (%FOO%),
        # else REG_SZ. .NET picks REG_SZ when value lacks '%' (see corefx/EnvironmentRegistryKey).
        reg_type = winreg.REG_EXPAND_SZ if "%" in value else winreg.REG_SZ
        winreg.SetValueEx(self._handle, name, 0, reg_type, value)
        self._broadcast()

    def delete(self, name: str) -> None:
        try:
            self._winreg.DeleteValue(self._handle, name)
        except FileNotFoundError:
            pass  # already absent — silently skip, matches .NET behavior
        self._broadcast()


def _make_default_writer() -> EnvWriter:
    if sys.platform != "win32":
        raise typer.BadParameter(
            "ImportAppsettings/CleanEnvironmentVariable only run on Windows "
            "(they manipulate HKLM environment variables). Use --writer-override "
            "for testing or run on a Logic App Standard Kudu shell."
        )
    return _WindowsMachineEnvWriter()


# Test seam: tests monkeypatch this to inject a recording writer.
def _get_writer() -> EnvWriter:
    return _make_default_writer()


def _load_settings(file_path: Path) -> dict[str, str]:
    if not file_path.exists():
        raise typer.BadParameter(f"File: {file_path} not exists!")
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"File is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise typer.BadParameter("Top-level JSON must be an object {key: value}.")
    # Coerce non-string values to strings as .NET dict<string,string> deserialization does
    return {str(k): str(v) for k, v in data.items()}


# ---------------------------------------------------------------------------
# Tools ImportAppsettings
# ---------------------------------------------------------------------------


def import_appsettings(
    file: Path = typer.Option(
        ..., "-f", "--file",
        help="Path to appsettings JSON exported from Azure portal Advanced edit.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip the overwrite confirmation prompt.",
    ),
) -> None:
    """Import app settings as machine environment variables (admin required)."""
    settings = _load_settings(file)
    typer.echo("This command need to be executed in Administrator mode")
    if not yes:
        typer.confirm(
            "All existing environment variables will be overwritten. Continue?",
            abort=True,
        )
    writer = _get_writer()
    for name, value in settings.items():
        writer.set(name, value)
    typer.echo("All app settings imported")


# ---------------------------------------------------------------------------
# Tools CleanEnvironmentVariable
# ---------------------------------------------------------------------------


def clean_environment_variable(
    file: Path = typer.Option(
        ..., "-f", "--file",
        help="Path to the same appsettings JSON used for import.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip the delete confirmation prompt.",
    ),
) -> None:
    """Remove the machine environment variables listed in the JSON file (admin)."""
    settings = _load_settings(file)
    typer.echo("This command need to run with Administrator mode")
    if not yes:
        typer.confirm(
            "All environment variables in appsettings file will be deleted. Continue?",
            abort=True,
        )
    writer = _get_writer()
    for name in settings:
        writer.delete(name)
    typer.echo("Environment variables have been removed.")


def register(tools_app: typer.Typer) -> None:
    tools_app.command(
        "import-appsettings",
        help="Import Logic App app-settings JSON as machine env vars (Windows admin).",
    )(import_appsettings)
    tools_app.command(
        "clean-environment-variable",
        help="Remove env vars listed in an appsettings JSON (Windows admin).",
    )(clean_environment_variable)
