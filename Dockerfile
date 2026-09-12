# ==============================================================================
# Sandboxed Offline Coding Agent for kirmya_project
# ==============================================================================
FROM python:3.12-slim-bookworm

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install Git and Node.js (for TypeScript/React typecheck and test execution)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory for the agent code
WORKDIR /app

# Copy dependency specifications and install
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent implementation
COPY agent.py /app/
RUN chmod +x /app/agent.py

# Create mount point for the target workspace
RUN mkdir -p /workspace

# Set default environment variables
ENV WORKSPACE_DIR=/workspace
ENV KIRMYA_PROJECT_PATH=/workspace
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
ENV OLLAMA_MODEL=qwen2.5-coder:7b

# Entrypoint mounts the workspace and executes the agent
ENTRYPOINT ["python", "/app/agent.py", "--workspace", "/workspace"]

# ==============================================================================
# USAGE INSTRUCTIONS:
#
# 1. Build the sandboxed image:
#    docker build -t kirmya-coding-agent .
#
# 2. Run with Host Ollama Access (connecting to host machine Ollama):
#    docker run -it --rm \
#      --add-host=host.docker.internal:host-gateway \
#      -v "/path/to/kirmya_project:/workspace" \
#      kirmya-coding-agent
#
# 3. Fully Offline / Air-gapped Execution (Strict --network none):
#    docker run -it --rm \
#      --network none \
#      -v "/path/to/kirmya_project:/workspace" \
#      kirmya-coding-agent --help
# ==============================================================================
