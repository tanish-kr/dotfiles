import io
import json
import os
import tarfile
import tempfile
import time
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


def _make_projects(root, entries):
    """entries: {相対パス: 内容} を projects ツリーとして作る。"""
    for rel, content in entries.items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class TestShouldInclude(unittest.TestCase):
    def setUp(self):
        self.all_ids = {"proj/aaa", "proj/bbb"}
        self.keep_ids = {"proj/aaa"}

    def test_keeps_selected_transcript(self):
        self.assertTrue(sessions.should_include("proj/aaa.jsonl", self.all_ids, self.keep_ids))

    def test_drops_unselected_transcript(self):
        self.assertFalse(sessions.should_include("proj/bbb.jsonl", self.all_ids, self.keep_ids))

    def test_keeps_sibling_dir_of_selected_transcript(self):
        self.assertTrue(
            sessions.should_include("proj/aaa/tool-results/x.json", self.all_ids, self.keep_ids)
        )

    def test_drops_sibling_dir_of_unselected_transcript(self):
        self.assertFalse(
            sessions.should_include("proj/bbb/tool-results/x.json", self.all_ids, self.keep_ids)
        )

    def test_keeps_memory_unconditionally(self):
        self.assertTrue(
            sessions.should_include("proj/memory/MEMORY.md", self.all_ids, self.keep_ids)
        )

    def test_keeps_session_aliases_unconditionally(self):
        self.assertTrue(
            sessions.should_include("proj/.session-aliases", self.all_ids, self.keep_ids)
        )

    def test_keeps_project_directory_itself(self):
        self.assertTrue(sessions.should_include("proj", self.all_ids, self.keep_ids))

    def test_distinguishes_same_uuid_across_projects(self):
        all_ids = {"one/aaa", "two/aaa"}
        keep_ids = {"one/aaa"}
        self.assertTrue(sessions.should_include("one/aaa/sub/x", all_ids, keep_ids))
        self.assertFalse(sessions.should_include("two/aaa/sub/x", all_ids, keep_ids))


class TestExportSessions(unittest.TestCase):
    def _tree(self, root):
        _make_projects(root, {
            "proj/aaa.jsonl": json.dumps({"cwd": "/Users/alice/app"}) + "\n",
            "proj/bbb.jsonl": json.dumps({"cwd": "/Users/alice/app"}) + "\n",
            "proj/aaa/tool-results/r.json": "{}",
            "proj/bbb/tool-results/r.json": "{}",
            "proj/memory/MEMORY.md": "- note\n",
            "proj/.session-aliases": "alias\n",
        })
        old = time.time() - 30 * 86400
        os.utime(Path(root) / "proj/bbb.jsonl", (old, old))

    def _names(self, archive):
        with tarfile.open(archive) as tar:
            return {n[2:] if n.startswith("./") else n for n in tar.getnames()}

    def test_day_filter_drops_old_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            projects.mkdir()
            self._tree(projects)
            archive, count = sessions.export_sessions(projects, Path(tmp) / "out", 7, "/Users/alice")
            names = self._names(archive)
            self.assertIn("proj/aaa.jsonl", names)
            self.assertNotIn("proj/bbb.jsonl", names)
            self.assertEqual(count, 1)

    def test_day_filter_zero_keeps_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            projects.mkdir()
            self._tree(projects)
            archive, count = sessions.export_sessions(projects, Path(tmp) / "out", 0, "/Users/alice")
            names = self._names(archive)
            self.assertIn("proj/bbb.jsonl", names)
            self.assertEqual(count, 2)

    def test_memory_is_included_even_when_transcript_is_filtered_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            projects.mkdir()
            self._tree(projects)
            archive, _ = sessions.export_sessions(projects, Path(tmp) / "out", 7, "/Users/alice")
            self.assertIn("proj/memory/MEMORY.md", self._names(archive))

    def test_sibling_dir_follows_its_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            projects.mkdir()
            self._tree(projects)
            archive, _ = sessions.export_sessions(projects, Path(tmp) / "out", 7, "/Users/alice")
            names = self._names(archive)
            self.assertIn("proj/aaa/tool-results/r.json", names)
            self.assertNotIn("proj/bbb/tool-results/r.json", names)

    def test_meta_records_home_and_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            projects.mkdir()
            self._tree(projects)
            archive, _ = sessions.export_sessions(projects, Path(tmp) / "out", 7, "/Users/alice")
            with tarfile.open(archive) as tar:
                meta = json.loads(tar.extractfile("meta.json").read().decode("utf-8"))
            self.assertEqual(meta["home"], "/Users/alice")
            self.assertEqual(meta["transcripts"], 1)

    def test_meta_is_not_written_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            projects.mkdir()
            self._tree(projects)
            out = Path(tmp) / "out"
            sessions.export_sessions(projects, out, 7, "/Users/alice")
            self.assertEqual([p.name for p in out.iterdir() if p.name == "meta.json"], [])

    def test_creates_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            projects.mkdir()
            self._tree(projects)
            out = Path(tmp) / "nested" / "out"
            archive, _ = sessions.export_sessions(projects, out, 7, "/Users/alice")
            self.assertTrue(archive.exists())

    def test_raises_when_projects_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(sessions.SessionError):
                sessions.export_sessions(Path(tmp) / "nope", Path(tmp) / "out", 7, "/Users/alice")


class TestImportSessions(unittest.TestCase):
    def _archive(self, tmp, home="/Users/alice", with_meta=True):
        projects = Path(tmp) / "projects"
        projects.mkdir()
        _make_projects(projects, {
            "-Users-alice-workspace-app/aaa.jsonl":
                json.dumps({"cwd": "/Users/alice/workspace/app", "type": "user"}) + "\n",
            "-Users-alice-workspace-app/memory/MEMORY.md": "- note\n",
        })
        archive = Path(tmp) / "archive.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(projects, arcname=".")
            if with_meta:
                payload = json.dumps({"home": home, "transcripts": 1}).encode("utf-8")
                info = tarfile.TarInfo("meta.json")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
        return archive

    def test_restores_transcript_and_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp)
            target = Path(tmp) / "restored"
            result = sessions.import_sessions(archive, target, "/Users/alice", log=lambda m: None)
            self.assertEqual(result["transcripts"], 1)
            self.assertTrue((target / "-Users-alice-workspace-app" / "aaa.jsonl").exists())
            self.assertTrue((target / "-Users-alice-workspace-app" / "memory" / "MEMORY.md").exists())

    def test_renames_directory_for_different_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp)
            target = Path(tmp) / "restored"
            sessions.import_sessions(archive, target, "/Users/bob", log=lambda m: None)
            self.assertTrue((target / "-Users-bob-workspace-app" / "aaa.jsonl").exists())

    def test_rewrites_cwd_for_different_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp)
            target = Path(tmp) / "restored"
            sessions.import_sessions(archive, target, "/Users/bob", log=lambda m: None)
            line = (target / "-Users-bob-workspace-app" / "aaa.jsonl").read_text(encoding="utf-8")
            self.assertEqual(json.loads(line)["cwd"], "/Users/bob/workspace/app")

    def test_leaves_content_untouched_for_same_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp)
            target = Path(tmp) / "restored"
            sessions.import_sessions(archive, target, "/Users/alice", log=lambda m: None)
            line = (target / "-Users-alice-workspace-app" / "aaa.jsonl").read_text(encoding="utf-8")
            self.assertEqual(json.loads(line)["cwd"], "/Users/alice/workspace/app")

    def test_meta_json_is_not_restored(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp)
            target = Path(tmp) / "restored"
            sessions.import_sessions(archive, target, "/Users/alice", log=lambda m: None)
            self.assertFalse((target / "meta.json").exists())

    def test_existing_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp)
            target = Path(tmp) / "restored"
            existing = target / "-Users-alice-workspace-app" / "aaa.jsonl"
            existing.parent.mkdir(parents=True)
            existing.write_text("original\n", encoding="utf-8")
            result = sessions.import_sessions(archive, target, "/Users/alice", log=lambda m: None)
            self.assertEqual(existing.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(result["skipped"], 1)

    def test_force_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp)
            target = Path(tmp) / "restored"
            existing = target / "-Users-alice-workspace-app" / "aaa.jsonl"
            existing.parent.mkdir(parents=True)
            existing.write_text("original\n", encoding="utf-8")
            sessions.import_sessions(archive, target, "/Users/alice", force=True, log=lambda m: None)
            self.assertNotEqual(existing.read_text(encoding="utf-8"), "original\n")

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp)
            target = Path(tmp) / "restored"
            result = sessions.import_sessions(
                archive, target, "/Users/alice", dry_run=True, log=lambda m: None
            )
            self.assertEqual(result["transcripts"], 1)
            self.assertFalse(target.exists())

    def test_missing_meta_raises_readable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp, with_meta=False)
            with self.assertRaises(sessions.SessionError) as caught:
                sessions.import_sessions(archive, Path(tmp) / "r", "/Users/alice", log=lambda m: None)
            self.assertIn("meta.json", str(caught.exception))

    def test_archive_cannot_escape_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "evil.tar.gz"
            payload = b"pwned\n"
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("../escaped.txt")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
                meta = json.dumps({"home": "/Users/alice"}).encode("utf-8")
                meta_info = tarfile.TarInfo("meta.json")
                meta_info.size = len(meta)
                tar.addfile(meta_info, io.BytesIO(meta))
            with self.assertRaises(Exception):
                sessions.import_sessions(
                    archive, Path(tmp) / "r", "/Users/alice", log=lambda m: None
                )
            self.assertFalse((Path(tmp) / "escaped.txt").exists())


if __name__ == "__main__":
    unittest.main()
