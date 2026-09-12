#!/usr/bin/env bash
# ==============================================================================
# Offline Coding Agent Runner for any local project (Linux / macOS)
# ==============================================================================

set -eo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
DEFAULT_MODEL="${OLLAMA_MODEL:-qwen2.5-coder:7b}"
DEFAULT_WORKSPACE="${WORKSPACE_DIR:-${KIRMYA_PROJECT_PATH:-.}}"

# Workspace can be passed as the first positional argument
WORKSPACE="${1:-$DEFAULT_WORKSPACE}"
shift || true

MODEL="$DEFAULT_MODEL"

echo "=========================================================="
echo "  Starting Offline Coding Agent"
echo "=========================================================="
echo "Workspace: $WORKSPACE"
echo "Model:     $MODEL"
echo "Ollama:    $OLLAMA_HOST"
echo "----------------------------------------------------------"

# 1. Verify Ollama is reachable
echo "[1/4] Checking Ollama connectivity..."
if ! curl -s -f "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; then
    echo "ERROR: Ollama is not running or unreachable at ${OLLAMA_HOST}."
    echo "Please start Ollama in another terminal with: 'ollama serve'"
    exit 1
fi
echo "      Ollama service is up and running."

# 2. Check if model is pulled
echo "[2/4] Verifying model availability ($MODEL)..."
TAGS_JSON=$(curl -s "${OLLAMA_HOST}/api/tags")
if ! echo "$TAGS_JSON" | grep -q "\"${MODEL}\""; then
    echo "WARNING: Model '$MODEL' not found in local Ollama repository."
    echo "Attempting to pull model with: 'ollama pull $MODEL'..."
    if command -v ollama > /dev/null 2>&1; then
        ollama pull "$MODEL"
    else
        echo "ERROR: 'ollama' CLI not found on PATH to pull model automatically."
        echo "Please run: ollama pull $MODEL"
        exit 1
    fi
else
    echo "      Model '$MODEL' is locally available."
fi

# 3. Setup Python virtual environment
echo "[3/4] Preparing Python environment..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "      Creating virtual environment in $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
source "${VENV_DIR}/bin/activate"

# Ensure dependencies are installed
if [ -f "${SCRIPT_DIR}/requirements.txt" ]; then
    echo "      Checking/installing Python dependencies..."
    pip install -q -r "${SCRIPT_DIR}/requirements.txt"
fi

# 4. Launch agent
echo "[4/4] Launching Offline Coding Agent..."
python "${SCRIPT_DIR}/agent.py" --workspace "$WORKSPACE" --model "$MODEL" "$@"
