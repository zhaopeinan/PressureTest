from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models.schemas import (
    LoadMode,
    MetricsSnapshot,
    RunCreate,
    RunDetail,
    RunStatus,
    RunSummary,
)
from app.scenarios.registry import get_scenario
from app.services.duration import normalize_duration, parse_duration_seconds
from app.services.stats_collector import parse_locust_stats
from app.services.word_report import build_word_report, word_report_path_for

LOCUSTFILE_TEMPLATE = '''\
"""Auto-generated Locust entrypoint for run {run_id}."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(r"{backend_root}")
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.scenarios.base import ScenarioRuntimeConfig
from app.scenarios.registry import get_scenario

_config = ScenarioRuntimeConfig.from_env()
_scenario = get_scenario("{scenario_id}")
# Locust scans module globals for HttpUser subclasses; keep exactly one reference.
_user_cls = _scenario.build_user_class(_config)
globals()[_user_cls.__name__] = _user_cls
del _config, _scenario, _user_cls
'''


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((settings.default_web_host, 0))
        return int(sock.getsockname()[1])


def _host_allowed(host: str) -> None:
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("host must include a valid hostname")
    allowed = settings.allowed_host_set()
    if hostname not in allowed and not any(hostname.endswith(f".{h}") for h in allowed):
        raise ValueError(
            f"host '{hostname}' is not in allowlist: {', '.join(sorted(allowed))}"
        )


def _validate_create(payload: RunCreate) -> str:
    _host_allowed(payload.host)
    if payload.users > settings.max_users:
        raise ValueError(f"users exceeds max_users={settings.max_users}")
    if payload.spawn_rate > settings.max_spawn_rate:
        raise ValueError(f"spawn_rate exceeds max_spawn_rate={settings.max_spawn_rate}")
    if payload.workers < 1 or payload.workers > settings.max_workers:
        raise ValueError(f"workers must be between 1 and {settings.max_workers}")
    if payload.load_mode == LoadMode.throughput:
        if payload.target_rps is None or payload.target_rps <= 0:
            raise ValueError("target_rps is required when load_mode=throughput")
        if payload.target_rps > settings.max_target_rps:
            raise ValueError(f"target_rps exceeds max_target_rps={settings.max_target_rps}")
    duration = normalize_duration(payload.duration)
    seconds = parse_duration_seconds(duration)
    if seconds > settings.max_duration_seconds:
        raise ValueError(f"duration exceeds max_duration_seconds={settings.max_duration_seconds}")
    get_scenario(payload.scenario_id)
    return duration


@dataclass
class RunState:
    id: str
    scenario_id: str
    scenario_name: str
    host: str
    users: int
    spawn_rate: float
    duration: str
    paths: list[str]
    headers: dict[str, str]
    follow_static_assets: bool
    load_mode: LoadMode = LoadMode.users
    target_rps: float | None = None
    workers: int = 1
    status: RunStatus = RunStatus.queued
    created_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    web_port: int | None = None
    master_port: int | None = None
    process: asyncio.subprocess.Process | None = None  # master or single process
    worker_processes: list[asyncio.subprocess.Process] = field(default_factory=list)
    history: list[MetricsSnapshot] = field(default_factory=list)
    latest_metrics: MetricsSnapshot | None = None
    report_path: Path | None = None
    word_report_path: Path | None = None
    run_dir: Path | None = None
    collector_task: asyncio.Task[None] | None = None
    waiter_task: asyncio.Task[None] | None = None
    log_file: TextIO | None = None
    worker_log_files: list[TextIO] = field(default_factory=list)

    def locust_pids(self) -> list[int]:
        pids: list[int] = []
        if self.process and self.process.returncode is None and self.process.pid:
            pids.append(self.process.pid)
        for proc in self.worker_processes:
            if proc.returncode is None and proc.pid:
                pids.append(proc.pid)
        return pids

    def to_summary(self) -> RunSummary:
        return RunSummary(
            id=self.id,
            scenario_id=self.scenario_id,
            scenario_name=self.scenario_name,
            host=self.host,
            load_mode=self.load_mode,
            users=self.users,
            spawn_rate=self.spawn_rate,
            target_rps=self.target_rps,
            duration=self.duration,
            workers=self.workers,
            status=self.status,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
            error=self.error,
            latest_metrics=self.latest_metrics,
        )

    def to_detail(self) -> RunDetail:
        return RunDetail(
            **self.to_summary().model_dump(),
            paths=self.paths,
            headers=self.headers,
            follow_static_assets=self.follow_static_assets,
            history=list(self.history),
            report_path=str(self.report_path) if self.report_path else None,
            word_report_path=str(self.word_report_path) if self.word_report_path else None,
            config={
                "host": self.host,
                "load_mode": self.load_mode.value,
                "users": self.users,
                "spawn_rate": self.spawn_rate,
                "target_rps": self.target_rps,
                "duration": self.duration,
                "workers": self.workers,
                "paths": self.paths,
                "headers": self.headers,
                "follow_static_assets": self.follow_static_assets,
            },
        )


class LocustRunner:
    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._lock = asyncio.Lock()
        self._load_existing_reports()

    def _load_existing_reports(self) -> None:
        root = settings.reports_dir
        if not root.exists():
            return
        for path in sorted(root.iterdir(), reverse=True):
            report = path / "report.json"
            if not report.is_file():
                continue
            try:
                data = json.loads(report.read_text(encoding="utf-8"))
                detail = RunDetail.model_validate(data)
                state = RunState(
                    id=detail.id,
                    scenario_id=detail.scenario_id,
                    scenario_name=detail.scenario_name,
                    host=detail.host,
                    users=detail.users,
                    spawn_rate=detail.spawn_rate,
                    duration=detail.duration,
                    paths=detail.paths,
                    headers=detail.headers,
                    follow_static_assets=detail.follow_static_assets,
                    load_mode=detail.load_mode,
                    target_rps=detail.target_rps,
                    workers=detail.workers,
                    status=detail.status,
                    created_at=detail.created_at,
                    started_at=detail.started_at,
                    finished_at=detail.finished_at,
                    error=detail.error,
                    history=detail.history,
                    latest_metrics=detail.latest_metrics,
                    report_path=report,
                    word_report_path=path / "report.docx"
                    if (path / "report.docx").is_file()
                    else None,
                    run_dir=path,
                )
                self._runs[state.id] = state
            except Exception:
                continue

    def list_runs(self) -> list[RunSummary]:
        return sorted(
            (run.to_summary() for run in self._runs.values()),
            key=lambda r: r.created_at,
            reverse=True,
        )

    def get_run(self, run_id: str) -> RunState:
        if run_id not in self._runs:
            raise KeyError(run_id)
        return self._runs[run_id]

    def active_run(self) -> RunState | None:
        for run in self._runs.values():
            if run.status in {RunStatus.queued, RunStatus.running, RunStatus.stopping}:
                return run
        return None

    async def create_run(self, payload: RunCreate) -> RunState:
        duration = _validate_create(payload)
        scenario = get_scenario(payload.scenario_id)

        async with self._lock:
            if self.active_run() is not None:
                raise RuntimeError("Another run is already active. Stop it before starting a new one.")

            run_id = uuid.uuid4().hex[:12]
            run_dir = settings.reports_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                id=run_id,
                scenario_id=scenario.meta.id,
                scenario_name=scenario.meta.name,
                host=payload.host,
                users=payload.users,
                spawn_rate=payload.spawn_rate,
                duration=duration,
                paths=list(payload.paths),
                headers=dict(payload.headers),
                follow_static_assets=payload.follow_static_assets,
                load_mode=payload.load_mode,
                target_rps=payload.target_rps if payload.load_mode == LoadMode.throughput else None,
                workers=payload.workers,
                run_dir=run_dir,
            )
            self._runs[run_id] = state

            config = {
                "host": payload.host,
                "paths": payload.paths,
                "headers": payload.headers,
                "follow_static_assets": payload.follow_static_assets,
                "load_mode": payload.load_mode.value,
                "target_rps": state.target_rps,
                "users": payload.users,
            }
            (run_dir / "config.json").write_text(
                json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            backend_root = Path(__file__).resolve().parents[2]
            locustfile = run_dir / "locustfile.py"
            locustfile.write_text(
                LOCUSTFILE_TEMPLATE.format(
                    run_id=run_id,
                    backend_root=str(backend_root),
                    scenario_id=payload.scenario_id,
                ),
                encoding="utf-8",
            )

            web_port = _free_port()
            state.web_port = web_port
            state.status = RunStatus.running
            state.started_at = _utc_now()

            env = os.environ.copy()
            env["PT_SCENARIO_CONFIG"] = json.dumps(config, ensure_ascii=False)
            env["PYTHONPATH"] = (
                str(backend_root)
                + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            )

            log_path = run_dir / "locust.log"
            log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
            state.log_file = log_file

            common_tail = [
                "--host",
                payload.host,
                "--users",
                str(payload.users),
                "--spawn-rate",
                str(payload.spawn_rate),
                "--run-time",
                duration,
                "--autostart",
                "--autoquit",
                "1",
                "--csv",
                str(run_dir / "stats"),
                "--html",
                str(run_dir / "locust-report.html"),
            ]

            meta: dict[str, Any]
            if payload.workers <= 1:
                cmd = [
                    sys.executable,
                    "-m",
                    "locust",
                    "-f",
                    str(locustfile),
                    "--web-host",
                    settings.default_web_host,
                    "--web-port",
                    str(web_port),
                    *common_tail,
                ]
                state.process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(backend_root),
                    env=env,
                    stdout=log_file,
                    stderr=asyncio.subprocess.STDOUT,
                )
                meta = {
                    "mode": "single",
                    "workers": 1,
                    "pid": state.process.pid,
                    "web_port": web_port,
                    "cmd": cmd,
                }
            else:
                master_port = _free_port()
                state.master_port = master_port
                master_cmd = [
                    sys.executable,
                    "-m",
                    "locust",
                    "-f",
                    str(locustfile),
                    "--master",
                    "--master-bind-host",
                    settings.default_web_host,
                    "--master-bind-port",
                    str(master_port),
                    "--expect-workers",
                    str(payload.workers),
                    "--web-host",
                    settings.default_web_host,
                    "--web-port",
                    str(web_port),
                    *common_tail,
                ]
                state.process = await asyncio.create_subprocess_exec(
                    *master_cmd,
                    cwd=str(backend_root),
                    env=env,
                    stdout=log_file,
                    stderr=asyncio.subprocess.STDOUT,
                )

                worker_cmds: list[list[str]] = []
                worker_pids: list[int | None] = []
                for idx in range(payload.workers):
                    worker_log = open(  # noqa: SIM115
                        run_dir / f"worker-{idx}.log", "w", encoding="utf-8"
                    )
                    state.worker_log_files.append(worker_log)
                    worker_cmd = [
                        sys.executable,
                        "-m",
                        "locust",
                        "-f",
                        str(locustfile),
                        "--worker",
                        "--master-host",
                        settings.default_web_host,
                        "--master-port",
                        str(master_port),
                    ]
                    worker_cmds.append(worker_cmd)
                    proc = await asyncio.create_subprocess_exec(
                        *worker_cmd,
                        cwd=str(backend_root),
                        env=env,
                        stdout=worker_log,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    state.worker_processes.append(proc)
                    worker_pids.append(proc.pid)

                meta = {
                    "mode": "distributed",
                    "workers": payload.workers,
                    "master_pid": state.process.pid,
                    "worker_pids": worker_pids,
                    "web_port": web_port,
                    "master_port": master_port,
                    "master_cmd": master_cmd,
                    "worker_cmds": worker_cmds,
                }

            (run_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            state.collector_task = asyncio.create_task(
                self._collect_loop(state), name=f"collect-{run_id}"
            )
            state.waiter_task = asyncio.create_task(
                self._wait_process(state), name=f"wait-{run_id}"
            )
            return state

    async def stop_run(self, run_id: str) -> RunState:
        state = self.get_run(run_id)
        if state.status not in {RunStatus.queued, RunStatus.running}:
            return state

        state.status = RunStatus.stopping
        if state.web_port:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    await client.get(
                        f"http://{settings.default_web_host}:{state.web_port}/stop"
                    )
            except Exception:
                pass

        await self._terminate_process_tree(state)

        if state.status != RunStatus.finished:
            state.status = RunStatus.stopped
        state.finished_at = state.finished_at or _utc_now()
        await self._finalize(state)
        return state

    async def _terminate_process_tree(self, state: RunState) -> None:
        procs: list[asyncio.subprocess.Process] = []
        if state.process and state.process.returncode is None:
            procs.append(state.process)
        procs.extend([p for p in state.worker_processes if p.returncode is None])

        for proc in procs:
            try:
                proc.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass

        async def _wait_one(proc: asyncio.subprocess.Process) -> None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=8)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass

        if procs:
            await asyncio.gather(*[_wait_one(p) for p in procs])

    async def _wait_process(self, state: RunState) -> None:
        assert state.process is not None
        try:
            code = await state.process.wait()
            # Master/single exited: ensure workers are cleaned up.
            await self._terminate_process_tree(state)

            if state.status in {RunStatus.stopping, RunStatus.stopped}:
                if state.finished_at is None:
                    state.finished_at = _utc_now()
                    await self._finalize(state)
                return
            if code == 0:
                state.status = RunStatus.finished
            else:
                state.status = RunStatus.failed
                state.error = f"Locust exited with code {code}. See locust.log."
            state.finished_at = _utc_now()
            await self._finalize(state)
        except Exception as exc:
            state.status = RunStatus.failed
            state.error = str(exc)
            state.finished_at = _utc_now()
            await self._terminate_process_tree(state)
            await self._finalize(state)
        finally:
            for fh in [state.log_file, *state.worker_log_files]:
                if fh:
                    try:
                        fh.close()
                    except Exception:
                        pass
            state.log_file = None
            state.worker_log_files = []

    async def _collect_loop(self, state: RunState) -> None:
        assert state.web_port is not None
        url = f"http://{settings.default_web_host}:{state.web_port}/stats/requests"
        async with httpx.AsyncClient(timeout=2.0) as client:
            while state.status in {RunStatus.running, RunStatus.stopping}:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        payload = resp.json()
                        user_count = int(payload.get("user_count") or 0)
                        if user_count == 0 and state.status == RunStatus.running and state.started_at:
                            elapsed = (_utc_now() - state.started_at).total_seconds()
                            user_count = min(state.users, max(0, int(elapsed * state.spawn_rate)))
                        metrics = parse_locust_stats(payload, user_count=user_count)
                        if "total_rps" in payload:
                            metrics.total_rps = float(payload["total_rps"] or 0.0)
                        if "fail_ratio" in payload:
                            metrics.fail_ratio = float(payload["fail_ratio"] or 0.0)
                        # Distributed: expose connected worker count when present
                        worker_count = payload.get("worker_count")
                        if worker_count is not None:
                            # stash lightly in endpoint-free fashion via history only
                            pass
                        state.latest_metrics = metrics
                        state.history.append(metrics)
                        if len(state.history) > 600:
                            state.history = state.history[-600:]
                        self._write_live(state)
                except Exception:
                    pass
                await asyncio.sleep(1)

    def _write_live(self, state: RunState) -> None:
        if not state.run_dir:
            return
        live = state.run_dir / "live.json"
        live.write_text(
            json.dumps(state.to_detail().model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def _finalize(self, state: RunState) -> None:
        if state.collector_task and not state.collector_task.done():
            state.collector_task.cancel()
            try:
                await state.collector_task
            except asyncio.CancelledError:
                pass

        if state.web_port:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(
                        f"http://{settings.default_web_host}:{state.web_port}/stats/requests"
                    )
                    if resp.status_code == 200:
                        payload = resp.json()
                        metrics = parse_locust_stats(
                            payload, user_count=int(payload.get("user_count") or 0)
                        )
                        if "total_rps" in payload:
                            metrics.total_rps = float(payload["total_rps"] or 0.0)
                        if "fail_ratio" in payload:
                            metrics.fail_ratio = float(payload["fail_ratio"] or 0.0)
                        state.latest_metrics = metrics
                        state.history.append(metrics)
            except Exception:
                pass

        if not state.run_dir:
            return

        report_path = state.run_dir / "report.json"
        detail = state.to_detail()
        detail.report_path = str(report_path)
        state.report_path = report_path
        report_path.write_text(
            json.dumps(detail.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        m = state.latest_metrics
        (state.run_dir / "summary.md").write_text(
            "\n".join(
                [
                    f"# Run {state.id}",
                    "",
                    f"- Scenario: {state.scenario_name} (`{state.scenario_id}`)",
                    f"- Host: {state.host}",
                    f"- Load mode: {state.load_mode.value}",
                    f"- Users: {state.users}",
                    f"- Workers: {state.workers}",
                    f"- Spawn rate: {state.spawn_rate}",
                    f"- Target RPS: {state.target_rps if state.target_rps is not None else '-'}",
                    f"- Duration: {state.duration}",
                    f"- Status: {state.status.value}",
                    f"- Requests: {m.total_requests if m else 0}",
                    f"- Failures: {m.total_failures if m else 0}",
                    f"- Fail ratio: {(m.fail_ratio if m else 0):.2%}",
                    f"- RPS: {m.total_rps if m else 0}",
                    f"- p95: {m.p95 if m else None}",
                    "",
                    "> Only load-test systems you own or are authorized to test.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        try:
            self.ensure_word_report(state, force=True)
        except Exception:
            # JSON/markdown reports remain available even if Word export fails.
            pass

    def ensure_word_report(self, state: RunState, *, force: bool = False) -> Path:
        if state.status not in {RunStatus.finished, RunStatus.stopped, RunStatus.failed}:
            raise RuntimeError("Word report is available only after the run ends")
        if not state.run_dir:
            raise RuntimeError("Run directory missing")

        out = word_report_path_for(state.run_dir)
        if out.is_file() and not force:
            state.word_report_path = out
            return out

        detail = state.to_detail()
        build_word_report(detail, out)
        state.word_report_path = out

        # Persist path into report.json when present.
        if state.report_path and state.report_path.is_file():
            try:
                data = json.loads(state.report_path.read_text(encoding="utf-8"))
                data["word_report_path"] = str(out)
                state.report_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass
        return out


runner = LocustRunner()
