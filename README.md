# PressureTest · Locust 本机压测工作台

本机启动的 Locust 压测控制台：通过 Web 前端配置场景/负载参数、启停压测，并实时查看 RPS、延迟、失败率。

内置场景：`bjtu_130th` → `https://130th.bjtu.edu.cn`；`bjtu_welcome` → `https://welcome.bjtu.edu.cn`；`bjtu_map` → `https://map.bjtu.edu.cn`。

> **重要**：仅对自有或已授权系统发起压测。默认 host 白名单、并发与时长上限见后端配置。

## 环境隔离（Conda）

本项目使用**独立 conda 环境** `pressure-test`，一项目一环境，避免依赖冲突。

```bash
# 一次性创建/更新环境
chmod +x scripts/setup_conda.sh scripts/start.sh
./scripts/setup_conda.sh

# 日常手动开发
conda activate pressure-test
export PYTHONNOUSERSITE=1   # 阻止 ~/.local 用户包污染本环境
```

定义见根目录 [`environment.yml`](environment.yml)（Python 3.12 + pip 安装 backend 依赖）。  
不要用系统 `venv` / 全局 Python 跑本项目；统一走 conda。

## 架构

- **前端**：React + Vite（`http://localhost:5173`）
- **控制层**：FastAPI（`http://localhost:8000`）
- **引擎**：Locust（由控制层以子进程拉起，场景可插拔）
- **结果**：写入 `backend/reports/<run_id>/`

## 快速启动

```bash
./scripts/start.sh
```

脚本会自动 `conda activate pressure-test`（不存在则创建），再启动前后端。  
然后打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。

### 分别启动

```bash
# 后端
conda activate pressure-test
cd backend
export PYTHONPATH="$(pwd)"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 前端（另开终端）
cd frontend
npm install
npm run dev
```

### Docker Compose

```bash
docker compose up --build
```

说明：开发联调优先用 conda + `scripts/start.sh`；Docker 适合环境打包演示。

## 使用方式

1. 选择场景（默认「北京交大 130 周年站」）
2. 配置 host / users / spawn rate / duration / paths
3. 点击「开始压测」
4. 右侧查看实时 KPI、曲线与 endpoint 表
5. 结束后在左侧历史列表回看，报告落在 `backend/reports/<run_id>/`

小流量冒烟建议：`users=3`，`spawn_rate=1`，`duration=20s`。

## 如何新增场景（扩展其他系统）

1. 复制 [`backend/app/scenarios/example_generic.py`](backend/app/scenarios/example_generic.py)
2. 修改 `ScenarioMeta`（`id` / `name` / `host_hint` / `default_paths`）与 `build_user_class` 行为
3. 在 [`backend/app/scenarios/registry.py`](backend/app/scenarios/registry.py) 注册
4. 把目标域名加入白名单环境变量 `PT_ALLOWED_HOSTS`
5. 重启后端，前端场景下拉即可看到新场景

复杂流程（登录、表单、API 序列）可在场景里用 Locust `@task` / `SequentialTaskSet` 自由编写，无需改控制层。

## 护栏配置

环境变量（前缀 `PT_`）：

| 变量 | 默认 | 含义 |
|---|---|---|
| `PT_ALLOWED_HOSTS` | `130th.bjtu.edu.cn,welcome.bjtu.edu.cn,map.bjtu.edu.cn,localhost,127.0.0.1` | 允许压测的 hostname |
| `PT_MAX_USERS` | `50000` | 最大并发用户 |
| `PT_MAX_SPAWN_RATE` | `500` | 最大爬坡速率 |
| `PT_MAX_DURATION_SECONDS` | `7200` | 最大时长（秒，默认 120 分钟） |
| `PT_MAX_WORKERS` | `8` | 本机 Locust Worker 上限 |
| `PT_CORS_ORIGINS` | `http://localhost:5173,...` | 前端来源 |

## API 摘要

- `GET /api/scenarios` 场景列表
- `POST /api/runs` 创建并启动
- `POST /api/runs/{id}/stop` 停止
- `GET /api/runs/{id}` 详情
- `GET /api/runs/{id}/events` SSE 实时推送
- `GET /api/guardrails` 护栏信息

接口形状按「run 资源」设计，后续可把本机 subprocess runner 换成远程 worker，而不改前端。

## 目录

```text
PressureTest/
  environment.yml       # conda 环境定义（pressure-test）
  backend/app/          # FastAPI + Locust 场景
  frontend/src/         # 工作台 UI
  scripts/setup_conda.sh
  scripts/start.sh
  docker-compose.yml
```
