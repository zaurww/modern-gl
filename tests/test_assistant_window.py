"""«AI-помощник»: the program connects the books to Claude Desktop and Claude Code itself —
it writes only its own entry in their settings, keeps the rest, and never rewrites a file
it could not read. The window shows what is connected and applies what is chosen."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modern_gl.desktop import theme
from modern_gl.desktop.assistant_dialog import AssistantDialog
from modern_gl.infrastructure import assistant_clients as ai
from modern_gl.infrastructure.assistant_clients import Client, ClientError
from tests.helpers.qt import running_app

COMMAND = Path("C:/Program Files/Modern GL/modern-gl-mcp.exe")


def desktop(tmp_path: Path, settings: object | None = None) -> Client:
    config = tmp_path / "claude_desktop_config.json"
    if settings is not None:
        config.write_text(json.dumps(settings), encoding="utf-8")
    return Client(ai.DESKTOP, config, ai.mode_of(config))


def entry(client: Client) -> dict:
    assert client.config is not None
    return json.loads(client.config.read_text(encoding="utf-8"))["mcpServers"][ai.SERVER]


# ---- the settings files ------------------------------------------------------------------


def test_connecting_keeps_everything_else_of_the_file(tmp_path):
    other = {"command": "npx", "args": ["-y", "something"]}
    client = desktop(tmp_path, {"preferences": {"theme": "dark"}, "mcpServers": {"other": other}})
    ai.connect(client, COMMAND, ai.READ)
    assert client.config is not None
    written = json.loads(client.config.read_text(encoding="utf-8"))
    assert written["preferences"] == {"theme": "dark"}
    assert written["mcpServers"]["other"] == other
    assert written["mcpServers"][ai.SERVER] == {"command": str(COMMAND), "args": []}


@pytest.mark.parametrize(
    ("mode", "args"),
    [(ai.READ, []), (ai.DRAFTS, ["--allow-drafts"]), (ai.EDITS, ["--allow-edits"])],
)
def test_the_mode_is_the_servers_flag(tmp_path, mode, args):
    client = desktop(tmp_path)  # no file yet: the program is installed, never configured
    ai.connect(client, COMMAND, mode)
    assert entry(client)["args"] == args
    assert client.config is not None
    assert ai.mode_of(client.config) == mode


def test_changing_the_mode_keeps_the_arguments_made_by_hand(tmp_path):
    by_hand = {"command": "old.exe", "args": ["--data", "D:/Books", "--allow-edits"]}
    client = desktop(tmp_path, {"mcpServers": {ai.SERVER: by_hand}})
    assert client.mode == ai.EDITS
    ai.connect(client, COMMAND, ai.DRAFTS)
    assert entry(client) == {
        "command": str(COMMAND),
        "args": ["--data", "D:/Books", "--allow-drafts"],
    }


def test_claude_code_gets_an_entry_in_its_own_shape(tmp_path):
    config = tmp_path / ".claude.json"
    config.write_text(json.dumps({"numStartups": 7}), encoding="utf-8")
    client = Client(ai.CODE, config)
    ai.connect(client, COMMAND, ai.EDITS)
    assert entry(client) == {
        "type": "stdio",
        "env": {},
        "command": str(COMMAND),
        "args": ["--allow-edits"],
    }
    assert json.loads(config.read_text(encoding="utf-8"))["numStartups"] == 7


def test_disconnecting_removes_only_the_assistant(tmp_path):
    other = {"command": "npx"}
    client = desktop(tmp_path, {"mcpServers": {"other": other, ai.SERVER: {"command": "x"}}})
    ai.disconnect(client)
    assert client.config is not None
    assert json.loads(client.config.read_text(encoding="utf-8")) == {"mcpServers": {"other": other}}
    assert ai.mode_of(client.config) is None


def test_a_file_that_cannot_be_read_is_left_as_it_is(tmp_path):
    config = tmp_path / "claude_desktop_config.json"
    config.write_text('{"mcpServers": {', encoding="utf-8")  # cut short by a crash
    client = Client(ai.DESKTOP, config)
    with pytest.raises(ClientError, match="не изменён"):
        ai.connect(client, COMMAND, ai.READ)
    assert config.read_text(encoding="utf-8") == '{"mcpServers": {'
    assert ai.mode_of(config) is None
    assert list(tmp_path.iterdir()) == [config]  # nothing left beside


def test_a_program_that_is_not_installed_cannot_be_connected():
    with pytest.raises(ClientError, match="Claude Code не установлен"):
        ai.connect(Client(ai.CODE, None), COMMAND, ai.READ)


def test_the_programs_are_found_where_they_keep_their_settings(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path / "Local"), "APPDATA": str(tmp_path / "Roaming")}
    home = tmp_path / "home"
    home.mkdir()
    assert [c.config for c in ai.clients(env, home)] == [None, None]

    classic = tmp_path / "Roaming" / "Claude"
    classic.mkdir(parents=True)
    assert ai.desktop_config(env, home) == classic / "claude_desktop_config.json"

    # the Windows Store build reads its own folder, not %APPDATA%
    store = tmp_path / "Local" / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
    store.mkdir(parents=True)
    assert ai.desktop_config(env, home) == store / "claude_desktop_config.json"

    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {ai.SERVER: {"command": "x", "args": ["--allow-drafts"]}}}),
        encoding="utf-8",
    )
    found = {c.key: c for c in ai.clients(env, home)}
    assert found[ai.DESKTOP].mode is None
    assert found[ai.CODE].mode == ai.DRAFTS


def test_the_server_is_looked_for_beside_the_program(tmp_path, monkeypatch):
    monkeypatch.setattr(ai.sys, "platform", "win32")
    assert ai.server_command(tmp_path / "modern-gl.exe") is None
    (tmp_path / "modern-gl-mcp.exe").write_bytes(b"")
    assert ai.server_command(tmp_path / "modern-gl.exe") == tmp_path / "modern-gl-mcp.exe"


# ---- the window --------------------------------------------------------------------------


@pytest.fixture
def programs(tmp_path):
    """Claude Desktop installed and never configured; Claude Code not installed."""
    config = tmp_path / "claude_desktop_config.json"

    def load() -> list[Client]:
        return [Client(ai.DESKTOP, config, ai.mode_of(config)), Client(ai.CODE, None)]

    return load, config


def window(qtbot, load, command: Path | None = COMMAND) -> AssistantDialog:
    theme.apply(running_app())
    dialog = AssistantDialog(load, command)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def test_one_click_connects_the_installed_program_for_reading(qtbot, programs):
    load, config = programs
    dialog = window(qtbot, load)
    assert dialog.status.text() == "AI не подключён"
    assert dialog.boxes[ai.DESKTOP].isChecked()
    assert not dialog.boxes[ai.CODE].isEnabled()
    assert dialog.states[ai.CODE].text() == "не установлен на этом компьютере"
    assert dialog.mode() == ai.READ
    assert dialog.apply_button.isEnabled()

    dialog.apply_button.click()

    assert ai.mode_of(config) == ai.READ
    assert dialog.status.text() == "AI подключён: Claude Desktop"
    assert dialog.states[ai.DESKTOP].text() == "подключён · только чтение"
    assert "после перезапуска: Claude Desktop" in dialog.message.text()
    assert not dialog.apply_button.isEnabled()  # nothing left to apply


def test_the_mode_is_changed_and_the_program_disconnected(qtbot, programs):
    load, config = programs
    ai.connect(load()[0], COMMAND, ai.DRAFTS)
    dialog = window(qtbot, load)
    assert dialog.mode() == ai.DRAFTS
    assert not dialog.apply_button.isEnabled()

    dialog.mode_buttons[ai.EDITS].click()
    assert "копия файла" in dialog.mode_note.text()
    dialog.apply_button.click()
    assert ai.mode_of(config) == ai.EDITS

    dialog.boxes[ai.DESKTOP].setChecked(False)
    dialog.apply_button.click()
    assert ai.mode_of(config) is None
    assert dialog.status.text() == "AI не подключён"


def test_without_the_server_nothing_is_applied(qtbot, programs):
    load, config = programs
    dialog = window(qtbot, load, command=None)
    assert not dialog.apply_button.isEnabled()
    assert "не найден" in dialog.message.text()
    assert not config.exists()


def test_a_broken_settings_file_is_told_and_not_touched(qtbot, programs):
    load, config = programs
    config.write_text("not json", encoding="utf-8")
    dialog = window(qtbot, load)
    dialog.apply_button.click()
    assert "не изменён" in dialog.message.text()
    assert config.read_text(encoding="utf-8") == "not json"
