from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from locust import HttpUser


@dataclass
class ScenarioMeta:
    id: str
    name: str
    description: str
    host_hint: str
    default_paths: list[str]
    supports_static_assets: bool = False


@dataclass
class ScenarioRuntimeConfig:
    host: str
    paths: list[str]
    headers: dict[str, str] = field(default_factory=dict)
    follow_static_assets: bool = False
    # Short think-time so RPS can scale with users; override via PT_SCENARIO_CONFIG.
    wait_time_min: float = 0.05
    wait_time_max: float = 0.2
    load_mode: str = "users"  # users | throughput
    target_rps: float | None = None
    users: int = 1

    @classmethod
    def from_env(cls) -> ScenarioRuntimeConfig:
        raw = os.environ.get("PT_SCENARIO_CONFIG", "{}")
        data = json.loads(raw)
        target = data.get("target_rps")
        return cls(
            host=data.get("host", "http://localhost"),
            paths=data.get("paths") or ["/"],
            headers=data.get("headers") or {},
            follow_static_assets=bool(data.get("follow_static_assets", False)),
            wait_time_min=float(data.get("wait_time_min", 0.05)),
            wait_time_max=float(data.get("wait_time_max", 0.2)),
            load_mode=str(data.get("load_mode") or "users"),
            target_rps=float(target) if target is not None else None,
            users=max(1, int(data.get("users") or 1)),
        )


def build_path_user(
    *,
    class_name: str,
    paths: list[str],
    headers: dict[str, str],
    wait_min: float,
    wait_max: float,
    follow_static_assets: bool = False,
    load_mode: str = "users",
    target_rps: float | None = None,
    users: int = 1,
) -> type[HttpUser]:
    """Dynamically build an HttpUser that samples configured paths."""
    import random

    from locust import HttpUser, between, constant_throughput, task

    normalized = [p if p.startswith("/") else f"/{p}" for p in paths] or ["/"]

    if load_mode == "throughput" and target_rps and target_rps > 0:
        # Each user aims for target_rps / users task starts per second.
        per_user = max(float(target_rps) / max(int(users), 1), 1e-6)
        wait = constant_throughput(per_user)
    else:
        wait = between(wait_min, wait_max)

    class DynamicPathUser(HttpUser):
        wait_time = wait

        def on_start(self) -> None:
            for key, value in headers.items():
                self.client.headers[key] = value

        @task(5)
        def hit_one_path(self) -> None:
            # One request per iteration so RPS scales with user count / throughput pacing.
            path = random.choice(normalized)
            with self.client.get(path, name=path, catch_response=True) as response:
                if response.status_code >= 400:
                    response.failure(f"status {response.status_code}")
                else:
                    response.success()

        @task(1)
        def hit_home(self) -> None:
            path = normalized[0]
            with self.client.get(path, name=path, catch_response=True) as response:
                if response.status_code >= 400:
                    response.failure(f"status {response.status_code}")
                else:
                    response.success()
                    if follow_static_assets:
                        text = response.text or ""
                        for marker in ('href="/static/', 'src="/static/'):
                            if marker not in text:
                                continue
                            prefix = 'href="' if "href" in marker else 'src="'
                            start = text.find(marker) + len(prefix)
                            end = text.find('"', start)
                            asset = text[start:end]
                            if asset.startswith("/"):
                                self.client.get(asset, name="[static]")
                            break

    DynamicPathUser.__name__ = class_name
    DynamicPathUser.__qualname__ = class_name
    return DynamicPathUser


class Scenario:
    meta: ScenarioMeta

    def build_user_class(self, config: ScenarioRuntimeConfig) -> type[HttpUser]:
        raise NotImplementedError

    def default_config_dict(self) -> dict[str, Any]:
        return {
            "host": self.meta.host_hint,
            "paths": list(self.meta.default_paths),
            "headers": {"User-Agent": "PressureTest-Locust/0.1"},
            "follow_static_assets": False,
            "load_mode": "users",
            "target_rps": None,
            "users": 1,
        }
