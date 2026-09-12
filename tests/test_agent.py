"""
Unit tests for the Offline Coding Agent.
Verifies security path traversal guards, specialized tools, and project awareness.
"""

import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from agent import (
    WorkspaceGuard,
    SecurityViolationError,
    ToolSuite,
    ProjectDetector,
)


class TestWorkspaceGuard(unittest.TestCase):
    """Tests the strict path traversal prevention mechanisms."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="kirmya_test_ws_")
        self.guard = WorkspaceGuard(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_safe_relative_path(self):
        resolved = self.guard.resolve_safe_path("src/index.ts")
        expected = (Path(self.temp_dir) / "src" / "index.ts").resolve()
        self.assertEqual(resolved, expected)

    def test_parent_traversal_blocked(self):
        with self.assertRaises(SecurityViolationError):
            self.guard.resolve_safe_path("../outside_file.txt")

    def test_deep_traversal_blocked(self):
        with self.assertRaises(SecurityViolationError):
            self.guard.resolve_safe_path("foo/bar/../../../../etc/passwd")

    def test_absolute_path_outside_blocked(self):
        # Outside absolute path
        outside_path = Path(tempfile.gettempdir()).resolve()
        if outside_path != Path(self.temp_dir).resolve():
            with self.assertRaises(SecurityViolationError):
                self.guard.resolve_safe_path(str(outside_path))

    def test_dot_path_allowed(self):
        resolved = self.guard.resolve_safe_path(".")
        self.assertEqual(resolved, Path(self.temp_dir).resolve())


class TestToolSuite(unittest.TestCase):
    """Tests read_file, write_file, search_code, list_dir, and run_terminal."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="kirmya_test_tools_")
        self.guard = WorkspaceGuard(self.temp_dir)
        self.tools = ToolSuite(self.guard)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_write_and_read_file(self):
        # Write file with nested directory creation
        content = "Line 1\nLine 2: Hello World\nLine 3: Goodbye\nLine 4: End"
        write_res = self.tools.write_file("src/components/Button.tsx", content)
        self.assertIn("Success", write_res)

        # Read full file
        read_res = self.tools.read_file("src/components/Button.tsx")
        self.assertIn("Line 2: Hello World", read_res)
        self.assertIn("   1 | Line 1", read_res)

        # Read line range
        range_res = self.tools.read_file("src/components/Button.tsx", start_line=2, end_line=3)
        self.assertIn("   2 | Line 2: Hello World", range_res)
        self.assertIn("   3 | Line 3: Goodbye", range_res)
        self.assertNotIn("Line 1", range_res)
        self.assertNotIn("Line 4", range_res)

    def test_read_file_security_block(self):
        res = self.tools.read_file("../../../secret.env")
        self.assertIn("Security Error", res)

    def test_write_file_security_block(self):
        res = self.tools.write_file("../../../malicious.sh", "echo bad")
        self.assertIn("Security Error", res)

    def test_search_code_and_ignore_node_modules(self):
        # Create normal files
        self.tools.write_file("src/app.ts", "const apiKey = 'secret_token_123';\nfunction run() {}")
        self.tools.write_file("src/utils.ts", "export const name = 'kirmya';")

        # Create ignored node_modules file
        node_modules_file = Path(self.temp_dir) / "node_modules" / "pkg" / "index.js"
        node_modules_file.parent.mkdir(parents=True, exist_ok=True)
        node_modules_file.write_text("const apiKey = 'ignored_in_node_modules';", encoding="utf-8")

        # Search
        res = self.tools.search_code("apiKey")
        self.assertIn("src/app.ts:1:", res)
        self.assertNotIn("node_modules", res)

    def test_list_dir(self):
        self.tools.write_file("package.json", "{}")
        self.tools.write_file("src/index.ts", "console.log('hi');")
        # Ignored dir
        (Path(self.temp_dir) / "node_modules").mkdir(exist_ok=True)

        listing = self.tools.list_dir(".")
        self.assertIn("package.json", listing)
        self.assertIn("src/", listing)
        self.assertNotIn("node_modules", listing)

    def test_run_terminal(self):
        res = self.tools.run_terminal("echo agent_test_ok")
        self.assertIn("agent_test_ok", res)
        self.assertIn("Exit Code: 0", res)

    def test_run_terminal_blocks_dangerous_command(self):
        res = self.tools.run_terminal("rm -rf /")
        self.assertIn("Security Error: Command blocked by safety filter", res)

    def test_inspect_package_json(self):
        self.tools.write_file("package.json", '{"name": "test_kirmya", "scripts": {"test": "vitest"}}')
        info = self.tools.inspect_package_json()
        self.assertIn("test_kirmya", info)
        self.assertIn("vitest", info)

    def test_verification_tools(self):
        # Configure toolsuite with mock commands
        mock_info = {
            "typecheck_cmd": "echo typecheck_ok",
            "test_cmd": "echo test_ok",
            "lint_cmd": "echo lint_ok"
        }
        tools = ToolSuite(self.guard, mock_info)
        tc_res = tools.run_typecheck()
        self.assertIn("typecheck_ok", tc_res)

        test_res = tools.run_unit_tests("src/App.test.tsx")
        self.assertIn("test_ok", test_res)

        lint_res = tools.run_linter()
        self.assertIn("lint_ok", lint_res)


class TestProjectDetector(unittest.TestCase):
    """Tests the project awareness and diagnostic capabilities."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="kirmya_test_detector_")
        self.guard = WorkspaceGuard(self.temp_dir)
        self.detector = ProjectDetector(self.guard)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_detect_typescript_react(self):
        # Create mock package.json
        pkg = {
            "name": "kirmya_project",
            "scripts": {
                "typecheck": "tsc --noEmit",
                "test": "vitest run",
                "lint": "eslint src/"
            },
            "dependencies": {
                "react": "^18.2.0",
                "react-dom": "^18.2.0"
            },
            "devDependencies": {
                "typescript": "^5.0.0",
                "vitest": "^1.0.0"
            }
        }
        import json
        (Path(self.temp_dir) / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        (Path(self.temp_dir) / "tsconfig.json").write_text("{}", encoding="utf-8")

        info = self.detector.detect()
        self.assertEqual(info["name"], "kirmya_project")
        self.assertEqual(info["type"], "TypeScript/React")
        self.assertIn("React", info["frameworks"])
        self.assertEqual(info["typecheck_cmd"], "npm run typecheck")
        self.assertEqual(info["test_cmd"], "npm test")
        self.assertEqual(info["lint_cmd"], "npm run lint")


if __name__ == "__main__":
    unittest.main()
