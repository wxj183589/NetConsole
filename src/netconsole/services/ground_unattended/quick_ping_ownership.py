"""Process identity used by durable Quick Ping reservations (no PID reuse guesses)."""
from __future__ import annotations

import os
from pathlib import Path


def process_identity(pid: int) -> str:
    if pid <= 0:
        return ""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return "unknown" if ctypes.get_last_error() == 5 else ""
        try:
            code = wintypes.DWORD()
            stamps = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return "unknown"
            if code.value != 259:
                return ""
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(stamp) for stamp in stamps)):
                return "unknown"
            return str((stamps[0].dwHighDateTime << 32) | stamps[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return ""


def matching_process(pid: int, identity: str) -> bool:
    current = process_identity(pid)
    return current == "unknown" or (bool(identity) and current == identity)


def orphan_fping_children(parent_pid: int) -> bool:
    """Cover a crash between Popen and storing its child identity on Windows."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("exe", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        return True  # Cannot prove exit; retain the reservation.
    try:
        item = ProcessEntry()
        item.size = ctypes.sizeof(item)
        valid = kernel.Process32FirstW(handle, ctypes.byref(item))
        while valid:
            if item.parent == parent_pid and item.exe.lower() in {"fping", "fping.exe"}:
                return True
            valid = kernel.Process32NextW(handle, ctypes.byref(item))
        return False
    finally:
        kernel.CloseHandle(handle)
