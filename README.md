# Offline Coding Agent for Any Local Project

A high-performance, 100% offline, self-contained AI coding agent that can work on any existing local repository. It detects common JavaScript/TypeScript, Python, Rust, Go, Java/Kotlin, and Ruby project layouts, then selects verification commands from project metadata. Powered by local LLMs through [Ollama](https://ollama.com/).

---

## Key Features

- **100% Air-Gapped & Offline**: No cloud APIs, no external telemetry, zero data egress.
- **Strict Path Traversal Guard**: Enforces strict boundaries around whichever workspace you provide. Any attempt to read or write files outside it (including directory traversal `../` and symlink escapes) is immediately blocked with a `SecurityViolationError`.
- **Pre-Flight Project Awareness**: Inspects project manifests, lockfiles, build scripts, and test runners on startup. Automatically configures suitable verification commands for the detected stack.
- **Strict Edit-and-Verify Workflow**:
  1. Inspect code without context explosion using windowed `read_file`.
  2. Make targeted modifications with `write_file`.
  3. Execute typecheck immediately (`run_terminal`).
  4. Execute affected unit tests (`run_terminal`).
  5. Run linter to maintain repository style standards.
  6. Perform mandatory `git status` and `git diff` audit upon completion.
- **Specialized Tool Suite**:
  - `read_file(path, start_line, end_line)`: Line-numbered inspection with auto-windowing for large files.
  - `write_file(path, content)`: Safe write with automatic directory tree creation.
  - `search_code(query, file_pattern)`: Fast regex/string search ignoring `node_modules`, `.git`, `dist`, etc.
  - `list_dir(path)`: Structured directory listing omitting noisy build artifacts.
  - `run_terminal(command)`: Sandboxed execution within the repository root with safety filters against destructive system commands.
  - `finish_task(summary)`: Concludes tasks and displays `git status` and `git diff` verification.

---

## File Structure

```
.
├── agent.py               # Core ReAct offline coding agent
├── requirements.txt       # Python dependencies (openai, requests, rich, pydantic)
├── run_agent.sh           # Linux/macOS launcher (verifies Ollama, venv, model)
├── run_agent.bat          # Windows launcher (verifies Ollama, venv, model)
├── Dockerfile             # Sandboxed offline execution environment (--network none)
├── tests/
│   └── test_agent.py      # Automated test suite (13 unit tests)
├── kirmya_project_demo/   # Reference TypeScript/React project for validation
└── README.md              # Documentation and operational manual
```

---

## Quickstart

### 1. Prerequisites
Ensure Ollama is installed and running locally:
```bash
# Start Ollama service (if not already running)
ollama serve

# Pull recommended coding model (7B or 14B)
ollama pull qwen2.5-coder:7b
# or for higher reasoning capacity:
# ollama pull qwen2.5-coder:14b
```

### 2. Running on Windows
Double-click `run_agent.bat` or run from PowerShell / Command Prompt:
```cmd
run_agent.bat "C:\path\to\your-project"
```
Or set the environment variable:
```cmd
set WORKSPACE_DIR=C:\path\to\your-project
run_agent.bat
```

### 3. Running on Linux / macOS
Make the script executable and run:
```bash
chmod +x run_agent.sh
./run_agent.sh /path/to/your-project
```

### 4. Running Directly with Python
```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install requirements
pip install -r requirements.txt

# Run interactive session
python agent.py --workspace /path/to/your-project --model qwen2.5-coder:7b

# Run a single task non-interactively
python agent.py --workspace /path/to/your-project --task "Fix the button toggle handler and run tests"
```

---

## Sandboxed Docker Execution

For complete isolation with network disabled (`--network none`):

```bash
# 1. Build the sandboxed container image
docker build -t kirmya-coding-agent .

# 2. Run with Host Ollama connection:
docker run -it --rm \
  --add-host=host.docker.internal:host-gateway \
  -v "/path/to/your-project:/workspace" \
  kirmya-coding-agent

# 3. Completely Air-Gapped execution (network disabled):
docker run -it --rm \
  --network none \
  -v "/path/to/your-project:/workspace" \
  kirmya-coding-agent --help
```

---

## Verification & Automated Testing

Run the included unit test suite to verify the security guards, tools, and project detector:

```bash
python -m unittest tests/test_agent.py
```

All 13 tests validate:
- Rejection of path traversal attempts (`../`, `../../../../etc/passwd`, external absolute paths).
- Line-slice reading and large file protection.
- Safe file creation and directory resolution.
- Code search filtering out `node_modules` and `.git`.
- Terminal command safety filtering.
- Automatic TypeScript/React project detection.
