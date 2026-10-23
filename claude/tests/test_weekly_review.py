import json
import os
import plistlib
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import weekly_review

ISSUE = "https://github.com/acme/tracker/issues/12"
OTHER = "https://github.com/acme/tracker/issues/34"


def user(text, **extra):
    record = {
        "type": "user", "sessionId": "s1", "cwd": "/work/app", "gitBranch": "main",
        "entrypoint": "cli", "timestamp": "2026-10-20T01:00:00.000Z",
        "message": {"role": "user", "content": text},
    }
    record.update(extra)
    return json.dumps(record)


def assistant(text, **extra):
    record = {
        "type": "assistant", "sessionId": "s1", "cwd": "/work/app", "gitBranch": "main",
        "entrypoint": "cli", "timestamp": "2026-10-20T02:00:00.000Z",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }
    record.update(extra)
    return json.dumps(record)


def command(name, args=""):
    return (
        "<command-message>%s</command-message>\n<command-name>/%s</command-name>\n"
        "<command-args>%s</command-args>" % (name, name, args)
    )


class TestIsPrompt(unittest.TestCase):
    def test_plain_text_is_prompt(self):
        self.assertTrue(weekly_review.is_prompt("調査して %s" % ISSUE))

    def test_clear_is_not_prompt(self):
        self.assertFalse(weekly_review.is_prompt(command("clear")))

    def test_custom_command_with_args_is_prompt(self):
        self.assertTrue(weekly_review.is_prompt(command("some-skill", ISSUE)))

    def test_local_command_output_is_not_prompt(self):
        self.assertFalse(weekly_review.is_prompt("<local-command-stdout>ok</local-command-stdout>"))

    def test_bash_input_is_not_prompt(self):
        self.assertFalse(weekly_review.is_prompt("<bash-input>ls</bash-input>"))

    def test_blank_is_not_prompt(self):
        self.assertFalse(weekly_review.is_prompt("  \n"))


class TestParseTranscript(unittest.TestCase):
    def test_skips_clear_and_takes_next_prompt(self):
        info = weekly_review.parse_transcript([
            user(command("clear")),
            user("続きをやる %s" % ISSUE),
            assistant("了解"),
        ])
        self.assertIn(ISSUE, info["first_prompt"])

    def test_ignores_meta_and_tool_results(self):
        info = weekly_review.parse_transcript([
            user("caveat", isMeta=True),
            user([{"type": "tool_result", "tool_use_id": "t", "content": "x"}]),
            user("本題"),
        ])
        self.assertEqual(info["first_prompt"], "本題")

    def test_keeps_last_assistant_text(self):
        info = weekly_review.parse_transcript([
            user("本題"),
            assistant("途中"),
            assistant("最後の応答"),
            json.dumps({
                "type": "assistant", "sessionId": "s1", "timestamp": "2026-10-20T03:00:00.000Z",
                "message": {"content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}]},
            }),
        ])
        self.assertEqual(info["last_reply"], "最後の応答")
        self.assertEqual(info["last_at"], "2026-10-20T03:00:00.000Z")

    def test_ignores_sidechain(self):
        info = weekly_review.parse_transcript([
            user("本題"),
            assistant("本線の応答"),
            assistant("サブエージェント", isSidechain=True),
        ])
        self.assertEqual(info["last_reply"], "本線の応答")

    def test_custom_title_wins_over_ai_title(self):
        info = weekly_review.parse_transcript([
            json.dumps({"type": "ai-title", "aiTitle": "自動"}),
            json.dumps({"type": "custom-title", "customTitle": "手動"}),
            json.dumps({"type": "ai-title", "aiTitle": "自動2"}),
        ])
        self.assertEqual(info["title"], "手動")

    def test_uses_latest_branch(self):
        info = weekly_review.parse_transcript([
            user("本題", gitBranch="main"),
            assistant("ok", gitBranch="feature/x"),
        ])
        self.assertEqual(info["branch"], "feature/x")

    def test_skips_broken_lines(self):
        info = weekly_review.parse_transcript(["{broken", user("本題")])
        self.assertEqual(info["first_prompt"], "本題")


class TestIsInteractive(unittest.TestCase):
    def test_cli_is_interactive(self):
        self.assertTrue(weekly_review.is_interactive({"entrypoint": "cli"}))

    def test_ide_is_interactive(self):
        self.assertTrue(weekly_review.is_interactive({"entrypoint": "claude-vscode"}))

    def test_sdk_is_not_interactive(self):
        self.assertFalse(weekly_review.is_interactive({"entrypoint": "sdk-cli"}))

    def test_missing_entrypoint_is_not_interactive(self):
        self.assertFalse(weekly_review.is_interactive({"entrypoint": None}))


class TestFindIssues(unittest.TestCase):
    def test_extracts_in_order_without_duplicates(self):
        text = "%s と %s と %s" % (OTHER, ISSUE, OTHER)
        self.assertEqual(weekly_review.find_issues(text), [OTHER, ISSUE])

    def test_drops_fragment_and_trailing_path(self):
        text = "%s#issuecomment-1 %s/timeline" % (ISSUE, OTHER)
        self.assertEqual(weekly_review.find_issues(text), [ISSUE, OTHER])

    def test_ignores_pull_requests(self):
        self.assertEqual(weekly_review.find_issues("https://github.com/acme/tracker/pull/5"), [])

    def test_handles_none(self):
        self.assertEqual(weekly_review.find_issues(None), [])


class TestCollectSessions(unittest.TestCase):
    def write(self, root, name, lines, age_days=0):
        path = root / "-work-app" / ("%s.jsonl" % name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
        mtime = time.time() - age_days * 86400
        os.utime(path, (mtime, mtime))
        return path

    def test_filters_by_age_and_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "recent", [user("a %s" % ISSUE, sessionId="recent")])
            self.write(root, "old", [user("b", sessionId="old")], age_days=10)
            self.write(root, "auto", [user("c", sessionId="auto", entrypoint="sdk-cli")])
            ids = [s["session_id"] for s in weekly_review.collect_sessions(root, 7)]
        self.assertEqual(ids, ["recent"])

    def test_ignores_subagent_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "main", [user("a", sessionId="main")])
            sub = root / "-work-app" / "main" / "subagents" / "agent-1.jsonl"
            sub.parent.mkdir(parents=True)
            sub.write_text(user("sub", sessionId="main") + "\n")
            sessions = weekly_review.collect_sessions(root, 7)
        self.assertEqual(len(sessions), 1)


class TestGroupByIssue(unittest.TestCase):
    def session(self, sid, prompt, last_at):
        return {"session_id": sid, "first_prompt": prompt, "last_at": last_at}

    def test_drops_closed_and_sorts_newest_first(self):
        sessions = [
            self.session("a", ISSUE, "2026-10-20T01:00:00Z"),
            self.session("b", ISSUE, "2026-10-21T01:00:00Z"),
            self.session("c", OTHER, "2026-10-22T01:00:00Z"),
            self.session("d", "Issue なし", "2026-10-23T01:00:00Z"),
        ]
        states = {ISSUE: {"state": "OPEN", "title": "open one"}, OTHER: {"state": "CLOSED", "title": "x"}}
        groups = weekly_review.group_by_issue(sessions, fetch=states.get)
        self.assertEqual([g["url"] for g in groups], [ISSUE])
        self.assertEqual([s["session_id"] for s in groups[0]["sessions"]], ["b", "a"])
        self.assertEqual(groups[0]["title"], "open one")

    def test_keeps_unknown_state(self):
        groups = weekly_review.group_by_issue(
            [self.session("a", ISSUE, "2026-10-20T01:00:00Z")], fetch=lambda url: None
        )
        self.assertEqual(len(groups), 1)
        self.assertFalse(groups[0]["known"])

    def test_fetches_each_issue_once(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return {"state": "OPEN", "title": "t"}

        weekly_review.group_by_issue(
            [self.session("a", ISSUE, "1"), self.session("b", ISSUE, "2")], fetch=fetch
        )
        self.assertEqual(calls, [ISSUE])


class TestExcerpt(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(weekly_review.excerpt("a\nb"), "a\nb")

    def test_truncates_lines(self):
        text = "\n".join(str(i) for i in range(20))
        result = weekly_review.excerpt(text, max_lines=3)
        self.assertEqual(result, "0\n1\n2\n…")

    def test_truncates_chars(self):
        result = weekly_review.excerpt("x" * 50, max_chars=10)
        self.assertEqual(result, "x" * 10 + "\n…")


class TestRenderMarkdown(unittest.TestCase):
    def test_renders_resume_command_and_quote(self):
        groups = [{
            "url": ISSUE, "title": "Issue 題名", "known": True,
            "sessions": [{
                "session_id": "abc", "title": "会話題名", "cwd": "/work/app", "branch": "main",
                "last_at": "2026-10-20T02:00:00.000Z", "last_reply": "1行目\n\n3行目",
            }],
        }]
        text = weekly_review.render_markdown(groups, datetime(2026, 10, 26, 9, 0), 7)
        self.assertIn("## Issue 題名", text)
        self.assertIn("`cd /work/app && claude --resume abc`", text)
        self.assertIn("> 1行目\n>\n> 3行目", text)

    def test_marks_unknown_state(self):
        groups = [{"url": ISSUE, "title": None, "known": False, "sessions": [
            {"session_id": "abc", "title": None, "cwd": None, "branch": None,
             "last_at": None, "last_reply": None},
        ]}]
        text = weekly_review.render_markdown(groups, datetime(2026, 10, 26, 9, 0), 7)
        self.assertIn("状態不明", text)
        self.assertNotIn("claude --resume", text)

    def test_empty(self):
        text = weekly_review.render_markdown([], datetime(2026, 10, 26, 9, 0), 7)
        self.assertIn("ありません", text)


class TestWriteReport(unittest.TestCase):
    def test_writes_dated_and_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            path = weekly_review.write_report("body", out, datetime(2026, 10, 26, 9, 0))
            self.assertEqual(path.name, "2026-10-26.md")
            self.assertEqual((out / "latest.md").read_text(), "body")
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["2026-10-26.md", "latest.md"])


class TestAgent(unittest.TestCase):
    def test_build_agent(self):
        definition = weekly_review.build_agent(["/usr/bin/python3", "x"], 1, 9, 0, "/tmp/a.log")
        self.assertEqual(definition["StartCalendarInterval"], {"Weekday": 1, "Hour": 9, "Minute": 0})
        self.assertIn("/opt/homebrew/bin", definition["EnvironmentVariables"]["PATH"])

    def test_install_writes_plist_and_bootstraps(self):
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            plist = Path(tmp) / "LaunchAgents" / "a.plist"
            log = Path(tmp) / "out" / "agent.log"
            definition = weekly_review.build_agent(["x"], 1, 9, 0, log)
            weekly_review.install_agent(definition, plist, run=run)
            with plist.open("rb") as f:
                self.assertEqual(plistlib.load(f)["Label"], weekly_review.AGENT_LABEL)
            self.assertTrue(log.parent.is_dir())
        self.assertEqual([c[1] for c in calls], ["bootout", "bootstrap"])

    def test_install_raises_on_bootstrap_failure(self):
        def run(cmd, **kwargs):
            return SimpleNamespace(returncode=1 if cmd[1] == "bootstrap" else 0, stderr="denied")

        with tempfile.TemporaryDirectory() as tmp:
            definition = weekly_review.build_agent(["x"], 1, 9, 0, Path(tmp) / "a.log")
            with self.assertRaises(weekly_review.ReviewError):
                weekly_review.install_agent(definition, Path(tmp) / "a.plist", run=run)

    def test_uninstall_removes_plist(self):
        with tempfile.TemporaryDirectory() as tmp:
            plist = Path(tmp) / "a.plist"
            plist.write_text("x")
            weekly_review.uninstall_agent(plist, run=lambda cmd, **kw: None)
            self.assertFalse(plist.exists())


if __name__ == "__main__":
    unittest.main()
