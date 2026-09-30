from __future__ import annotations

from typing import TYPE_CHECKING

from app.scenarios.base import Scenario, ScenarioMeta, ScenarioRuntimeConfig, build_path_user

if TYPE_CHECKING:
    from locust import HttpUser


class Bjtu130thScenario(Scenario):
    meta = ScenarioMeta(
        id="bjtu_130th",
        name="北京交大 130 周年站",
        description="对 https://130th.bjtu.edu.cn 首页及可配置页面路径进行 HTTP GET 压测。",
        host_hint="https://130th.bjtu.edu.cn",
        default_paths=["/", "/index.html"],
        supports_static_assets=True,
    )

    def build_user_class(self, config: ScenarioRuntimeConfig) -> type[HttpUser]:
        return build_path_user(
            class_name="Bjtu130thUser",
            paths=config.paths or self.meta.default_paths,
            headers=config.headers,
            wait_min=config.wait_time_min,
            wait_max=config.wait_time_max,
            follow_static_assets=config.follow_static_assets,
            load_mode=config.load_mode,
            target_rps=config.target_rps,
            users=config.users,
        )


scenario = Bjtu130thScenario()
