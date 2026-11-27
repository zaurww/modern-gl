"""The AI programs of this computer the assistant server (D83) is connected to: Claude
Desktop and Claude Code keep their MCP servers in a JSON file of their own, and the
program writes its entry there — what a person did by hand before (docs/ASSISTANT.md).
Only the entry «modern-gl» is touched; a file that cannot be read is never rewritten."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

SERVER = "modern-gl"
READ, DRAFTS, EDITS = "read", "drafts", "edits"
MODES = (READ, DRAFTS, EDITS)
FLAGS = {DRAFTS: "--allow-drafts", EDITS: "--allow-edits"}
DESKTOP, CODE = "desktop", "code"
NAMES = {DESKTOP: "Claude Desktop", CODE: "Claude Code"}


class ClientError(LedgerError):
    """An AI program's settings could not be read or written; the message is for the user."""


@dataclass(frozen=True)
class Client:
    """One AI program: where its settings are and what the assistant is allowed there."""

    key: str
    config: Path | None  # None: the program is not on this computer
    mode: str | None = None  # None: the assistant is not connected

    @property
    def name(self) -> str:
        """The program's own name, the same in every language."""
        return NAMES[self.key]


def server_command(executable: Path | None = None) -> Path | None:
    """The assistant server beside the running program (the installed folder, or the
    environment's scripts); None when it is not there."""
    beside = (executable or Path(sys.executable)).parent
    name = "modern-gl-mcp.exe" if sys.platform == "win32" else "modern-gl-mcp"
    return beside / name if (beside / name).is_file() else None


def desktop_config(env: Mapping[str, str] | None = None, home: Path | None = None) -> Path | None:
    """Claude Desktop's settings file; None when the program is not installed. The Windows
    Store build keeps its «Roaming» inside its package folder."""
    env, home = os.environ if env is None else env, home or Path.home()
    folders: list[Path] = []
    if env.get("LOCALAPPDATA"):
        packages = Path(env["LOCALAPPDATA"]) / "Packages"
        folders += sorted(packages.glob("Claude_*/LocalCache/Roaming/Claude"))
    if env.get("APPDATA"):
        folders.append(Path(env["APPDATA"]) / "Claude")
    folders += [home / "Library" / "Application Support" / "Claude", home / ".config" / "Claude"]
    found = next((folder for folder in folders if folder.is_dir()), None)
    return found / "claude_desktop_config.json" if found else None


def code_config(home: Path | None = None) -> Path | None:
    """Claude Code's settings file (the servers of every project); None when not installed."""
    path = (home or Path.home()) / ".claude.json"
    return path if path.is_file() else None


def clients(env: Mapping[str, str] | None = None, home: Path | None = None) -> list[Client]:
    """The AI programs the window offers, with what is connected now."""
    found = {DESKTOP: desktop_config(env, home), CODE: code_config(home)}
    return [
        Client(key, config, mode_of(config) if config else None) for key, config in found.items()
    ]


def mode_of(config: Path) -> str | None:
    """What the assistant is allowed in this program; None when it is not connected or the
    file cannot be read."""
    try:
        entry = _servers(_read(config)).get(SERVER)
    except ClientError:
        return None
    if not isinstance(entry, dict):
        return None
    args = _args(cast("dict[str, object]", entry))
    return EDITS if FLAGS[EDITS] in args else DRAFTS if FLAGS[DRAFTS] in args else READ


def connect(client: Client, command: Path, mode: str) -> None:
    """Write the assistant's entry: the server and what it is allowed. The other arguments
    of an entry made by hand (`--data`, `--lang`) stay."""
    config = _installed(client)
    settings = _read(config)
    servers = _servers(settings)
    old = servers.get(SERVER)
    entry = cast("dict[str, object]", old) if isinstance(old, dict) else _new_entry(client.key)
    kept = [arg for arg in _args(entry) if arg not in FLAGS.values()]
    entry["command"] = str(command)
    entry["args"] = [*kept, *([FLAGS[mode]] if mode in FLAGS else [])]
    servers[SERVER] = entry
    settings["mcpServers"] = servers
    _write(config, settings)


def disconnect(client: Client) -> None:
    """Remove the assistant's entry; nothing else of the file changes."""
    config = _installed(client)
    settings = _read(config)
    servers = _servers(settings)
    if SERVER in servers:
        del servers[SERVER]
        _write(config, settings)


def _installed(client: Client) -> Path:
    if client.config is None:
        raise ClientError(tr("{name} не установлен на этом компьютере", name=client.name))
    return client.config


def _new_entry(key: str) -> dict[str, object]:
    return {"type": "stdio", "env": {}} if key == CODE else {}


def _args(entry: dict[str, object]) -> list[str]:
    args = entry.get("args")
    return (
        [a for a in cast("list[object]", args) if isinstance(a, str)]
        if isinstance(args, list)
        else []
    )


def _servers(settings: dict[str, object]) -> dict[str, object]:
    servers = settings.get("mcpServers")
    return cast("dict[str, object]", servers) if isinstance(servers, dict) else {}


def _read(config: Path) -> dict[str, object]:
    """The settings as they are; an absent or empty file is empty settings."""
    try:
        text = config.read_text(encoding="utf-8") if config.is_file() else ""
        settings: object = json.loads(text) if text.strip() else {}
    except (OSError, ValueError) as e:
        raise ClientError(
            tr("Файл настроек не читается, он не изменён: {file} ({error})", file=config, error=e)
        ) from e
    if not isinstance(settings, dict):
        raise ClientError(tr("Файл настроек не читается, он не изменён: {file}", file=config))
    return cast("dict[str, object]", settings)


def _write(config: Path, settings: dict[str, object]) -> None:
    """All or nothing: the new text goes to a file beside and takes the old one's place."""
    beside = config.with_name(config.name + ".modern-gl.tmp")
    try:
        beside.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        beside.replace(config)
    except OSError as e:
        beside.unlink(missing_ok=True)
        raise ClientError(
            tr("Настройки не записаны: {file} ({error})", file=config, error=e)
        ) from e
