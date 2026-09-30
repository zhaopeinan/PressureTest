from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import psutil

# Prime system-wide cpu_percent so subsequent non-blocking calls return meaningful values.
psutil.cpu_percent(interval=None)
_prev_net = psutil.net_io_counters()
_prev_net_ts = time.time()

# Keep Process objects so cpu_percent(interval=None) can compare against prior sample.
_proc_cache: dict[int, psutil.Process] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_proc(pid: int) -> psutil.Process | None:
    cached = _proc_cache.get(pid)
    if cached is not None:
        try:
            if cached.is_running():
                return cached
        except (psutil.Error, ValueError):
            pass
        _proc_cache.pop(pid, None)
    try:
        proc = psutil.Process(pid)
        # Prime once; first cpu_percent call is always 0.0
        proc.cpu_percent(interval=None)
        _proc_cache[pid] = proc
        return proc
    except (psutil.Error, ValueError):
        return None


def _prune_proc_cache(alive_pids: set[int]) -> None:
    for pid in list(_proc_cache.keys()):
        if pid not in alive_pids:
            _proc_cache.pop(pid, None)


def collect_system_metrics(locust_pids: list[int] | int | None = None) -> dict[str, Any]:
    global _prev_net, _prev_net_ts

    if locust_pids is None:
        pids: list[int] = []
    elif isinstance(locust_pids, int):
        pids = [locust_pids]
    else:
        pids = [p for p in locust_pids if p]

    alive = set(pids)
    _prune_proc_cache(alive)

    vm = psutil.virtual_memory()
    cpu_percent = float(psutil.cpu_percent(interval=None))
    cpu_count = psutil.cpu_count(logical=True) or 1

    load_1 = load_5 = load_15 = None
    try:
        load_1, load_5, load_15 = os.getloadavg()
    except (AttributeError, OSError):
        pass

    now = time.time()
    net = psutil.net_io_counters()
    dt = max(now - _prev_net_ts, 1e-6)
    net_sent_mbps = (net.bytes_sent - _prev_net.bytes_sent) * 8 / dt / 1_000_000
    net_recv_mbps = (net.bytes_recv - _prev_net.bytes_recv) * 8 / dt / 1_000_000
    _prev_net = net
    _prev_net_ts = now

    # Ensure Process objects exist and are primed.
    procs: list[psutil.Process] = []
    for pid in pids:
        proc = _get_proc(pid)
        if proc is not None:
            procs.append(proc)

    # Let a short window elapse so subsequent cpu_percent reads are meaningful.
    if procs:
        time.sleep(0.15)

    processes: list[dict[str, Any]] = []
    for proc in procs:
        try:
            with proc.oneshot():
                mem = proc.memory_info()
                processes.append(
                    {
                        "pid": proc.pid,
                        "name": proc.name(),
                        "status": proc.status(),
                        "cpu_percent": round(float(proc.cpu_percent(interval=None)), 1),
                        "memory_rss_mb": round(mem.rss / (1024 * 1024), 1),
                        "num_threads": proc.num_threads(),
                    }
                )
        except (psutil.Error, ValueError):
            _proc_cache.pop(proc.pid, None)
            continue

    locust_cpu_total = round(sum(p["cpu_percent"] for p in processes), 1)
    locust_busy = bool(processes) and (
        any(p["cpu_percent"] >= 80 for p in processes)
        or locust_cpu_total >= max(80.0, cpu_count * 35)
    )
    primary = processes[0] if processes else None

    bottleneck = "idle"
    hints: list[str] = []
    if cpu_percent >= 85:
        bottleneck = "generator_cpu"
        hints.append("发压机整机 CPU 较高，结果可能低估目标站真实承载能力")
    elif vm.percent >= 90:
        bottleneck = "generator_memory"
        hints.append("发压机内存紧张，继续加用户可能失真")
    elif locust_busy:
        bottleneck = "locust_process"
        hints.append(
            f"Locust 共 {len(processes)} 个进程，合计 CPU {locust_cpu_total:.0f}%；"
            "单机发压接近上限时可增加 Workers"
        )
    elif cpu_percent < 60 and processes:
        bottleneck = "headroom"
        hints.append("发压机仍有余量，若目标站延迟/错误上升，更可能是目标站瓶颈")
    elif processes:
        bottleneck = "balanced"
        hints.append("发压机负载中等，请结合目标站监控交叉判断")

    return {
        "ts": _utc_now(),
        "hostname": os.uname().nodename if hasattr(os, "uname") else "local",
        "cpu_percent": round(cpu_percent, 1),
        "cpu_count": cpu_count,
        "memory_percent": round(float(vm.percent), 1),
        "memory_used_gb": round(vm.used / (1024**3), 2),
        "memory_total_gb": round(vm.total / (1024**3), 2),
        "load_avg_1": round(load_1, 2) if load_1 is not None else None,
        "load_avg_5": round(load_5, 2) if load_5 is not None else None,
        "load_avg_15": round(load_15, 2) if load_15 is not None else None,
        "net_sent_mbps": round(max(net_sent_mbps, 0.0), 3),
        "net_recv_mbps": round(max(net_recv_mbps, 0.0), 3),
        "locust": primary,
        "locust_processes": processes,
        "locust_process_count": len(processes),
        "locust_cpu_total_percent": locust_cpu_total,
        "bottleneck": bottleneck,
        "hints": hints,
    }
