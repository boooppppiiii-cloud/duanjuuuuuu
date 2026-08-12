import json
import subprocess
from pathlib import Path

import pytest

from app.services.windows_folder_picker import (
    FolderPickerCancelled,
    FolderPickerError,
    _parse_child_output,
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
