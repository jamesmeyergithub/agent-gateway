#!/usr/bin/env bash
# ==============================================================================
# Google Cloud Agent Platform: Turnkey Deployment with Native Agent Gateway
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Resolve Python environment
PYTHON_BIN="python3"
if [ -n "${VIRTUAL_ENV:-}" ] && [ -f "${VIRTUAL_ENV}/bin/python" ]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [ -f "${ROOT_DIR}/.venv/bin/python" ]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
fi

echo "=================================================================="
echo "Google Cloud Agent Platform & Agent Gateway Turnkey Deployment"
echo "Using Python: ${PYTHON_BIN}"
echo "=================================================================="

# Ensure dependencies are available
"${PYTHON_BIN}" -c "import google.auth, certifi" 2>/dev/null || {
  echo "Installing required Python dependencies (google-auth, certifi)..."
  "${PYTHON_BIN}" -m pip install google-auth certifi requests httpx
}

# Execute deployment and verification automation
exec "${PYTHON_BIN}" "${SCRIPT_DIR}/deploy.py" "$@"
