"""
Tests for ProcessManager — verifies that claude --print responses
are correctly parsed and that the session-file fallback works.

Run: python3 -m pytest test_process_manager.py -v
  or: python3 test_process_manager.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))
from process_manager import ProcessManager, AgentConfig, AgentResponse


class TestParseJsonResponse(unittest.TestCase):
    """Test _parse_json_response with various CLI output shapes."""

    def setUp(self):
        self.pm = ProcessManager()

    def test_normal_result_populated(self):
        """When CLI returns result text (future fix), use it directly."""
        stdout = json.dumps({
            "type": "result",
            "result": "Hello there!",
            "session_id": "abc-123",
            "total_cost_usd": 0.05,
            "usage": {"output_tokens": 10}
        })
        resp = self.pm._parse_json_response(stdout, 1.0)
        self.assertEqual(resp.text, "Hello there!")
        self.assertEqual(resp.session_id, "abc-123")
        self.assertAlmostEqual(resp.cost_usd, 0.05)
        self.assertFalse(resp.is_error)

    def test_empty_result_triggers_session_fallback(self):
        """When result is empty (TTY bug), falls back to session file."""
        stdout = json.dumps({
            "type": "result",
            "result": "",
            "session_id": "test-session-id",
            "total_cost_usd": 0.75,
            "usage": {"output_tokens": 100}
        })
        # Mock the session file reader to return text
        with patch.object(self.pm, '_read_session_response', return_value="Recovered text from session file"):
            resp = self.pm._parse_json_response(stdout, 2.5, cwd="/tmp")

        self.assertEqual(resp.text, "Recovered text from session file")
        self.assertEqual(resp.session_id, "test-session-id")
        self.assertAlmostEqual(resp.cost_usd, 0.75)

    def test_empty_result_no_session_id(self):
        """When result is empty AND no session_id, return empty string."""
        stdout = json.dumps({
            "type": "result",
            "result": "",
            "total_cost_usd": 0.01
        })
        resp = self.pm._parse_json_response(stdout, 1.0)
        self.assertEqual(resp.text, "")
        self.assertIsNone(resp.session_id)

    def test_null_result_triggers_fallback(self):
        """When result is null/None, trigger fallback."""
        stdout = json.dumps({
            "type": "result",
            "result": None,
            "session_id": "sess-456",
            "total_cost_usd": 0.10
        })
        with patch.object(self.pm, '_read_session_response', return_value="Fallback text"):
            resp = self.pm._parse_json_response(stdout, 1.0, cwd="/tmp")
        self.assertEqual(resp.text, "Fallback text")

    def test_missing_result_key_triggers_fallback(self):
        """When result key is absent, trigger fallback."""
        stdout = json.dumps({
            "type": "result",
            "session_id": "sess-789",
            "total_cost_usd": 0.10
        })
        with patch.object(self.pm, '_read_session_response', return_value="From session"):
            resp = self.pm._parse_json_response(stdout, 1.0, cwd="/tmp")
        self.assertEqual(resp.text, "From session")

    def test_invalid_json_falls_back_to_raw(self):
        """When stdout is not valid JSON, use raw text."""
        resp = self.pm._parse_json_response("not json at all", 1.0)
        self.assertEqual(resp.text, "not json at all")
        self.assertFalse(resp.is_error)

    def test_cost_defaults_to_zero(self):
        """Missing or null cost should default to 0.0."""
        stdout = json.dumps({"type": "result", "result": "ok"})
        resp = self.pm._parse_json_response(stdout, 1.0)
        self.assertEqual(resp.cost_usd, 0.0)

    def test_null_cost_defaults_to_zero(self):
        """Explicit null cost should default to 0.0."""
        stdout = json.dumps({"type": "result", "result": "ok", "total_cost_usd": None})
        resp = self.pm._parse_json_response(stdout, 1.0)
        self.assertEqual(resp.cost_usd, 0.0)


class TestReadSessionResponse(unittest.TestCase):
    """Test _read_session_response reads JSONL correctly."""

    def setUp(self):
        self.pm = ProcessManager()

    def _write_session_file(self, tmpdir, session_id, lines):
        """Helper to create a mock session JSONL file."""
        session_file = Path(tmpdir) / f"{session_id}.jsonl"
        with open(session_file, 'w') as f:
            for obj in lines:
                f.write(json.dumps(obj) + '\n')
        return session_file

    def test_extracts_last_assistant_text(self):
        """Should extract text from the last assistant content block."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_session_file(tmpdir, "sess-001", [
                {"type": "user", "message": {"role": "user", "content": "hello"}},
                {"type": "assistant", "message": {
                    "role": "assistant",
                    "content": [{"type": "thinking", "thinking": "hmm..."}]
                }},
                {"type": "assistant", "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello! How can I help?"}]
                }},
            ])
            result = self.pm._read_session_response("sess-001", cwd="")
            # Mock won't find via cwd, test direct
            with patch.object(self.pm, '_find_session_file', return_value=Path(tmpdir) / "sess-001.jsonl"):
                result = self.pm._read_session_response("sess-001")
            self.assertEqual(result, "Hello! How can I help?")

    def test_returns_last_text_when_multiple_assistant_turns(self):
        """When multiple assistant turns, return the last one's text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_file = self._write_session_file(tmpdir, "sess-002", [
                {"type": "user", "message": {"role": "user", "content": "first"}},
                {"type": "assistant", "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "First response"}]
                }},
                {"type": "user", "message": {"role": "user", "content": "second"}},
                {"type": "assistant", "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Second response"}]
                }},
            ])
            with patch.object(self.pm, '_find_session_file', return_value=session_file):
                result = self.pm._read_session_response("sess-002")
            self.assertEqual(result, "Second response")

    def test_returns_none_when_no_session_file(self):
        """Returns None when session file doesn't exist."""
        result = self.pm._read_session_response("nonexistent-id", cwd="/tmp/no-such-dir")
        self.assertIsNone(result)

    def test_skips_thinking_blocks(self):
        """Should not return thinking blocks as the text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_file = self._write_session_file(tmpdir, "sess-003", [
                {"type": "assistant", "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "Let me think..."},
                        {"type": "text", "text": "The answer is 42."}
                    ]
                }},
            ])
            with patch.object(self.pm, '_find_session_file', return_value=session_file):
                result = self.pm._read_session_response("sess-003")
            self.assertEqual(result, "The answer is 42.")

    def test_handles_malformed_jsonl_lines(self):
        """Gracefully handles corrupt lines in the JSONL file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_file = Path(tmpdir) / "sess-004.jsonl"
            with open(session_file, 'w') as f:
                f.write("not valid json\n")
                f.write(json.dumps({"type": "assistant", "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Still works"}]
                }}) + '\n')
                f.write("{truncated\n")
            with patch.object(self.pm, '_find_session_file', return_value=session_file):
                result = self.pm._read_session_response("sess-004")
            self.assertEqual(result, "Still works")

    def test_snapshot_only_file_returns_none(self):
        """Files with only file-history-snapshot entries (no conversation) return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_file = self._write_session_file(tmpdir, "sess-005", [
                {"type": "file-history-snapshot", "files": ["/tmp/foo.py"]},
                {"type": "file-history-snapshot", "files": ["/tmp/bar.py"]},
            ])
            with patch.object(self.pm, '_find_session_file', return_value=session_file):
                result = self.pm._read_session_response("sess-005")
            self.assertIsNone(result)

    def test_assistant_with_tool_use_blocks(self):
        """Extracts text even when assistant turn has tool_use blocks mixed in."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_file = self._write_session_file(tmpdir, "sess-006", [
                {"type": "user", "message": {"role": "user", "content": "list files"}},
                {"type": "assistant", "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        {"type": "text", "text": "Here are the files in the directory."}
                    ]
                }},
            ])
            with patch.object(self.pm, '_find_session_file', return_value=session_file):
                result = self.pm._read_session_response("sess-006")
            self.assertEqual(result, "Here are the files in the directory.")


class TestMangleCwd(unittest.TestCase):
    """Test cwd path mangling matches Claude's convention."""

    def test_slashes_become_dashes(self):
        self.assertEqual(
            ProcessManager._mangle_cwd("/Users/foo/project"),
            "-Users-foo-project"
        )

    def test_dots_become_dashes(self):
        self.assertEqual(
            ProcessManager._mangle_cwd("/Users/foo.bar/project"),
            "-Users-foo-bar-project"
        )

    def test_real_path(self):
        """Matches the actual mangled directory name on this machine."""
        self.assertEqual(
            ProcessManager._mangle_cwd("/Users/christopherk.marks/Downloads/personal-os-main"),
            "-Users-christopherk-marks-Downloads-personal-os-main"
        )


class TestFindSessionFile(unittest.TestCase):
    """Test _find_session_file path resolution."""

    def setUp(self):
        self.pm = ProcessManager()

    def test_finds_direct_path(self):
        """Finds session file at direct path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "abc-123.jsonl"
            target.touch()
            result = self.pm._find_session_file(Path(tmpdir), "abc-123")
            self.assertEqual(result, target)

    def test_skips_subagent_files(self):
        """Filters out subagent session files (tip from Symbolic)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Only a subagent file exists — should not be found
            subagent = Path(tmpdir) / "abc-123-subagent.jsonl"
            subagent.touch()
            result = self.pm._find_session_file(Path(tmpdir), "abc-123-subagent")
            self.assertIsNone(result)

    def test_finds_non_subagent_over_subagent(self):
        """Prefers non-subagent files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            real = Path(tmpdir) / "abc-123.jsonl"
            real.touch()
            result = self.pm._find_session_file(Path(tmpdir), "abc-123")
            self.assertEqual(result, real)

    def test_finds_nested_path(self):
        """Finds session file in subdirectory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir) / "subproject"
            subdir.mkdir()
            target = subdir / "abc-123.jsonl"
            target.touch()
            result = self.pm._find_session_file(Path(tmpdir), "abc-123")
            self.assertEqual(result, target)

    def test_returns_none_for_missing(self):
        """Returns None when file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.pm._find_session_file(Path(tmpdir), "nonexistent")
            self.assertIsNone(result)

    def test_returns_none_for_missing_dir(self):
        """Returns None when directory doesn't exist."""
        result = self.pm._find_session_file(Path("/tmp/no-such-dir-12345"), "abc")
        self.assertIsNone(result)


class TestEndToEnd(unittest.TestCase):
    """Integration test: actually call claude CLI and verify response text."""

    @unittest.skipUnless(
        os.environ.get("RUN_INTEGRATION_TESTS"),
        "Set RUN_INTEGRATION_TESTS=1 to run (costs money)"
    )
    def test_send_message_returns_text(self):
        """THE TEST: subprocess sends message, gets non-empty result text back."""
        pm = ProcessManager()
        config = AgentConfig(
            agent_id="test-integration",
            name="Test Agent",
            cwd=str(Path.home()),
            model="haiku"
        )
        response = pm.send_message(config, "Say exactly: INTEGRATION_TEST_PASSED")
        self.assertFalse(response.is_error, f"Got error: {response.text}")
        self.assertNotEqual(response.text, "", "Response text should not be empty")
        self.assertIn("INTEGRATION_TEST", response.text)
        self.assertGreater(response.cost_usd, 0)
        self.assertIsNotNone(response.session_id)
        print(f"\n  Response: {response.text[:100]}")
        print(f"  Cost: ${response.cost_usd:.4f}")
        print(f"  Session: {response.session_id[:8]}...")


if __name__ == "__main__":
    unittest.main(verbosity=2)
