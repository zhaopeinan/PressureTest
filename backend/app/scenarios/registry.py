from __future__ import annotations

from app.models.schemas import ScenarioInfo
from app.scenarios.bjtu_130th import scenario as bjtu_130th
from app.scenarios.bjtu_map import scenario as bjtu_map
from app.scenarios.bjtu_welcome import scenario as bjtu_welcome
from app.scenarios.example_generic import scenario as example_generic
from app.scenarios.base import Scenario

_SCENARIOS: dict[str, Scenario] = {
    bjtu_130th.meta.id: bjtu_130th,
    bjtu_map.meta.id: bjtu_map,
    bjtu_welcome.meta.id: bjtu_welcome,
    example_generic.meta.id: example_generic,
}


def list_scenarios() -> list[ScenarioInfo]:
    items: list[ScenarioInfo] = []
    for scenario in _SCENARIOS.values():
        meta = scenario.meta
        items.append(
            ScenarioInfo(
                id=meta.id,
                name=meta.name,
                description=meta.description,
                host_hint=meta.host_hint,
                default_paths=list(meta.default_paths),
                supports_static_assets=meta.supports_static_assets,
            )
        )
    return sorted(items, key=lambda s: s.id)


def get_scenario(scenario_id: str) -> Scenario:
    try:
        return _SCENARIOS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"Unknown scenario: {scenario_id}") from exc


def register_scenario(scenario: Scenario) -> None:
    _SCENARIOS[scenario.meta.id] = scenario
