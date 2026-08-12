import json
import subprocess
from pathlib import Path

import pytest

from app.services.windows_folder_picker import (
    FolderPickerEnvironment,
    FolderPickerCancelled,
    FolderPickerError,
    _parse_child_output,
    folder_picker_environment,
)


def completed(stdout: str, stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["picker"], returncode, stdout, stderr)


def test_picker_parses_selected_unicode_folder(tmp_path: Path):
    selected = tmp_path / "短剧 源文件"
    selected.mkdir()

    result = _parse_child_output(completed(json.dumps({"status": "selected", "path": str(selected)})))

    assert result == selected.resolve()


def test_picker_distinguishes_cancel_from_failure():
    with pytest.raises(FolderPickerCancelled):
        _parse_child_output(completed('{"status":"cancelled"}'))

    with pytest.raises(FolderPickerError, match="COM failed"):
        _parse_child_output(completed('{"status":"error","message":"COM failed"}', returncode=2))


def test_picker_reports_missing_child_output():
    with pytest.raises(FolderPickerError, match="blocked by policy"):
        _parse_child_output(completed("", "blocked by policy", returncode=1))


def test_picker_environment_accepts_active_shell_session(monkeypatch):
    monkeypatch.setattr("app.services.windows_folder_picker.sys.platform", "win32")
    monkeypatch.setattr("app.services.windows_folder_picker.windows_session_id", lambda: 7)
    monkeypatch.setattr("app.services.windows_folder_picker.active_console_session_id", lambda: 2)
    monkeypatch.setattr("app.services.windows_folder_picker._windows_libraries_available", lambda: True)
    monkeypatch.setattr("app.services.windows_folder_picker._query_wts_session", lambda _session: (0, "operator"))
    monkeypatch.setattr("app.services.windows_folder_picker._shell_session_id", lambda: 7)
    monkeypatch.setattr("app.services.windows_folder_picker.os.getenv", lambda _key, _default="": "operator")

    environment = folder_picker_environment()

    assert environment == FolderPickerEnvironment(True, "ready", 7, 0, "operator", 7, 2)


@pytest.mark.parametrize(
    ("session_id", "state", "user", "shell_session", "reason"),
    [
        (0, 0, "operator", 0, "non_interactive_session"),
        (7, 4, "operator", 7, "session_not_active"),
        (7, 0, "", 7, "session_has_no_user"),
        (7, 0, "operator", 8, "shell_session_mismatch"),
    ],
)
def test_picker_environment_rejects_noninteractive_desktops(monkeypatch, session_id, state, user, shell_session, reason):
    monkeypatch.setattr("app.services.windows_folder_picker.sys.platform", "win32")
    monkeypatch.setattr("app.services.windows_folder_picker.windows_session_id", lambda: session_id)
    monkeypatch.setattr("app.services.windows_folder_picker.active_console_session_id", lambda: 2)
    monkeypatch.setattr("app.services.windows_folder_picker._windows_libraries_available", lambda: True)
    monkeypatch.setattr("app.services.windows_folder_picker._query_wts_session", lambda _session: (state, user))
    monkeypatch.setattr("app.services.windows_folder_picker._shell_session_id", lambda: shell_session)
    monkeypatch.setattr("app.services.windows_folder_picker.os.getenv", lambda _key, _default="": "operator")

    environment = folder_picker_environment()

    assert not environment.ready
    assert environment.reason == reason


def test_picker_environment_rejects_different_windows_user(monkeypatch):
    monkeypatch.setattr("app.services.windows_folder_picker.sys.platform", "win32")
    monkeypatch.setattr("app.services.windows_folder_picker.windows_session_id", lambda: 7)
    monkeypatch.setattr("app.services.windows_folder_picker.active_console_session_id", lambda: 7)
    monkeypatch.setattr("app.services.windows_folder_picker._windows_libraries_available", lambda: True)
    monkeypatch.setattr("app.services.windows_folder_picker._query_wts_session", lambda _session: (0, "operator"))
    monkeypatch.setattr("app.services.windows_folder_picker._shell_session_id", lambda: 7)
    monkeypatch.setattr("app.services.windows_folder_picker.os.getenv", lambda _key, _default="": "administrator")

    environment = folder_picker_environment()

    assert not environment.ready
    assert environment.reason == "desktop_user_mismatch"
