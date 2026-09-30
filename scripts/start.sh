#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENV_NAME="${CONDA_ENV_NAME:-pressure-test}"

echo "==> PressureTest local start (conda env: ${ENV_NAME})"
echo "    Only load-test systems you own or are authorized to test."

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required" >&2
  exit 1
fi

# shellcheck disable=SC1091
if [[ -f "/opt/anaconda3/etc/profile.d/conda.sh" ]]; then
  source "/opt/anaconda3/etc/profile.d/conda.sh"
elif [[ -f "${HOME}/anaconda3/etc/profile.d/conda.sh" ]]; then
  source "${HOME}/anaconda3/etc/profile.d/conda.sh"
elif [[ -f "${HOME}/miniconda3/etc/profile.d/conda.sh" ]]; then
  source "${HOME}/miniconda3/etc/profile.d/conda.sh"
elif command -v conda >/dev/null 2>&1; then
  eval "$(conda shell.zsh hook 2>/dev/null || conda shell.bash hook)"
else
  echo "conda is required. Install Anaconda/Miniconda first." >&2
  exit 1
fi

if ! conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "==> Creating conda env '${ENV_NAME}' from environment.yml"
  conda env create -f "${ROOT}/environment.yml"
else
  echo "==> Reusing conda env '${ENV_NAME}' (run ./scripts/setup_conda.sh to update)"
fi

conda activate "${ENV_NAME}"
# Avoid ~/.local user-site packages leaking into this project env.
export PYTHONNOUSERSITE=1
echo "==> Using $(python -V) at $(which python)"

echo "==> Ensuring backend package is installed in conda env"
python -m pip install -q -e "${ROOT}/backend"

echo "==> Installing frontend deps"
(cd "${ROOT}/frontend" && npm install --silent)

export PT_ALLOWED_HOSTS="${PT_ALLOWED_HOSTS:-130th.bjtu.edu.cn,welcome.bjtu.edu.cn,map.bjtu.edu.cn,localhost,127.0.0.1}"
export PT_CORS_ORIGINS="${PT_CORS_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173}"
export PYTHONPATH="${ROOT}/backend${PYTHONPATH:+:$PYTHONPATH}"

cleanup() {
  echo ""
  echo "==> Stopping..."
  kill "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "==> Starting backend on http://127.0.0.1:8000"
(
  cd "${ROOT}/backend"
  uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
) &
BACKEND_PID=$!

echo "==> Starting frontend on http://127.0.0.1:5173"
(
  cd "${ROOT}/frontend"
  npm run dev -- --host 127.0.0.1 --port 5173
) &
FRONTEND_PID=$!

echo ""
echo "Open http://127.0.0.1:5173"
echo "API docs http://127.0.0.1:8000/docs"
echo "Conda env: ${ENV_NAME}"
wait
