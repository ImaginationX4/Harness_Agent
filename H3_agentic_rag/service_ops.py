"""service_ops.py — service_registry 的所有写操作。

契约:
  service_registry : dict[str, ServiceInfo]  — 调用方持有，通过参数传入
  INV: ∀ id ∈ registry, registry[id].pid 对应一个活着的进程（cleanup 负责最终清场）
"""
from __future__ import annotations
import os
import signal
import subprocess
import time

from models import ServiceInfo, ServiceState


def _alive(pid: int) -> ServiceState:
    try:
        os.kill(pid, 0)
        return ServiceState.RUNNING
    except ProcessLookupError:
        return ServiceState.DEAD


def _sigterm(pid: int) -> str:
    try:
        os.kill(pid, signal.SIGTERM)
        return "sent SIGTERM"
    except ProcessLookupError:
        return "already dead"


# ── tool handlers ────────────────────────────────────────────────────────────

def start_service(tool_input: dict, registry: dict) -> str:
    cmd = tool_input["command"]
    sid = tool_input["service_id"]
    port = tool_input.get("port")
    log_path = f"{sid}_{int(time.time())}.log"

    with open(log_path, "w") as log_file:
        proc = subprocess.Popen(cmd, shell=True, stdout=log_file, stderr=subprocess.STDOUT)

    time.sleep(2)
    if _alive(proc.pid) == ServiceState.DEAD:
        try:
            tail = open(log_path).read()[-500:]
        except OSError:
            tail = "(log unreadable)"
        return f"[error] service '{sid}' died immediately. log tail:\n{tail}"

    registry[sid] = ServiceInfo(pid=proc.pid, command=cmd, log_path=log_path, port=port)
    port_msg = f"port={port}" if port else "port=UNDECLARED (downstream http_check may fail)"
    return f"[ok] service '{sid}' started pid={proc.pid} {port_msg} log={log_path}"


def stop_service(tool_input: dict, registry: dict) -> str:
    sid = tool_input["service_id"]
    info = registry.pop(sid, None)
    if info is None:
        return f"[ok] service '{sid}' not in registry"
    status = _sigterm(info.pid)
    return f"[ok] service '{sid}' stopped ({status}, pid={info.pid}, port={info.port})"


def check_service(tool_input: dict, registry: dict) -> str:
    sid = tool_input["service_id"]
    info = registry.get(sid)
    if info is None:
        return f"[error] service '{sid}' not found in registry"
    if _alive(info.pid) == ServiceState.DEAD:
        registry.pop(sid, None)
        try:
            tail = open(info.log_path).read()[-500:]
        except OSError:
            tail = "(log unreadable)"
        return f"[fail] service '{sid}' DIED (pid={info.pid}, port={info.port}). log:\n{tail}"
    return (f"[ok] service '{sid}' state=running "
            f"pid={info.pid} port={info.port} log={info.log_path}")


def list_services(registry: dict) -> str:
    if not registry:
        return "[ok] no services running"
    lines = ["[ok] running services:"]
    for sid, info in registry.items():
        state = _alive(info.pid).value
        lines.append(f"  - {sid}: pid={info.pid} port={info.port} "
                     f"state={state} log={info.log_path} cmd={info.command!r}")
    return "\n".join(lines)


def cleanup(registry: dict) -> None:
    """兜底清场：不信任 LLM 自觉调 stop_service。"""
    for sid, info in list(registry.items()):
        status = _sigterm(info.pid)
        print(f"[cleanup] {sid} (pid={info.pid}, port={info.port}): {status}")
    registry.clear()