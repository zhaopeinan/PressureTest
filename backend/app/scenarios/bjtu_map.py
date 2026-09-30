from __future__ import annotations

from typing import TYPE_CHECKING

from app.scenarios.base import Scenario, ScenarioMeta, ScenarioRuntimeConfig, build_path_user

if TYPE_CHECKING:
    from locust import HttpUser


class BjtuMapScenario(Scenario):
    meta = ScenarioMeta(
        id="bjtu_map",
        name="北京交大校园地图",
        description=(
            "对 https://map.bjtu.edu.cn 三维校园地图首页与公开 POI/检索接口进行 HTTP GET 压测。"
        ),
        host_hint="https://map.bjtu.edu.cn",
        default_paths=[
            "/",
            "/pois?term=图书馆",
            "/japi/get_poi_by_sort_xq?sortcode=002006&t=1",
            "/japi/get_poi_by_sort_xq?sortcode=010001&t=1",
            "/japi/get_poi_by_sort_xq?sortcode=010012&t=1",
            "/japi/get_poi_by_sort_xq?sortcode=010007&t=1",
        ],
        supports_static_assets=True,
    )

    def build_user_class(self, config: ScenarioRuntimeConfig) -> type[HttpUser]:
        return build_path_user(
            class_name="BjtuMapUser",
            paths=config.paths or self.meta.default_paths,
            headers=config.headers,
            wait_min=config.wait_time_min,
            wait_max=config.wait_time_max,
            follow_static_assets=config.follow_static_assets,
            load_mode=config.load_mode,
            target_rps=config.target_rps,
            users=config.users,
        )


scenario = BjtuMapScenario()
