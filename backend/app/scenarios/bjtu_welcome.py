from __future__ import annotations

from typing import TYPE_CHECKING

from app.scenarios.base import Scenario, ScenarioMeta, ScenarioRuntimeConfig, build_path_user

if TYPE_CHECKING:
    from locust import HttpUser


class BjtuWelcomeScenario(Scenario):
    meta = ScenarioMeta(
        id="bjtu_welcome",
        name="北京交大迎新网",
        description=(
            "对 https://welcome.bjtu.edu.cn 首页壳与公开 /v1 API 进行 HTTP GET 压测。"
            "登录态接口可在 UI 中补充路径后压测。"
        ),
        host_hint="https://welcome.bjtu.edu.cn",
        default_paths=[
            "/",
            "/v1/cms/home/express/",
            "/v1/cms/index/column/",
            "/v1/student/xy/",
            "/v1/student/xsinfo/",
            "/v1/user/admin_user/info/",
        ],
        supports_static_assets=True,
    )

    def build_user_class(self, config: ScenarioRuntimeConfig) -> type[HttpUser]:
        return build_path_user(
            class_name="BjtuWelcomeUser",
            paths=config.paths or self.meta.default_paths,
            headers=config.headers,
            wait_min=config.wait_time_min,
            wait_max=config.wait_time_max,
            follow_static_assets=config.follow_static_assets,
            load_mode=config.load_mode,
            target_rps=config.target_rps,
            users=config.users,
        )


scenario = BjtuWelcomeScenario()
