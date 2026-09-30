from __future__ import annotations

from typing import TYPE_CHECKING

from app.scenarios.base import Scenario, ScenarioMeta, ScenarioRuntimeConfig, build_path_user

if TYPE_CHECKING:
    from locust import HttpUser


class ExampleGenericScenario(Scenario):
    """示例场景：复制本文件即可扩展到其他系统。"""

    meta = ScenarioMeta(
        id="example_generic",
        name="通用 HTTP 路径压测（示例）",
        description="可插拔示例场景。修改 host_hint 与 default_paths 即可用于其他系统。",
        host_hint="https://example.com",
        default_paths=["/"],
        supports_static_assets=False,
    )

    def build_user_class(self, config: ScenarioRuntimeConfig) -> type[HttpUser]:
        return build_path_user(
            class_name="ExampleGenericUser",
            paths=config.paths or self.meta.default_paths,
            headers=config.headers,
            wait_min=config.wait_time_min,
            wait_max=config.wait_time_max,
            follow_static_assets=False,
            load_mode=config.load_mode,
            target_rps=config.target_rps,
            users=config.users,
        )


scenario = ExampleGenericScenario()
