"""Small read-only Win32 process adapter; target authorization belongs to the caller.

This adapter never starts a target, grants privileges, writes memory, injects code,
suspends threads, or sends input. Only 64-bit Windows observers are supported.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path


PROCESS_ACCESS = 0x0410  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
MAX_READ_SIZE = 2 * 1024 * 1024
MAX_MODULES = 4096
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
READABLE_PAGE_TYPES = frozenset((0x02, 0x04, 0x08, 0x20, 0x40, 0x80))
UINT32 = ctypes.c_uint32
HANDLE = ctypes.c_void_p
SIZE_T = ctypes.c_size_t
BOOL = ctypes.c_int


class ProcessMemoryError(RuntimeError):
    """The requested read cannot be established as complete and readable."""


class _FileTime(ctypes.Structure):
    _fields_ = [("low", UINT32), ("high", UINT32)]

    def value(self) -> int:
        return (int(self.high) << 32) | int(self.low)


class _MemoryBasicInformation(ctypes.Structure):
    # Native 64-bit MEMORY_BASIC_INFORMATION. Natural padding places RegionSize
    # at offset 24 and produces sizeof 48, including trailing native padding.
    _fields_ = [
        ("BaseAddress", HANDLE), ("AllocationBase", HANDLE),
        ("AllocationProtect", UINT32), ("PartitionId", ctypes.c_uint16),
        ("RegionSize", SIZE_T), ("State", UINT32), ("Protect", UINT32),
        ("Type", UINT32),
    ]


class _ModuleInformation(ctypes.Structure):
    _fields_ = [("lpBaseOfDll", HANDLE), ("SizeOfImage", UINT32), ("EntryPoint", HANDLE)]


def _same_path(first: str | Path, second: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(first))) == os.path.normcase(
        os.path.abspath(os.fspath(second))
    )


def _error(operation: str) -> ProcessMemoryError:
    return ProcessMemoryError(f"{operation} failed (Win32 error {ctypes.get_last_error()})")


class _Win32Api:
    def __init__(self) -> None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        bindings = {
            "OpenProcess": (kernel, [UINT32, BOOL, UINT32], HANDLE),
            "CloseHandle": (kernel, [HANDLE], BOOL),
            "GetProcessTimes": (kernel, [HANDLE] + [ctypes.POINTER(_FileTime)] * 4, BOOL),
            "QueryFullProcessImageNameW": (kernel, [HANDLE, UINT32, ctypes.c_wchar_p,
                                                  ctypes.POINTER(UINT32)], BOOL),
            "VirtualQueryEx": (kernel, [HANDLE, HANDLE, ctypes.POINTER(_MemoryBasicInformation),
                                        SIZE_T], SIZE_T),
            "ReadProcessMemory": (kernel, [HANDLE, HANDLE, HANDLE, SIZE_T,
                                          ctypes.POINTER(SIZE_T)], BOOL),
            "EnumProcessModulesEx": (psapi, [HANDLE, ctypes.POINTER(HANDLE), UINT32,
                                            ctypes.POINTER(UINT32), UINT32], BOOL),
            "GetModuleFileNameExW": (psapi, [HANDLE, HANDLE, ctypes.c_wchar_p, UINT32], UINT32),
            "GetModuleInformation": (psapi, [HANDLE, HANDLE, ctypes.POINTER(_ModuleInformation),
                                           UINT32], BOOL),
        }
        for name, (library, arguments, result) in bindings.items():
            function = getattr(library, name)
            function.argtypes = arguments
            function.restype = result
            setattr(self, name, function)


class ReadOnlyProcess:
    """Open one PID with only query and read rights; close deterministically."""

    def __init__(self, pid: int) -> None:
        if os.name != "nt" or ctypes.sizeof(HANDLE) != 8:
            raise ProcessMemoryError("A 64-bit Windows Python observer is required")
        if type(pid) is not int or not 1 <= pid <= 0xFFFFFFFF:
            raise ValueError("pid must be a positive uint32 integer")
        self.pid = pid
        self._handle = None
        self._identity_path = None
        self._identity_creation = None
        self._api = _Win32Api()
        opened = self._api.OpenProcess(PROCESS_ACCESS, False, pid)
        if not opened:
            raise _error("OpenProcess read-only")
        self._handle = opened

    def _open_handle(self):
        if self._handle is None:
            raise ProcessMemoryError("Process handle is closed")
        return self._handle

    def __enter__(self) -> ReadOnlyProcess:
        self._open_handle()
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.close()

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None and not self._api.CloseHandle(handle):
            raise _error("CloseHandle")

    def identity(self) -> dict:
        handle = self._open_handle()
        creation, exit_time, kernel_time, user_time = (_FileTime() for _ in range(4))
        if not self._api.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time),
                                         ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise _error("GetProcessTimes")
        path = ctypes.create_unicode_buffer(32768)
        length = UINT32(len(path))
        if not self._api.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
            # Windows can refuse the image query after exit even while the held
            # process handle still supplies valid creation/exit times. Reuse a
            # previously queried path only for that same, demonstrably exited
            # process object; never invent a path or accept a live query failure.
            if (exit_time.value() and self._identity_path is not None
                    and self._identity_creation == creation.value()):
                return {"pid": self.pid, "image_path": self._identity_path,
                        "creation_filetime": creation.value(), "exited": True}
            raise _error("QueryFullProcessImageNameW")
        if not 0 < length.value < len(path):
            raise ProcessMemoryError("Process image path is empty or truncated")
        self._identity_path = path.value
        self._identity_creation = creation.value()
        return {"pid": self.pid, "image_path": path.value,
                "creation_filetime": creation.value(), "exited": exit_time.value() != 0}

    def module(self, expected_path: Path) -> dict:
        handle = self._open_handle()
        identity = self.identity()
        if identity["exited"]:
            raise ProcessMemoryError("Process has exited")
        if not _same_path(identity["image_path"], expected_path):
            raise ProcessMemoryError("Opened process image does not match the expected path")
        capacity = 128
        while True:
            modules = (HANDLE * capacity)()
            needed = UINT32()
            if not self._api.EnumProcessModulesEx(handle, modules, ctypes.sizeof(modules),
                                                  ctypes.byref(needed), 3):  # LIST_MODULES_ALL
                raise _error("EnumProcessModulesEx")
            if needed.value % ctypes.sizeof(HANDLE):
                raise ProcessMemoryError("Module enumeration returned an invalid byte count")
            count = needed.value // ctypes.sizeof(HANDLE)
            if count <= capacity:
                break
            if count > MAX_MODULES:
                raise ProcessMemoryError("Module enumeration exceeds the observer limit")
            capacity = min(MAX_MODULES, max(count, capacity * 2))
        found = []
        for module in modules[:count]:
            path = ctypes.create_unicode_buffer(32768)
            copied = self._api.GetModuleFileNameExW(handle, module, path, len(path))
            if not copied:
                raise _error("GetModuleFileNameExW")
            if copied >= len(path) - 1:
                raise ProcessMemoryError("Module image path is truncated")
            if not _same_path(path.value, expected_path):
                continue
            information = _ModuleInformation()
            if not self._api.GetModuleInformation(handle, module, ctypes.byref(information),
                                                  ctypes.sizeof(information)):
                raise _error("GetModuleInformation")
            base, size = int(information.lpBaseOfDll or 0), int(information.SizeOfImage)
            if not base or not size or base + size > 0xFFFFFFFFFFFFFFFF:
                raise ProcessMemoryError("Module information has an invalid image range")
            found.append({"base": base, "size": size})
        after = self.identity()
        if (after["exited"] or after["creation_filetime"] != identity["creation_filetime"]
                or not _same_path(after["image_path"], identity["image_path"])):
            raise ProcessMemoryError("Process identity changed during module enumeration")
        if len(found) != 1:
            raise ProcessMemoryError("Expected process image module was not uniquely found")
        return found[0]

    def read(self, address: int, size: int) -> bytes:
        handle = self._open_handle()
        if type(address) is not int or not 1 <= address <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("address must be a positive pointer integer")
        if type(size) is not int or not 0 <= size <= MAX_READ_SIZE:
            raise ValueError("size must be an integer between zero and 2 MiB")
        end = address + size
        if end > 0xFFFFFFFFFFFFFFFF:
            raise ValueError("Memory read range overflows a pointer")
        if not size:
            return b""
        position = address
        while position < end:
            information = _MemoryBasicInformation()
            result = self._api.VirtualQueryEx(handle, position, ctypes.byref(information),
                                              ctypes.sizeof(information))
            if result != ctypes.sizeof(information):
                raise _error("VirtualQueryEx complete record")
            base = int(information.BaseAddress or 0)
            region_end = base + int(information.RegionSize)
            if (base > position or region_end <= position or region_end > 0xFFFFFFFFFFFFFFFF
                    or information.State != MEM_COMMIT
                    or information.Protect & PAGE_GUARD
                    or information.Protect & 0xFF not in READABLE_PAGE_TYPES):
                raise ProcessMemoryError("Memory range includes uncommitted or unreadable pages")
            position = min(end, region_end)
        buffer = ctypes.create_string_buffer(size)
        copied = SIZE_T()
        if not self._api.ReadProcessMemory(handle, address, buffer, size, ctypes.byref(copied)):
            raise _error("ReadProcessMemory")
        if copied.value != size:
            raise ProcessMemoryError("ReadProcessMemory returned a short read")
        return buffer.raw
