from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ServiceState(Enum):
    RUNNING = "running"
    DEAD = "dead"


@dataclass
class ServiceInfo:
    """service_registry 的值类型.
    INV: pid + command + log_path + started_at 必须存在, port 可为 None.
    """
    pid: int
    command: str
    log_path: str
    port: Optional[int] = None