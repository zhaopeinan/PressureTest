from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PT_", env_file=".env", extra="ignore")

    reports_dir: Path = Path(__file__).resolve().parents[1] / "reports"
    allowed_hosts: str = (
        "130th.bjtu.edu.cn,welcome.bjtu.edu.cn,map.bjtu.edu.cn,localhost,127.0.0.1"
    )
    max_users: int = 50000
    max_spawn_rate: float = 500.0
    max_duration_seconds: int = 120 * 60
    max_workers: int = 8
    max_target_rps: float = 100000.0
    default_web_host: str = "127.0.0.1"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    def allowed_host_set(self) -> set[str]:
        return {h.strip().lower() for h in self.allowed_hosts.split(",") if h.strip()}

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
settings.reports_dir.mkdir(parents=True, exist_ok=True)
