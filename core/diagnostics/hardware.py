# core/diagnostics/hardware.py
"""Hardware Profiler — docs/research/v3-implementation-plan.md.

Stdlib-only for v1: works cross-platform without extra dependencies.
Windows uses ctypes for available RAM; POSIX reads /proc/meminfo when present.
"""
from __future__ import annotations

import ctypes
import os
import platform
import shutil
from pathlib import Path

import yaml
from pydantic import BaseModel


class HardwareProfile(BaseModel):
    total_ram_gb: float
    available_ram_gb: float
    cpu_count: int
    has_gpu: bool
    ram_detected: bool = True


def _ram_windows() -> tuple[float, float]:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
    gb = 1024 ** 3
    return stat.ullTotalPhys / gb, stat.ullAvailPhys / gb


def _ram_proc_meminfo() -> tuple[float, float]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as f:
        for line in f:
            key, _, rest = line.partition(":")
            kb = rest.strip().split()[0]
            values[key] = int(kb)
    total_gb = values.get("MemTotal", 0) / (1024 ** 2)
    available_gb = values.get("MemAvailable", values.get("MemFree", 0)) / (1024 ** 2)
    return total_gb, available_gb


def _detect_ram() -> tuple[float, float]:
    if platform.system() == "Windows":
        return _ram_windows()
    if os.path.exists("/proc/meminfo"):
        return _ram_proc_meminfo()
    # Fallback (e.g. macOS without extra deps): unknown, report 0 so doctor WARNs, not crashes.
    return 0.0, 0.0


def _detect_gpu() -> bool:
    return shutil.which("nvidia-smi") is not None


def detect_hardware() -> HardwareProfile:
    total_ram_gb, available_ram_gb = _detect_ram()
    # Only the unknown-platform fallback in _detect_ram() returns exactly
    # (0.0, 0.0) — a real machine reporting 0.0 available RAM would still
    # report a nonzero total. Treat that specific pair as "RAM undetected"
    # so callers (e.g. the router's RAM watchdog) don't mistake it for a
    # genuine zero-RAM reading and silently escalate to a cloud tier.
    ram_detected = not (total_ram_gb == 0.0 and available_ram_gb == 0.0)
    return HardwareProfile(
        total_ram_gb=round(total_ram_gb, 1),
        available_ram_gb=round(available_ram_gb, 1),
        cpu_count=os.cpu_count() or 1,
        has_gpu=_detect_gpu(),
        ram_detected=ram_detected,
    )


def write_hardware_profile(profile: HardwareProfile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(profile.model_dump(), f, sort_keys=False)
