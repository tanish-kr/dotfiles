import json
import tempfile
import unittest
from pathlib import Path

import permission_candidates as pc

HOME = "/Users/alice"


def keys(command):
    return [pc.command_key(s) for s in pc.split_segments(command)]


class TestSplitSegments(unittest.TestCase):
    def test_splits_on_operators(self):
        self.assertEqual(keys("cd app && git log -5 | head; ls"), ["cd", "git log", "head", "ls"])

    def test_splits_on_newlines(self):
        self.assertEqual(keys("git status\ngit diff"), ["git status", "git diff"])

    def test_keeps_quoted_operators(self):
        self.assertEqual(keys("echo 'a && b' && git log"), ["echo", "git log"])

    def test_heredoc_uses_first_line_only(self):
        self.assertEqual(keys("python3 - <<'EOF'\nimport os\nEOF"), ["python3"])

    def test_unclosed_quote_returns_nothing(self):
        self.assertEqual(pc.split_segments("echo 'oops"), [])


class TestCommandKey(unittest.TestCase):
    def test_plain_command(self):
        self.assertEqual(pc.command_key(["ls", "-la"]), "ls")

    def test_gh_takes_two_levels(self):
        self.assertEqual(pc.command_key(["gh", "issue", "view", "12"]), "gh issue view")

    def test_stops_at_option(self):
        self.assertEqual(pc.command_key(["gh", "api", "-X", "GET"]), "gh api")

    def test_docker_compose_nests(self):
        self.assertEqual(pc.command_key(["docker", "compose", "up", "-d"]), "docker compose up")

    def test_skips_env_assignments(self):
        self.assertEqual(pc.command_key(["RAILS_ENV=test", "bundle", "exec", "rspec"]), "bundle exec rspec")

    def test_redirect_is_not_subcommand(self):
        self.assertEqual(keys("git status 2>/dev/null"), ["git status"])

    def test_loop_keywords(self):
        self.assertEqual(keys("for f in a b; do wc -l $f; done"), [None, "wc", None])

    def test_if_keywords(self):
        self.assertEqual(keys("if git diff --quiet; then echo ok; fi"), ["git diff", "echo", None])

    def test_git_dash_c(self):
        self.assertEqual(pc.command_key(["git", "-C", "/w/app", "log", "-1"]), "git log")

    def test_rejects_non_command(self):
        self.assertIsNone(pc.command_key(["$(pwd)/x"]))

    def test_git_global_flag(self):
        self.assertEqual(pc.command_key(["git", "--no-pager", "diff"]), "git diff")


class TestReadRule(unittest.TestCase):
    def test_inside_cwd_is_none(self):
        self.assertIsNone(pc.read_rule(HOME + "/work/app/a.rb", HOME + "/work/app", HOME))

    def test_home_dotdir(self):
        self.assertEqual(pc.read_rule(HOME + "/.docker/config.json", HOME + "/work/app", HOME), "Read(~/.docker/**)")

    def test_sibling_repo(self):
        self.assertEqual(
            pc.read_rule(HOME + "/work/other/lib/x.rb", HOME + "/work/app", HOME), "Read(~/work/other/**)"
        )

    def test_outside_home(self):
        self.assertEqual(pc.read_rule("/opt/homebrew/bin/gh", HOME + "/work/app", HOME), "Read(//opt/homebrew/**)")

    def test_file_directly_under_home_is_none(self):
        self.assertIsNone(pc.read_rule(HOME + "/.zshrc", HOME + "/work/app", HOME))


class TestReadRuleDir(unittest.TestCase):
    def test_home_and_absolute(self):
        self.assertEqual(pc.read_rule_dir("Read(~/.docker/**)", HOME), HOME + "/.docker")
        self.assertEqual(pc.read_rule_dir("Read(//opt/homebrew/**)", HOME), "/opt/homebrew")


class TestToolRules(unittest.TestCase):
    def test_mcp_and_websearch(self):
        self.assertEqual(pc.tool_rules("mcp__x__search", {}, None, HOME), ["mcp__x__search"])
        self.assertEqual(pc.tool_rules("WebSearch", {}, None, HOME), ["WebSearch"])

    def test_webfetch_domain(self):
        rules = pc.tool_rules("WebFetch", {"url": "https://docs.example.com/a"}, None, HOME)
        self.assertEqual(rules, ["WebFetch(domain:docs.example.com)"])

    def test_ignores_edit(self):
        self.assertEqual(pc.tool_rules("Edit", {"file_path": "/x"}, None, HOME), [])


class TestScanHistory(unittest.TestCase):
    def write(self, root, name, entrypoint, commands):
        lines = [json.dumps({"type": "user", "entrypoint": entrypoint, "cwd": "/w/app", "message": {"content": "x"}})]
        for cmd in commands:
            lines.append(json.dumps({
                "type": "assistant", "cwd": "/w/app", "entrypoint": entrypoint,
                "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]},
            }))
        path = root / "-w-app" / ("%s.jsonl" % name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")

    def test_counts_calls_and_sessions_excluding_sdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "a", "cli", ["git log", "git log -1"])
            self.write(root, "b", "cli", ["git log && ls"])
            self.write(root, "c", "sdk-cli", ["git log"])
            stats, count = pc.scan_history(root, 30, HOME)
        self.assertEqual(count, 2)
        self.assertEqual(stats["Bash(git log *)"]["calls"], 3)
        self.assertEqual(len(stats["Bash(git log *)"]["sessions"]), 2)
        self.assertIn(stats["Bash(git log *)"]["example"], ("git log", "git log && ls"))


class TestCovered(unittest.TestCase):
    def test_wildcard_covers_narrower(self):
        self.assertTrue(pc.covered("Bash(gh issue view *)", ["Bash(gh issue *)"]))

    def test_does_not_cover_other(self):
        self.assertFalse(pc.covered("Bash(git push *)", ["Bash(git log *)"]))

    def test_exact(self):
        self.assertTrue(pc.covered("WebSearch", ["WebSearch"]))


class TestBuildCandidates(unittest.TestCase):
    def stat(self, sessions, calls=1):
        return {"calls": calls, "sessions": set(range(sessions)), "repos": {"/w/app"}, "example": None}

    def test_thresholds_and_existing(self):
        history = {
            "Bash(git log *)": self.stat(3),
            "Bash(rare *)": self.stat(1),
            "Bash(gh issue view *)": self.stat(5),
        }
        local = {"Bash(docker info *)": ["a", "b"], "Bash(once *)": ["a"]}
        user = {"allow": ["Bash(gh issue *)"]}
        rules = [c["rule"] for c in pc.build_candidates(history, local, user)]
        self.assertEqual(sorted(rules), ["Bash(docker info *)", "Bash(git log *)"])

    def test_denied_rules_are_excluded(self):
        result = pc.build_candidates({"Bash(rm *)": self.stat(9)}, {}, {"deny": ["Bash(rm *)"]})
        self.assertEqual(result, [])


class TestDuplicates(unittest.TestCase):
    def test_lists_local_rules_covered_by_user(self):
        local = {"Bash(git log *)": ["/r1/s.json", "/r2/s.json"], "Bash(git push *)": ["/r1/s.json"]}
        dups = pc.find_duplicates(local, ["Bash(git log *)"])
        self.assertEqual(dups, [
            {"file": "/r1/s.json", "rules": ["Bash(git log *)"]},
            {"file": "/r2/s.json", "rules": ["Bash(git log *)"]},
        ])


class TestEdit(unittest.TestCase):
    def test_add_keeps_other_keys_and_backs_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(json.dumps({"theme": "dark", "permissions": {"allow": ["WebSearch"]}}))
            added, saved = pc.add_rules(settings, ["WebSearch", "Bash(git log *)"], Path(tmp) / "bk")
            data = json.loads(settings.read_text())
            self.assertEqual(added, ["Bash(git log *)"])
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(data["permissions"]["allow"], ["WebSearch", "Bash(git log *)"])
            self.assertEqual(json.loads(saved.read_text())["permissions"]["allow"], ["WebSearch"])

    def test_add_creates_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            added, saved = pc.add_rules(settings, ["WebSearch"], Path(tmp) / "bk")
            self.assertEqual(added, ["WebSearch"])
            self.assertIsNone(saved)
            self.assertEqual(json.loads(settings.read_text())["permissions"]["allow"], ["WebSearch"])

    def test_add_nothing_does_not_touch_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text('{"permissions": {"allow": ["WebSearch"]}}')
            added, saved = pc.add_rules(settings, ["WebSearch"], Path(tmp) / "bk")
            self.assertEqual((added, saved), ([], None))
            self.assertFalse((Path(tmp) / "bk").exists())

    def test_prune_removes_only_given_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.local.json"
            settings.write_text(json.dumps({"permissions": {"allow": ["a", "b", "c"], "deny": ["d"]}}))
            removed, saved = pc.prune_rules(settings, ["b", "x"], Path(tmp) / "bk")
            data = json.loads(settings.read_text())
            self.assertEqual(removed, ["b"])
            self.assertEqual(data["permissions"], {"allow": ["a", "c"], "deny": ["d"]})
            self.assertIsNotNone(saved)

    def test_broken_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text("{broken")
            with self.assertRaises(pc.CandidateError):
                pc.add_rules(settings, ["a"], Path(tmp) / "bk")


if __name__ == "__main__":
    unittest.main()
