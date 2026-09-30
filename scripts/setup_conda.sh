#!/usr/bin/env bash
# Create/update the project-local conda environment only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_NAME="${CONDA_ENV_NAME:-pressure-test}"

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
  echo "conda is required" >&2
  exit 1
fi

if conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "==> Updating conda env '${ENV_NAME}'"
  conda env update -f "${ROOT}/environment.yml" --prune
else
  echo "==> Creating conda env '${ENV_NAME}'"
  conda env create -f "${ROOT}/environment.yml"
fi

conda activate "${ENV_NAME}"
export PYTHONNOUSERSITE=1
python -m pip install -e "${ROOT}/backend"
echo "==> Ready. Activate with: conda activate ${ENV_NAME}"
echo "    Tip: export PYTHONNOUSERSITE=1 to keep ~/.local packages out."
