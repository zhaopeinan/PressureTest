from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    stopping = "stopping"
    finished = "finished"
    failed = "failed"
    stopped = "stopped"


class LoadMode(str, Enum):
    """users: open/closed users with think-time; throughput: target aggregate RPS."""

    users = "users"
    throughput = "throughput"


class ScenarioInfo(BaseModel):
    id: str
    name: str
    description: str
    host_hint: str
    default_paths: list[str]
    supports_static_assets: bool = False


class DiscoverPathsRequest(BaseModel):
    host: str = "https://130th.bjtu.edu.cn"
    start_path: str = "/"
    max_pages: int = Field(default=1, ge=1, le=5)

    @field_validator("host")
    @classmethod
    def strip_host(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("start_path")
    @classmethod
    def normalize_start(cls, value: str) -> str:
        text = (value or "/").strip() or "/"
        if not text.startswith("/"):
            text = f"/{text}"
        return text


class DiscoveredPathItem(BaseModel):
    path: str
    kind: str = "page"  # page | api | asset
    status_code: int = 200
    content_type: str = ""


class DiscoverPathsResponse(BaseModel):
    host: str
    start_path: str
    paths: list[str]
    items: list[DiscoveredPathItem] = Field(default_factory=list)
    fetched_pages: int
    warnings: list[str] = Field(default_factory=list)


class RunCreate(BaseModel):
    scenario_id: str
    host: str = "https://130th.bjtu.edu.cn"
    load_mode: LoadMode = LoadMode.users
    users: int = Field(default=10, ge=1)
    spawn_rate: float = Field(default=2.0, gt=0)
    target_rps: float | None = Field(
        default=None,
        gt=0,
        description="Target aggregate RPS when load_mode=throughput",
    )
    duration: str = Field(default="60s", description="Locust run-time, e.g. 60s / 5m")
    workers: int = Field(default=1, ge=1, description="Locust worker processes for multi-core")
    paths: list[str] = Field(default_factory=lambda: ["/"])
    headers: dict[str, str] = Field(default_factory=dict)
    follow_static_assets: bool = False

    @field_validator("host")
    @classmethod
    def strip_host(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("paths")
    @classmethod
    def normalize_paths(cls, value: list[str]) -> list[str]:
        paths = []
        for item in value:
            text = (item or "").strip()
            if not text:
                continue
            if not text.startswith("/"):
                text = f"/{text}"
            paths.append(text)
        return paths or ["/"]


class EndpointStat(BaseModel):
    name: str
    method: str = "GET"
    num_requests: int = 0
    num_failures: int = 0
    current_rps: float = 0.0
    avg_response_time: float = 0.0
    min_response_time: float | None = None
    max_response_time: float | None = None
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None


class MetricsSnapshot(BaseModel):
    ts: datetime
    user_count: int = 0
    total_rps: float = 0.0
    fail_ratio: float = 0.0
    total_requests: int = 0
    total_failures: int = 0
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None
    endpoints: list[EndpointStat] = Field(default_factory=list)


class RunSummary(BaseModel):
    id: str
    scenario_id: str
    scenario_name: str
    host: str
    load_mode: LoadMode = LoadMode.users
    users: int
    spawn_rate: float
    target_rps: float | None = None
    duration: str
    workers: int = 1
    status: RunStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    latest_metrics: MetricsSnapshot | None = None


class RunDetail(RunSummary):
    paths: list[str]
    headers: dict[str, str]
    follow_static_assets: bool
    history: list[MetricsSnapshot] = Field(default_factory=list)
    report_path: str | None = None
    word_report_path: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class GuardrailsInfo(BaseModel):
    allowed_hosts: list[str]
    max_users: int
    max_spawn_rate: float
    max_duration_seconds: int
    max_workers: int
    max_target_rps: float


class LocustProcessMetrics(BaseModel):
    pid: int
    name: str
    status: str
    cpu_percent: float = 0.0
    memory_rss_mb: float = 0.0
    num_threads: int = 0


class SystemMetrics(BaseModel):
    ts: datetime
    hostname: str
    cpu_percent: float
    cpu_count: int
    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float
    load_avg_1: float | None = None
    load_avg_5: float | None = None
    load_avg_15: float | None = None
    net_sent_mbps: float = 0.0
    net_recv_mbps: float = 0.0
    locust: LocustProcessMetrics | None = None
    locust_processes: list[LocustProcessMetrics] = Field(default_factory=list)
    locust_process_count: int = 0
    locust_cpu_total_percent: float = 0.0
    bottleneck: str = "idle"
    hints: list[str] = Field(default_factory=list)
