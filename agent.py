#!/usr/bin/env python3
"""
Offline Coding Agent tailored for 'kirmya_project'
Powered by Ollama and local LLMs (e.g., qwen2.5-coder:7b / qwen2.5-coder:14b).

Features:
- 100% Offline ReAct agent communicating with local Ollama API
- Strict Path Traversal Guard preventing file access outside the target workspace
- Flexible CLI: accepts workspace as an optional positional argument or via -w/--workspace
- Resolves workspace to absolute path (os.path.abspath) and validates existence
- Specialized Tools: read_file, write_file, search_code, list_dir, run_terminal,
  run_typecheck, run_unit_tests, run_linter, inspect_package_json, finish_task
- Pre-flight Project Awareness check for TypeScript/React, scripts, and dependencies
- Strict Edit-and-Verify workflow (edit -> typecheck -> test -> lint -> diff audit)
- End-of-task Git status and diff verification
"""

import os
import sys
import json
import re
import fnmatch
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union

# Optional rich formatting with graceful fallback
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.syntax import Syntax
    from rich.markdown import Markdown
    from rich.text import Text
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    console = None

# Optional OpenAI client with graceful standard library fallback
try:
    from openai import OpenAI
    HAS_OPENAI_LIB = True
except ImportError:
    HAS_OPENAI_LIB = False
    OpenAI = None

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ============================================================================
# Console Output Helper
# ============================================================================

def print_banner(text: str, style: str = "bold cyan") -> None:
    if HAS_RICH and console:
        console.print(Panel(f"[{style}]{text}[/{style}]", border_style="cyan", expand=False))
    else:
        border = "=" * (len(text) + 4)
        print(f"\n{border}\n  {text}\n{border}\n")


def print_step(title: str, content: str, style: str = "green") -> None:
    if HAS_RICH and console:
        console.print(Panel(content, title=f"[{style}]{title}[/{style}]", border_style=style))
    else:
        print(f"\n--- {title} ---")
        print(content)
        print("------------------\n")


def print_error(text: str) -> None:
    if HAS_RICH and console:
        console.print(f"[bold red]ERROR:[/bold red] {text}")
    else:
        print(f"ERROR: {text}", file=sys.stderr)


def print_info(text: str) -> None:
    if HAS_RICH and console:
        console.print(f"[bold blue]INFO:[/bold blue] {text}")
    else:
        print(f"INFO: {text}")


# ============================================================================
# Security Guard & Path Traversal Protection
# ============================================================================

class SecurityViolationError(Exception):
    """Raised when an operation attempts to access or mutate files outside workspace."""
    pass


class WorkspaceGuard:
    """Strictly enforces workspace boundaries to prevent directory traversal attacks."""

    IGNORE_DIRS = {
        '.git', 'node_modules', '__pycache__', '.next', '.nuxt',
        '.turbo', '.cache', 'coverage', '.venv', 'venv', 'dist', 'build'
    }

    def __init__(self, workspace_path: Union[str, Path]):
        abs_path = os.path.abspath(str(workspace_path))
        self.workspace_root = Path(abs_path).resolve()
        if not self.workspace_root.exists():
            raise FileNotFoundError(f"Workspace directory not found: {self.workspace_root}")
        if not self.workspace_root.is_dir():
            raise NotADirectoryError(f"Workspace path is not a directory: {self.workspace_root}")

    def resolve_safe_path(self, target_path: Union[str, Path]) -> Path:
        """
        Resolves a target path and ensures it lies strictly inside workspace_root.
        Resolves symlinks to avoid symlink escape attacks.
        """
        path_obj = Path(target_path)
        if not path_obj.is_absolute():
            resolved = (self.workspace_root / path_obj).resolve()
        else:
            resolved = path_obj.resolve()

        try:
            # Raises ValueError if resolved is not a subpath of workspace_root
            resolved.relative_to(self.workspace_root)
        except ValueError:
            raise SecurityViolationError(
                f"Path Traversal Blocked: Target path '{target_path}' resolves to "
                f"'{resolved}', which is outside the workspace root '{self.workspace_root}'."
            )

        return resolved

    def get_rel_path(self, path: Union[str, Path]) -> str:
        safe_path = self.resolve_safe_path(path)
        return safe_path.relative_to(self.workspace_root).as_posix()


# ============================================================================
# Project Awareness & Diagnostic Engine
# ============================================================================

class ProjectDetector:
    """Inspects kirmya_project to identify language, frameworks, test runners, and scripts."""

    def __init__(self, guard: WorkspaceGuard):
        self.guard = guard
        self.root = guard.workspace_root

    def detect(self) -> Dict[str, Any]:
        info = {
            "name": self.root.name,
            "path": str(self.root),
            "is_git": (self.root / ".git").is_dir(),
            "type": "Unknown",
            "frameworks": [],
            "package_manager": "npm",
            "scripts": {},
            "key_files": [],
            "typecheck_cmd": "npx tsc --noEmit",
            "test_cmd": "npm test",
            "lint_cmd": "npm run lint",
        }

        # Check key configuration files
        configs = [
            "package.json", "tsconfig.json", "requirements.txt",
            "pyproject.toml", "Cargo.toml", "pom.xml", "vite.config.ts",
            "next.config.js", "next.config.mjs", "webpack.config.js"
        ]
        for cfg in configs:
            if (self.root / cfg).is_file():
                info["key_files"].append(cfg)

        # Detect package managers
        if (self.root / "pnpm-lock.yaml").is_file():
            info["package_manager"] = "pnpm"
        elif (self.root / "yarn.lock").is_file():
            info["package_manager"] = "yarn"
        elif (self.root / "package-lock.json").is_file():
            info["package_manager"] = "npm"

        pm = info["package_manager"]

        # Inspect package.json
        pkg_json_path = self.root / "package.json"
        if pkg_json_path.is_file():
            try:
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    pkg_data = json.load(f)

                info["name"] = pkg_data.get("name", info["name"])
                scripts = pkg_data.get("scripts", {})
                info["scripts"] = scripts

                deps = {
                    **pkg_data.get("dependencies", {}),
                    **pkg_data.get("devDependencies", {})
                }

                frameworks = []
                is_ts = "typescript" in deps or (self.root / "tsconfig.json").is_file()
                if "react" in deps:
                    frameworks.append("React")
                if "next" in deps:
                    frameworks.append("Next.js")
                if "vite" in deps:
                    frameworks.append("Vite")

                test_runner = None
                if "jest" in deps:
                    test_runner = "Jest"
                elif "vitest" in deps:
                    test_runner = "Vitest"
                elif "mocha" in deps:
                    test_runner = "Mocha"

                if is_ts:
                    info["type"] = "TypeScript/React" if "React" in frameworks else "TypeScript"
                elif "React" in frameworks:
                    info["type"] = "JavaScript/React"
                else:
                    info["type"] = "Node.js / JavaScript"

                info["frameworks"] = frameworks
                if test_runner:
                    info["frameworks"].append(f"Test Runner: {test_runner}")

                # Configure optimal commands based on package.json scripts
                if "typecheck" in scripts:
                    info["typecheck_cmd"] = f"{pm} run typecheck"
                elif is_ts:
                    info["typecheck_cmd"] = "npx tsc --noEmit"

                if "test" in scripts:
                    info["test_cmd"] = f"{pm} test"
                elif test_runner == "vitest":
                    info["test_cmd"] = "npx vitest run"
                elif test_runner == "jest":
                    info["test_cmd"] = "npx jest"

                if "lint" in scripts:
                    info["lint_cmd"] = f"{pm} run lint"
                elif "eslint" in deps:
                    info["lint_cmd"] = "npx eslint ."

            except Exception as e:
                info["parsing_error"] = str(e)

        return info

    def display_diagnostic(self, info: Dict[str, Any]) -> None:
        """Renders the pre-flight check in a clear dashboard."""
        if HAS_RICH and console:
            table = Table(title="[bold green]Project Awareness Diagnostic[/bold green]", show_header=True)
            table.add_column("Property", style="cyan", no_wrap=True)
            table.add_column("Detected Value", style="white")

            table.add_row("Repository", info["name"])
            table.add_row("Root Directory", info["path"])
            table.add_row("Project Stack", info["type"])
            table.add_row("Frameworks & Tools", ", ".join(info["frameworks"]) or "None detected")
            table.add_row("Package Manager", info["package_manager"])
            table.add_row("Typecheck Command", f"`{info['typecheck_cmd']}`")
            table.add_row("Test Command", f"`{info['test_cmd']}`")
            table.add_row("Linter Command", f"`{info['lint_cmd']}`")
            table.add_row("Git Initialized", "[green]Yes[/green]" if info["is_git"] else "[yellow]No[/yellow]")
            console.print(table)
        else:
            print("\n=== Project Awareness Diagnostic ===")
            print(f"Repository:        {info['name']}")
            print(f"Root Directory:    {info['path']}")
            print(f"Project Stack:     {info['type']}")
            print(f"Frameworks:        {', '.join(info['frameworks']) or 'None'}")
            print(f"Package Manager:   {info['package_manager']}")
            print(f"Typecheck Command: {info['typecheck_cmd']}")
            print(f"Test Command:      {info['test_cmd']}")
            print(f"Linter Command:    {info['lint_cmd']}")
            print(f"Git Initialized:   {'Yes' if info['is_git'] else 'No'}")
            print("====================================\n")


# ============================================================================
# Specialized Tool Suite
# ============================================================================

class ToolSuite:
    """Specialized coding tools operating strictly within the protected workspace."""

    def __init__(self, guard: WorkspaceGuard, project_info: Optional[Dict[str, Any]] = None):
        self.guard = guard
        self.workspace_root = guard.workspace_root
        self.project_info = project_info or {}

    def read_file(self, path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
        """
        Reads contents of a file within the workspace with line numbers.
        Protects the context window by paging large files when no line range is provided.
        """
        try:
            target = self.guard.resolve_safe_path(path)
            if not target.exists():
                return f"Error: File '{path}' does not exist."
            if not target.is_file():
                return f"Error: Path '{path}' is not a regular file."

            # Read with UTF-8, handling binary gracefully
            try:
                with open(target, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()
            except Exception as e:
                return f"Error reading file '{path}': {str(e)}"

            total_lines = len(lines)
            if total_lines == 0:
                return f"[File '{self.guard.get_rel_path(target)}' is empty (0 lines)]"

            # Validate and slice lines
            if start_line is not None or end_line is not None:
                s = max(1, start_line if start_line is not None else 1)
                e = min(total_lines, end_line if end_line is not None else total_lines)
                if s > total_lines:
                    return f"Error: start_line ({s}) exceeds total lines ({total_lines})."
                if s > e:
                    return f"Error: start_line ({s}) cannot be greater than end_line ({e})."

                selected_lines = lines[s - 1:e]
                output = [f"{idx:4d} | {line}" for idx, line in enumerate(selected_lines, start=s)]
                header = f"=== File: {self.guard.get_rel_path(target)} (lines {s}-{e} of {total_lines}) ==="
                return f"{header}\n" + "\n".join(output)

            # Auto-windowing for large files to avoid blowing the context window
            MAX_INITIAL_LINES = 300
            if total_lines > MAX_INITIAL_LINES:
                output = [f"{idx:4d} | {line}" for idx, line in enumerate(lines[:MAX_INITIAL_LINES], start=1)]
                notice = (
                    f"\n[Notice: File has {total_lines} lines. Showing first {MAX_INITIAL_LINES} lines "
                    f"to conserve context. Call read_file with start_line and end_line to view remaining lines.]"
                )
                header = f"=== File: {self.guard.get_rel_path(target)} (lines 1-{MAX_INITIAL_LINES} of {total_lines}) ==="
                return f"{header}\n" + "\n".join(output) + notice
            else:
                output = [f"{idx:4d} | {line}" for idx, line in enumerate(lines, start=1)]
                header = f"=== File: {self.guard.get_rel_path(target)} (all {total_lines} lines) ==="
                return f"{header}\n" + "\n".join(output)

        except SecurityViolationError as sec_err:
            return f"Security Error: {str(sec_err)}"
        except Exception as e:
            return f"Error: {str(e)}"

    def write_file(self, path: str, content: str) -> str:
        """Overwrites or creates a file within the workspace, automatically creating parent folders."""
        try:
            target = self.guard.resolve_safe_path(path)
            # Ensure parent directories exist
            target.parent.mkdir(parents=True, exist_ok=True)

            with open(target, "w", encoding="utf-8") as f:
                f.write(content)

            lines = len(content.splitlines())
            size_bytes = len(content.encode("utf-8"))
            rel_path = self.guard.get_rel_path(target)
            return f"Success: Wrote {lines} lines ({size_bytes} bytes) to '{rel_path}'."

        except SecurityViolationError as sec_err:
            return f"Security Error: {str(sec_err)}"
        except Exception as e:
            return f"Error writing file '{path}': {str(e)}"

    def search_code(self, query: str, file_pattern: Optional[str] = None) -> str:
        """
        Recursively searches the workspace for query/regex.
        Ignores .git, node_modules, dist, and build directories.
        """
        try:
            results = []
            max_matches = 50
            query_lower = query.lower()

            # Compile regex pattern if query appears to be regex, otherwise literal
            is_regex = False
            regex = None
            if any(char in query for char in r"[](){}^$+?*|\\"):
                try:
                    regex = re.compile(query, re.IGNORECASE)
                    is_regex = True
                except re.error:
                    pass

            for root, dirs, files in os.walk(self.workspace_root):
                # Prune ignored directories in-place
                dirs[:] = [d for d in dirs if d not in WorkspaceGuard.IGNORE_DIRS]

                for file in files:
                    if file_pattern and not fnmatch.fnmatch(file, file_pattern):
                        continue

                    full_path = Path(root) / file
                    try:
                        rel_path = full_path.relative_to(self.workspace_root).as_posix()
                    except ValueError:
                        continue

                    # Read file lines
                    try:
                        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                            for line_idx, line in enumerate(f, start=1):
                                matched = False
                                if is_regex and regex:
                                    matched = bool(regex.search(line))
                                else:
                                    matched = query_lower in line.lower()

                                if matched:
                                    snippet = line.rstrip()
                                    results.append(f"{rel_path}:{line_idx}: {snippet}")
                                    if len(results) >= max_matches:
                                        break
                    except Exception:
                        continue

                    if len(results) >= max_matches:
                        break
                if len(results) >= max_matches:
                    break

            if not results:
                return f"No matches found for query '{query}'."

            count_msg = f"Found {len(results)} match(es)" + (" (capped at 50)" if len(results) == max_matches else "")
            return f"=== Search Results for '{query}' ({count_msg}) ===\n" + "\n".join(results)

        except Exception as e:
            return f"Error during search: {str(e)}"

    def list_dir(self, path: str = ".") -> str:
        """Lists files and directories cleanly, omitting build artifacts and node_modules."""
        try:
            target = self.guard.resolve_safe_path(path)
            if not target.exists():
                return f"Error: Directory '{path}' does not exist."
            if not target.is_dir():
                return f"Error: Path '{path}' is a file, not a directory."

            entries = []
            for item in sorted(target.iterdir()):
                if item.name in WorkspaceGuard.IGNORE_DIRS:
                    continue
                if item.is_dir():
                    entries.append(f"[DIR]  {item.name}/")
                else:
                    try:
                        size = item.stat().st_size
                        if size < 1024:
                            size_str = f"{size} B"
                        elif size < 1024 * 1024:
                            size_str = f"{size / 1024:.1f} KB"
                        else:
                            size_str = f"{size / (1024 * 1024):.1f} MB"
                    except Exception:
                        size_str = "unknown"
                    entries.append(f"[FILE] {item.name:<30} ({size_str})")

            rel_path = self.guard.get_rel_path(target)
            display_path = rel_path if rel_path != "." else self.workspace_root.name
            if not entries:
                return f"Directory '{display_path}' is empty."

            return f"=== Directory Listing: {display_path} ===\n" + "\n".join(entries)

        except SecurityViolationError as sec_err:
            return f"Security Error: {str(sec_err)}"
        except Exception as e:
            return f"Error listing directory '{path}': {str(e)}"

    def run_terminal(self, command: str) -> str:
        """
        Executes terminal commands (npm test, git, build, typecheck) strictly inside the workspace.
        Enforces execution timeout and flags potentially destructive system-level commands.
        """
        dangerous_patterns = [
            r"\brm\s+-(?:[a-zA-Z]*[rf][a-zA-Z]*)\s+(?:/|[a-zA-Z]:[\\/])?",
            r"\brm\s+-rf\b",
            r"\bmkfs\b",
            r"\bdd\s+if=",
            r":\(\)\{\s*:\|\:&\s*\};:",
            r"\bformat\s+[A-Za-z]:",
            r"\bdel\s+/[sfq]\s+[a-zA-Z]:[\\/]",
            r"\brmdir\s+/[sq]\s+[a-zA-Z]:[\\/]"
        ]
        for pat in dangerous_patterns:
            if re.search(pat, command, re.IGNORECASE):
                return f"Security Error: Command blocked by safety filter: '{command}'"

        try:
            print_info(f"Running terminal command in {self.workspace_root.name}: `{command}`")
            proc = subprocess.run(
                command,
                cwd=str(self.workspace_root),
                shell=True,
                text=True,
                capture_output=True,
                timeout=120
            )

            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            exit_code = proc.returncode

            output = [f"Exit Code: {exit_code}"]
            if stdout:
                output.append(f"STDOUT:\n{stdout}")
            if stderr:
                output.append(f"STDERR:\n{stderr}")
            if not stdout and not stderr:
                output.append("(No output produced)")

            return "\n\n".join(output)

        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after 120 seconds: '{command}'"
        except Exception as e:
            return f"Error running command '{command}': {str(e)}"

    def run_typecheck(self) -> str:
        """Runs the repository typecheck command (e.g. npm run typecheck or npx tsc --noEmit)."""
        cmd = self.project_info.get("typecheck_cmd", "npx tsc --noEmit")
        print_info(f"Executing Typecheck: {cmd}")
        return self.run_terminal(cmd)

    def run_unit_tests(self, test_file: Optional[str] = None) -> str:
        """Runs unit tests, optionally targeting an affected test file."""
        base_cmd = self.project_info.get("test_cmd", "npm test")
        if test_file:
            safe_target = self.guard.get_rel_path(test_file)
            cmd = f"{base_cmd} -- {safe_target}"
        else:
            cmd = base_cmd
        print_info(f"Executing Unit Tests: {cmd}")
        return self.run_terminal(cmd)

    def run_linter(self) -> str:
        """Runs the repository linter command (e.g. npm run lint)."""
        cmd = self.project_info.get("lint_cmd", "npm run lint")
        print_info(f"Executing Linter: {cmd}")
        return self.run_terminal(cmd)

    def inspect_package_json(self) -> str:
        """Reads and parses package.json inside the target workspace."""
        pkg_path = self.workspace_root / "package.json"
        if not pkg_path.is_file():
            return "package.json not found in target workspace."
        try:
            with open(pkg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            formatted = {
                "name": data.get("name"),
                "version": data.get("version"),
                "scripts": data.get("scripts", {}),
                "dependencies": list(data.get("dependencies", {}).keys()),
                "devDependencies": list(data.get("devDependencies", {}).keys())
            }
            return json.dumps(formatted, indent=2)
        except Exception as e:
            return f"Error inspecting package.json: {str(e)}"

    def finish_task(self, summary: str) -> str:
        """
        Concludes the current task and performs a strict git status and diff audit
        to verify modifications before completing.
        """
        audit_output = []
        audit_output.append(f"Task Summary: {summary}")
        audit_output.append("\n=== Safety Audit: Repository Modifications ===")

        # Run git status
        try:
            status_proc = subprocess.run(
                ["git", "status", "--short"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=30
            )
            git_status = status_proc.stdout.strip()
            if git_status:
                audit_output.append(f"\n[Git Status (Modified/Untracked Files)]:\n{git_status}")
            else:
                audit_output.append("\n[Git Status]: Working tree clean (no uncommitted changes).")
        except Exception as e:
            audit_output.append(f"\n[Git Status Failed]: {str(e)}")

        # Run git diff
        try:
            diff_proc = subprocess.run(
                ["git", "diff"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=30
            )
            git_diff = diff_proc.stdout.strip()
            if git_diff:
                # Limit diff output if massive
                if len(git_diff.splitlines()) > 200:
                    truncated = "\n".join(git_diff.splitlines()[:200])
                    audit_output.append(f"\n[Git Diff (Truncated to first 200 lines)]:\n{truncated}\n... (diff truncated)")
                else:
                    audit_output.append(f"\n[Git Diff]:\n{git_diff}")
            else:
                audit_output.append("\n[Git Diff]: No tracked line changes.")
        except Exception as e:
            audit_output.append(f"\n[Git Diff Failed]: {str(e)}")

        return "\n".join(audit_output)


# ============================================================================
# OpenAI-Compatible Tool Schema Definitions
# ============================================================================

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents with line numbers. Supports start_line and end_line for range inspection to preserve context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to file relative to workspace root."
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "1-indexed starting line number (optional)."
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "1-indexed ending line number (optional)."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file within the workspace. Automatically creates missing parent directories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to file relative to workspace root."
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete text content to write into the file."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search code across workspace files for a text string or regular expression. Ignores .git and node_modules.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Literal text or regex pattern to search for."
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "Optional glob filter (e.g., '*.tsx', '*.ts', 'package.json')."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and subdirectories within a directory path. Omits node_modules and .git.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to workspace root (defaults to '.')."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_terminal",
            "description": "Execute a terminal command (e.g., npm test, npx tsc --noEmit, git status) strictly inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command line to execute inside the workspace."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_typecheck",
            "description": "Run the project's detected typecheck command (e.g., npm run typecheck or npx tsc --noEmit). Call immediately after editing files.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_unit_tests",
            "description": "Run the project's unit test runner, optionally specifying the affected test file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_file": {
                        "type": "string",
                        "description": "Optional relative path to specific test file to run."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_linter",
            "description": "Run the repository linter command (e.g. npm run lint or npx eslint .).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_package_json",
            "description": "Inspect package.json to view dependencies, scripts, and package information.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "finish_task",
            "description": "Conclude the task. Triggers the mandatory git status and git diff safety audit before finalizing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Detailed summary of the changes made and verification steps completed."
                    }
                },
                "required": ["summary"]
            }
        }
    }
]


# ============================================================================
# Offline HTTP Client for Ollama
# ============================================================================

class OllamaClient:
    """Communicates with Ollama's local OpenAI-compatible API endpoint."""

    def __init__(self, base_url: str = "http://localhost:11434/v1", timeout: int = 600):
        self.base_url = base_url.rstrip("/")
        self.raw_ollama_url = base_url.replace("/v1", "")
        self.timeout = timeout

        if HAS_OPENAI_LIB:
            self.client = OpenAI(base_url=self.base_url, api_key="ollama", timeout=self.timeout)
        else:
            self.client = None

    def check_connection(self) -> Tuple[bool, str]:
        """Checks whether the local Ollama instance is online and responding."""
        tags_url = f"{self.raw_ollama_url}/api/tags"
        try:
            if HAS_REQUESTS:
                resp = requests.get(tags_url, timeout=10)
                if resp.status_code == 200:
                    return True, "Connected"
            else:
                import urllib.request
                req = urllib.request.Request(tags_url)
                with urllib.request.urlopen(req, timeout=10) as r:
                    if r.status == 200:
                        return True, "Connected"
            return False, "Ollama returned non-200 status code"
        except Exception as e:
            return False, f"Cannot reach Ollama at {tags_url}: {str(e)}"

    def list_models(self) -> List[str]:
        """Fetches list of pulled models from Ollama."""
        tags_url = f"{self.raw_ollama_url}/api/tags"
        try:
            if HAS_REQUESTS:
                resp = requests.get(tags_url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    return [m.get("name", "") for m in data.get("models", [])]
            else:
                import urllib.request
                req = urllib.request.Request(tags_url)
                with urllib.request.urlopen(req, timeout=10) as r:
                    if r.status == 200:
                        data = json.loads(r.read().decode("utf-8"))
                        return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def chat_completion(self, model: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Sends chat completion request with tool calling."""
        if HAS_OPENAI_LIB and self.client:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.2,
                timeout=self.timeout
            )
            msg = response.choices[0].message
            # Convert to dict format
            tool_calls = []
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })

            return {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": tool_calls
            }
        else:
            # Fallback HTTP via requests or urllib
            payload = {
                "model": model,
                "messages": messages,
                "tools": tools,
                "stream": False,
                "temperature": 0.2
            }
            url = f"{self.base_url}/chat/completions"
            data_bytes = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json", "Authorization": "Bearer ollama"}

            if HAS_REQUESTS:
                resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
                res_json = resp.json()
            else:
                import urllib.request
                req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    res_json = json.loads(r.read().decode("utf-8"))

            choice = res_json["choices"][0]["message"]
            return {
                "role": "assistant",
                "content": choice.get("content", ""),
                "tool_calls": choice.get("tool_calls", [])
            }


# ============================================================================
# ReAct Agent Core Loop
# ============================================================================

class OfflineCodingAgent:
    """Orchestrates ReAct cycles, tool execution, and the strict edit-verify workflow."""

    def __init__(self, workspace_path: str, model_name: str = "qwen2.5-coder:7b", base_url: str = "http://localhost:11434/v1", timeout: int = 600):
        # Resolve to absolute path
        abs_workspace = os.path.abspath(workspace_path)
        self.guard = WorkspaceGuard(abs_workspace)
        self.detector = ProjectDetector(self.guard)
        self.project_info = self.detector.detect()
        # Propagate resolved workspace and project metadata to tools
        self.tools = ToolSuite(self.guard, self.project_info)
        self.model_name = model_name
        self.client = OllamaClient(base_url, timeout=timeout)
        self.system_prompt = self._build_system_prompt()
        self.conversation_history: List[Dict[str, Any]] = []

    def _build_system_prompt(self) -> str:
        p = self.project_info
        frameworks_str = ", ".join(p["frameworks"]) or "TypeScript/React"

        return f"""You are an expert offline coding assistant working on '{p['name']}'.
Workspace Root: {p['path']}
Project Type: {p['type']} ({frameworks_str})
Package Manager: {p['package_manager']}

Repository Conventions and Available Verification Commands:
- Typecheck: `{p['typecheck_cmd']}` (or call tool `run_typecheck`)
- Unit Tests: `{p['test_cmd']}` (or call tool `run_unit_tests`)
- Linter:     `{p['lint_cmd']}` (or call tool `run_linter`)

STRICT EDIT-AND-VERIFY WORKFLOW:
1. Make targeted file changes using `read_file` and `write_file`.
2. Immediately call `run_typecheck` (or `run_terminal('{p['typecheck_cmd']}')) to verify types. If type errors occur, resolve them first.
3. Call `run_unit_tests` on affected files (or `run_terminal('{p['test_cmd']}')) to verify behavior.
4. Call `run_linter` (or `run_terminal('{p['lint_cmd']}')) before concluding to ensure repository style standards.
5. Do not conclude the task until BOTH typecheck and unit tests pass cleanly.
6. Call `finish_task` with a clear summary when complete. This automatically triggers a `git status` and `git diff` audit.

SECURITY CONSTRAINT:
You are strictly confined to '{p['path']}'. Never attempt to read or write paths outside this directory.
Always inspect code before editing. Keep diffs focused and minimal.
"""

    def execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Dispatches tool call to appropriate ToolSuite method."""
        if name == "read_file":
            return self.tools.read_file(
                path=args.get("path", ""),
                start_line=args.get("start_line"),
                end_line=args.get("end_line")
            )
        elif name == "write_file":
            return self.tools.write_file(
                path=args.get("path", ""),
                content=args.get("content", "")
            )
        elif name == "search_code":
            return self.tools.search_code(
                query=args.get("query", ""),
                file_pattern=args.get("file_pattern")
            )
        elif name == "list_dir":
            return self.tools.list_dir(
                path=args.get("path", ".")
            )
        elif name == "run_terminal":
            return self.tools.run_terminal(
                command=args.get("command", "")
            )
        elif name == "run_typecheck":
            return self.tools.run_typecheck()
        elif name == "run_unit_tests":
            return self.tools.run_unit_tests(
                test_file=args.get("test_file")
            )
        elif name == "run_linter":
            return self.tools.run_linter()
        elif name == "inspect_package_json":
            return self.tools.inspect_package_json()
        elif name == "finish_task":
            return self.tools.finish_task(
                summary=args.get("summary", "")
            )
        else:
            return f"Error: Unknown tool '{name}'"

    def run_task(self, user_prompt: str, max_iterations: int = 30) -> None:
        """Executes a complete ReAct loop for the requested user prompt."""
        print_banner(f"Task: {user_prompt}", style="bold yellow")

        # Initialize conversation with system prompt if empty
        if not self.conversation_history:
            self.conversation_history.append({
                "role": "system",
                "content": self.system_prompt
            })

        self.conversation_history.append({
            "role": "user",
            "content": user_prompt
        })

        iteration = 0
        task_finished = False

        while iteration < max_iterations and not task_finished:
            iteration += 1
            print_info(f"ReAct Iteration {iteration}/{max_iterations}")

            try:
                if HAS_RICH and console:
                    with console.status(
                        f"[bold yellow]Thinking with {self.model_name}... (local CPU/GPU inference in progress, please wait)[/bold yellow]",
                        spinner="dots"
                    ):
                        response = self.client.chat_completion(
                            model=self.model_name,
                            messages=self.conversation_history,
                            tools=TOOL_SCHEMAS
                        )
                else:
                    print_info(f"Thinking with {self.model_name}... (local inference in progress, please wait)")
                    response = self.client.chat_completion(
                        model=self.model_name,
                        messages=self.conversation_history,
                        tools=TOOL_SCHEMAS
                    )
            except Exception as e:
                print_error(f"Inference error with model '{self.model_name}': {str(e)}")
                break

            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])

            # Append assistant message to history
            self.conversation_history.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls if tool_calls else None
            })

            # Print thoughts if available
            if content:
                print_step("Agent Reasoning", content, style="magenta")

            # Check if there are tool calls to execute
            if not tool_calls:
                # Check for textual ReAct fallback if model generated plain text action
                fallback_call = self._parse_textual_tool_call(content)
                if fallback_call:
                    tool_calls = [fallback_call]
                else:
                    print_info("No further actions requested by agent.")
                    break

            for tc in tool_calls:
                call_id = tc.get("id", f"call_{iteration}")
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")

                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {"raw": raw_args}
                else:
                    args = raw_args

                print_step(f"Tool Invocation: {tool_name}", json.dumps(args, indent=2), style="cyan")

                # Execute tool
                result = self.execute_tool(tool_name, args)

                # Show preview of result
                display_result = result
                if len(result.splitlines()) > 25:
                    display_result = "\n".join(result.splitlines()[:25]) + f"\n... [Result truncated: {len(result.splitlines())} lines total]"
                print_step(f"Observation: {tool_name}", display_result, style="blue")

                # Record tool result in conversation history
                self.conversation_history.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": result
                })

                if tool_name == "finish_task":
                    task_finished = True
                    print_banner("Task Completed & Safety Audit Verified", style="bold green")
                    print(result)
                    break

        if iteration >= max_iterations:
            print_error(f"Reached maximum iterations ({max_iterations}) without task completion.")

    def _parse_textual_tool_call(self, text: str) -> Optional[Dict[str, Any]]:
        """Fallback parser for models outputting JSON or ReAct text actions."""
        # Check for JSON block in markdown: ```json { "tool": "...", "args": {...} } ```
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if "name" in data and ("parameters" in data or "arguments" in data):
                    name = data["name"]
                    args = data.get("parameters") or data.get("arguments", {})
                    return {
                        "id": "text_fallback",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)}
                    }
            except Exception:
                pass

        # Check for Action: tool_name \n Action Input: {...}
        action_match = re.search(r"Action:\s*([a-zA-Z0-9_]+)\s*\nAction Input:\s*(\{.*?\})", text, re.DOTALL)
        if action_match:
            try:
                name = action_match.group(1).strip()
                args_str = action_match.group(2).strip()
                return {
                    "id": "text_react_fallback",
                    "type": "function",
                    "function": {"name": name, "arguments": args_str}
                }
            except Exception:
                pass

        return None


# ============================================================================
# Main Entry Point & CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Self-contained Offline Coding Agent for kirmya_project using Ollama."
    )
    # Positional workspace argument (nargs="*") so any unflagged path is captured
    parser.add_argument(
        "workspace",
        nargs="*",
        default=[],
        help="Target workspace directory (optional positional argument)."
    )
    # Optional -w / --workspace flag
    parser.add_argument(
        "-w", "--workspace-flag", "--workspace",
        dest="workspace_flag",
        default=None,
        help="Target workspace directory (takes precedence over positional argument)."
    )
    parser.add_argument(
        "-m", "--model",
        default=os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
        help="Ollama model name (default: 'qwen2.5-coder:7b', or 'qwen2.5-coder:14b')."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        help="Ollama OpenAI-compatible API base URL (default: 'http://localhost:11434/v1')."
    )
    parser.add_argument(
        "--task",
        default=None,
        help="Single task prompt to execute immediately."
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=30,
        help="Maximum ReAct iterations per task (default: 30)."
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Inference timeout in seconds (default: 600)."
    )

    args = parser.parse_args()

    # Determine raw workspace path from flag, positional, environment, or default fallback
    raw_workspace = None
    if args.workspace_flag:
        raw_workspace = args.workspace_flag
    elif args.workspace:
        raw_workspace = args.workspace[0]
    else:
        raw_workspace = os.environ.get("KIRMYA_PROJECT_PATH", os.environ.get("WORKSPACE_DIR"))

    # Fallback to demo or current directory if not specified
    if not raw_workspace:
        if os.path.isdir("./kirmya_project"):
            raw_workspace = "./kirmya_project"
        elif os.path.isdir("./kirmya_project_demo"):
            raw_workspace = "./kirmya_project_demo"
        else:
            raw_workspace = "."

    # Requirement 2: Resolve workspace to absolute path and validate existence
    workspace_abs = os.path.abspath(raw_workspace)
    if not os.path.exists(workspace_abs):
        print_error(f"Target workspace directory does not exist: {workspace_abs}")
        sys.exit(1)
    if not os.path.isdir(workspace_abs):
        print_error(f"Target workspace path is not a directory: {workspace_abs}")
        sys.exit(1)

    print_banner("OLLAMA OFFLINE CODING AGENT FOR KIRMYA_PROJECT")

    # Initialize agent (Requirement 3: workspace dynamically propagated into all tools and guards)
    try:
        agent = OfflineCodingAgent(
            workspace_path=workspace_abs,
            model_name=args.model,
            base_url=args.base_url,
            timeout=args.timeout
        )
    except Exception as e:
        print_error(f"Initialization failure: {str(e)}")
        sys.exit(1)

    # Run Project Awareness Diagnostic
    agent.detector.display_diagnostic(agent.project_info)

    # Check Ollama connectivity
    print_info(f"Checking Ollama status at {args.base_url}...")
    connected, conn_msg = agent.client.check_connection()
    if not connected:
        print_error(f"Cannot communicate with Ollama: {conn_msg}")
        print_info("Make sure Ollama is running (`ollama serve`) and accessible at http://localhost:11434.")
        print_info("For mock or dry-run testing, check 'tests/test_agent.py'.")
    else:
        print_info(f"Ollama connected successfully. Checking model '{args.model}'...")
        models = agent.client.list_models()
        model_found = any(args.model in m for m in models)
        if not model_found and models:
            print_error(f"Model '{args.model}' is not currently pulled in Ollama.")
            print_info(f"Available local models: {', '.join(models)}")
            print_info(f"Run `ollama pull {args.model}` to download it.")
        elif model_found:
            print_info(f"Model '{args.model}' is verified and ready.")

        # Check local processor offload status (CPU vs GPU)
        try:
            import urllib.request
            ps_url = f"{agent.client.raw_ollama_url}/api/ps"
            req = urllib.request.Request(ps_url)
            with urllib.request.urlopen(req, timeout=3) as r:
                ps_data = json.loads(r.read().decode("utf-8"))
                for running_m in ps_data.get("models", []):
                    if args.model in running_m.get("name", ""):
                        size_vram = running_m.get("size_vram", 0)
                        total_size = running_m.get("size", 1)
                        pct_vram = (size_vram / total_size) * 100
                        if pct_vram < 50:
                            print_info(f"Hardware Notice: '{args.model}' is running mostly on CPU ({100-pct_vram:.0f}% CPU).")
                            print_info("Responses may take 1-3 minutes per turn. For fast 3-5s responses on CPU, consider 'qwen2.5-coder:1.5b'.")
        except Exception:
            pass

    # Single-task mode
    if args.task:
        agent.run_task(args.task, max_iterations=args.max_iterations)
        return

    # Interactive REPL mode
    print_info("Entering interactive mode. Type your task, or 'exit' / 'quit' to end.\n")
    while True:
        try:
            prompt = input("\nkirmya_agent > ").strip()
            if not prompt:
                continue
            if prompt.lower() in ("exit", "quit", "q"):
                print_info("Exiting coding agent session.")
                break
            agent.run_task(prompt, max_iterations=args.max_iterations)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting session.")
            break


if __name__ == "__main__":
    main()
