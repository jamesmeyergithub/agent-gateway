#!/usr/bin/env bash
# ==============================================================================
# Google Cloud Agent Platform: Turnkey Deployment with Native Agent Gateway
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Resolve Python environment
PYTHON_BIN="python3"
if [ -f "${ROOT_DIR}/.venv/bin/python" ]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif [ -f "/Users/jamesmeyer/gcp-docs-agent/.venv/bin/python" ]; then
  PYTHON_BIN="/Users/jamesmeyer/gcp-docs-agent/.venv/bin/python"
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
