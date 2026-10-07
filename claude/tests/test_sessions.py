import json
import tempfile
import unittest
from pathlib import Path

import sessions


class TestEncodeProjectDir(unittest.TestCase):
    def test_replaces_slashes_with_dashes(self):
        self.assertEqual(sessions.encode_project_dir("/Users/alice/workspace"), "-Users-alice-workspace")

    def test_replaces_dots_with_dashes(self):
        self.assertEqual(sessions.encode_project_dir("/Users/alice/.config"), "-Users-alice--config")

    def test_handles_home_itself(self):
        self.assertEqual(sessions.encode_project_dir("/Users/alice"), "-Users-alice")


class TestRewriteDirName(unittest.TestCase):
    def test_swaps_home_prefix(self):
        self.assertEqual(
            sessions.rewrite_dir_name("-Users-alice-workspace-app", "/Users/alice", "/Users/bob"),
            "-Users-bob-workspace-app",
        )

    def test_leaves_unrelated_name_untouched(self):
        self.assertEqual(
            sessions.rewrite_dir_name("-opt-shared-app", "/Users/alice", "/Users/bob"),
            "-opt-shared-app",
        )

    def test_rewrites_bare_home_directory(self):
        self.assertEqual(
            sessions.rewrite_dir_name("-Users-alice", "/Users/alice", "/Users/bob"),
            "-Users-bob",
        )

    def test_does_not_match_partial_segment(self):
        self.assertEqual(
            sessions.rewrite_dir_name("-Users-alicia-workspace", "/Users/alice", "/Users/bob"),
            "-Users-alicia-workspace",
        )


class TestRewriteJsonlLine(unittest.TestCase):
    def test_rewrites_only_cwd(self):
        line = json.dumps({"cwd": "/Users/alice/workspace/app", "type": "user"})
        result = json.loads(sessions.rewrite_jsonl_line(line, "/Users/alice", "/Users/bob"))
        self.assertEqual(result["cwd"], "/Users/bob/workspace/app")
        self.assertEqual(result["type"], "user")

    def test_preserves_paths_inside_message_body(self):
        line = json.dumps({
            "cwd": "/Users/alice/workspace/app",
            "toolUseResult": "cat /Users/alice/workspace/app/main.py",
        })
        result = json.loads(sessions.rewrite_jsonl_line(line, "/Users/alice", "/Users/bob"))
        self.assertEqual(result["toolUseResult"], "cat /Users/alice/workspace/app/main.py")

    def test_passes_through_unparsable_line(self):
        self.assertEqual(
            sessions.rewrite_jsonl_line("not json at all\n", "/Users/alice", "/Users/bob"),
            "not json at all\n",
        )

    def test_passes_through_line_without_cwd(self):
        line = json.dumps({"type": "summary"})
        self.assertEqual(
            json.loads(sessions.rewrite_jsonl_line(line, "/Users/alice", "/Users/bob")),
            {"type": "summary"},
        )

    def test_leaves_cwd_outside_old_home(self):
        line = json.dumps({"cwd": "/opt/shared/app"})
        result = json.loads(sessions.rewrite_jsonl_line(line, "/Users/alice", "/Users/bob"))
        self.assertEqual(result["cwd"], "/opt/shared/app")


class TestRewriteJsonlFile(unittest.TestCase):
    def test_round_trips_invalid_utf8_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.jsonl"
            dest = Path(tmp) / "out.jsonl"
            payload = json.dumps({"cwd": "/Users/alice/app"}).encode("utf-8")
            src.write_bytes(payload + b"\n" + b"\xff\xfe invalid bytes\n")
            sessions.rewrite_jsonl_file(src, dest, "/Users/alice", "/Users/bob")
            lines = dest.read_bytes().split(b"\n")
            self.assertEqual(json.loads(lines[0])["cwd"], "/Users/bob/app")
            self.assertEqual(lines[1], b"\xff\xfe invalid bytes")

    def test_preserves_line_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.jsonl"
            dest = Path(tmp) / "out.jsonl"
            src.write_text("\n".join(json.dumps({"i": i}) for i in range(5)) + "\n", encoding="utf-8")
            sessions.rewrite_jsonl_file(src, dest, "/Users/alice", "/Users/bob")
            self.assertEqual(len(dest.read_text(encoding="utf-8").splitlines()), 5)


if __name__ == "__main__":
    unittest.main()
