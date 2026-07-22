from __future__ import annotations

import ctypes
import os


CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect_windows_data(data: bytes, entropy: bytes) -> bytes:
    return _crypt_protect(data, entropy, decrypt=False)


def unprotect_windows_data(data: bytes, entropy: bytes) -> bytes:
    return _crypt_protect(data, entropy, decrypt=True)


def _crypt_protect(data: bytes, entropy: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("受控凭据持久化要求 Windows DPAPI")
    data_buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    entropy_buffer = (ctypes.c_ubyte * len(entropy)).from_buffer_copy(entropy)
    input_blob = _DataBlob(len(data), ctypes.cast(data_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    entropy_blob = _DataBlob(len(entropy), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output_blob = _DataBlob()
    windll = getattr(ctypes, "windll")
    function = windll.crypt32.CryptUnprotectData if decrypt else windll.crypt32.CryptProtectData
    if not function(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.data, output_blob.size)
    finally:
        windll.kernel32.LocalFree(output_blob.data)


__all__ = ["protect_windows_data", "unprotect_windows_data"]
