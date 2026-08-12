"""Reliable Windows folder picker shared by the local assistant endpoints.

The picker runs in a short-lived child process.  Keeping the native dialog out
of the uvicorn worker avoids COM/threading problems and lets us distinguish a
real cancellation from a dialog startup failure.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading


class FolderPickerCancelled(Exception):
    pass


class FolderPickerBusy(Exception):
    pass


class FolderPickerError(RuntimeError):
    pass


_picker_lock = threading.Lock()


def folder_picker_ready() -> bool:
    if sys.platform != "win32":
        return False
    try:
        ctypes.WinDLL("shell32", use_last_error=True)
        ctypes.WinDLL("ole32", use_last_error=True)
        ctypes.WinDLL("user32", use_last_error=True)
        return True
    except Exception:
        return False


def windows_session_id() -> int:
    if sys.platform != "win32":
        return -1
    session_id = wintypes.DWORD()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
        return -1
    return int(session_id.value)


def _native_pick_folder(title: str) -> str | None:
    if sys.platform != "win32":
        raise RuntimeError("Windows native folder picker is unavailable")

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    class BrowseInfo(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", wintypes.LPWSTR),
            ("lpszTitle", wintypes.LPCWSTR),
            ("ulFlags", wintypes.UINT),
            ("lpfn", ctypes.c_void_p),
            ("lParam", wintypes.LPARAM),
            ("iImage", ctypes.c_int),
        ]

    shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BrowseInfo)]
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL

    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.UINT, wintypes.LPARAM, wintypes.LPARAM)

    def show_picker(hwnd: int, message: int, _lparam: int, _data: int) -> int:
        if message == 1:  # BFFM_INITIALIZED
            # The helper is hidden in the tray/startup flow. Explicitly raise
            # its dialog so users do not mistake a window behind the browser
            # for an unresponsive button.
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            user32.SetForegroundWindow(hwnd)
        return 0

    callback = callback_type(show_picker)

    # COINIT_APARTMENTTHREADED. A fresh child process guarantees a clean STA.
    result = ole32.CoInitializeEx(None, 0x2)
    initialized = result in (0, 1)
    if result not in (0, 1, -2147417850):  # S_OK, S_FALSE, RPC_E_CHANGED_MODE
        raise OSError(f"Windows COM initialization failed (0x{result & 0xFFFFFFFF:08X})")

    pidl = None
    try:
        display_name = ctypes.create_unicode_buffer(32768)
        browse = BrowseInfo(
            hwndOwner=user32.GetForegroundWindow(),
            pidlRoot=None,
            pszDisplayName=ctypes.cast(display_name, wintypes.LPWSTR),
            lpszTitle=title,
            # Filesystem folders only + new-style resizable dialog + edit box.
            ulFlags=0x0001 | 0x0040 | 0x0010,
            lpfn=ctypes.cast(callback, ctypes.c_void_p),
            lParam=0,
            iImage=0,
        )
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(browse))
        if not pidl:
            return None
        selected = ctypes.create_unicode_buffer(32768)
        if not shell32.SHGetPathFromIDListW(pidl, selected):
            raise OSError("Windows returned a folder that could not be resolved")
        return selected.value
    finally:
        if pidl:
            ole32.CoTaskMemFree(pidl)
        if initialized:
            ole32.CoUninitialize()


def _child_main(title: str) -> int:
    try:
        selected = _native_pick_folder(title)
        payload = {"status": "selected", "path": selected} if selected else {"status": "cancelled"}
        print(json.dumps(payload, ensure_ascii=True), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=True), flush=True)
        return 2


def _parse_child_output(completed: subprocess.CompletedProcess[str]) -> Path:
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        diagnostic = completed.stderr.strip() or f"native picker exited with code {completed.returncode}"
        raise FolderPickerError(f"无法打开 Windows 文件夹选择窗口：{diagnostic}")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise FolderPickerError(f"文件夹选择器返回了无效结果：{lines[-1][:160]}") from exc
    status = payload.get("status")
    if status == "cancelled":
        raise FolderPickerCancelled()
    if status == "error":
        raise FolderPickerError(f"无法打开 Windows 文件夹选择窗口：{payload.get('message') or '未知错误'}")
    value = str(payload.get("path") or "").strip()
    if status != "selected" or not value:
        raise FolderPickerError("文件夹选择器没有返回有效路径")
    path = Path(value).resolve()
    if not path.is_dir():
        raise FolderPickerError("选择的文件夹不存在或当前用户无权访问")
    return path


def pick_windows_folder(title: str, timeout: int = 300) -> Path:
    if sys.platform != "win32":
        raise FolderPickerError("当前环境不支持 Windows 文件夹选择器")
    if not _picker_lock.acquire(blocking=False):
        raise FolderPickerBusy("文件夹选择窗口已经打开，请先完成或取消当前选择")
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "backend.app.services.windows_folder_picker", "--child", "--title", title],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=flags,
            )
        except subprocess.TimeoutExpired as exc:
            raise FolderPickerError("文件夹选择窗口等待超时，请重新点击选择") from exc
        return _parse_child_output(completed)
    finally:
        _picker_lock.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--title", default="选择文件夹")
    args = parser.parse_args()
    if args.probe:
        print(json.dumps({"ready": folder_picker_ready()}))
        raise SystemExit(0 if folder_picker_ready() else 1)
    if not args.child:
        parser.error("--child or --probe is required")
    raise SystemExit(_child_main(args.title))
