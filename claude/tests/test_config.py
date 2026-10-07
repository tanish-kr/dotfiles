import json
import tempfile
import unittest
from pathlib import Path

import config


class TestPaths(unittest.TestCase):
    def test_normalize_replaces_home_with_token(self):
        self.assertEqual(
            config.normalize_home("/Users/alice/workspace/app", "/Users/alice"),
            "__HOME__/workspace/app",
        )

    def test_normalize_leaves_paths_outside_home(self):
        self.assertEqual(
            config.normalize_home("/opt/tools/bin", "/Users/alice"),
            "/opt/tools/bin",
        )

    def test_localize_is_inverse_of_normalize(self):
        original = "/Users/alice/workspace/app"
        token = config.normalize_home(original, "/Users/alice")
        self.assertEqual(config.localize_home(token, "/Users/bob"), "/Users/bob/workspace/app")

    def test_round_trip_returns_original(self):
        original = "/Users/alice/workspace/app"
        token = config.normalize_home(original, "/Users/alice")
        self.assertEqual(config.localize_home(token, "/Users/alice"), original)

    def test_normalize_passes_through_non_strings(self):
        self.assertEqual(config.normalize_home(None, "/Users/alice"), None)


class TestPlaceholders(unittest.TestCase):
    def test_placeholder_name_upcases_and_joins(self):
        self.assertEqual(config.placeholder_name("github", "Authorization"), "GITHUB_AUTHORIZATION")

    def test_placeholder_name_collapses_punctuation(self):
        self.assertEqual(
            config.placeholder_name("ci-mcp-server", "CI_TOKEN"),
            "CI_MCP_SERVER_CI_TOKEN",
        )

    def test_redact_env_replaces_every_value_by_default(self):
        result = config.redact_env("svc", {"TOKEN": "real-secret"}, set(), "/Users/alice")
        self.assertEqual(result, {"TOKEN": "${SVC_TOKEN}"})

    def test_redact_env_keeps_allowlisted_key(self):
        result = config.redact_env("svc", {"PATH": "/Users/alice/bin"}, {"svc/PATH"}, "/Users/alice")
        self.assertEqual(result, {"PATH": "__HOME__/bin"})

    def test_redact_env_allowlist_is_scoped_per_server(self):
        result = config.redact_env("other", {"PATH": "/Users/alice/bin"}, {"svc/PATH"}, "/Users/alice")
        self.assertEqual(result, {"PATH": "${OTHER_PATH}"})

    def test_redact_headers_keeps_auth_scheme(self):
        result = config.redact_headers("github", {"Authorization": "Bearer ghp_realtoken"})
        self.assertEqual(result, {"Authorization": "Bearer ${GITHUB_AUTHORIZATION}"})

    def test_redact_headers_replaces_whole_value_without_scheme(self):
        result = config.redact_headers("svc", {"X-Api-Key": "abcdef"})
        self.assertEqual(result, {"X-Api-Key": "${SVC_X_API_KEY}"})

    def test_redact_headers_has_no_allowlist(self):
        result = config.redact_headers("svc", {"X-Region": "us-east-1"})
        self.assertEqual(result, {"X-Region": "${SVC_X_REGION}"})


PLUGIN_LIST = [
    {
        "id": "tools@example-marketplace",
        "version": "0.1.0",
        "scope": "user",
        "enabled": True,
        "installPath": "/Users/alice/.claude/plugins/cache/x",
        "installedAt": "2026-01-01T00:00:00Z",
        "lastUpdated": "2026-01-01T00:00:00Z",
    },
    {
        "id": "tools@example-marketplace",
        "version": "0.1.0",
        "scope": "project",
        "enabled": False,
        "installPath": "/Users/alice/.claude/plugins/cache/x",
        "installedAt": "2026-01-01T00:00:00Z",
        "lastUpdated": "2026-01-01T00:00:00Z",
        "projectPath": "/Users/alice/workspace/app",
    },
]

MARKETPLACE_LIST = [
    {
        "name": "example-marketplace",
        "source": "github",
        "repo": "example-org/plugins",
        "installLocation": "/Users/alice/.claude/plugins/marketplaces/example-marketplace",
    },
    {"name": "local-marketplace", "source": "path", "path": "/Users/alice/dev/marketplace"},
]

CLAUDE_JSON = {
    "mcpServers": {
        "docs": {"type": "http", "url": "https://mcp.example.com/mcp",
                 "headers": {"Authorization": "Bearer realtoken"}},
    },
    "projects": {
        "/Users/alice/workspace/app": {
            "mcpServers": {
                "ci": {"type": "stdio", "command": "npx", "args": ["-y", "ci-mcp"],
                       "env": {"CI_TOKEN": "realsecret"}},
            },
        },
        "/Users/alice/workspace/empty": {},
    },
}


class TestBuildPluginsManifest(unittest.TestCase):
    def test_keeps_only_portable_fields(self):
        result = config.build_plugins_manifest(PLUGIN_LIST, MARKETPLACE_LIST, "/Users/alice")
        self.assertEqual(
            result["plugins"][0],
            {"id": "tools@example-marketplace", "scope": "project",
             "projectPath": "__HOME__/workspace/app", "enabled": False},
        )
        self.assertNotIn("installPath", result["plugins"][0])
        self.assertNotIn("version", result["plugins"][0])

    def test_user_scoped_entry_has_no_project_path(self):
        result = config.build_plugins_manifest(PLUGIN_LIST, MARKETPLACE_LIST, "/Users/alice")
        user_entry = [p for p in result["plugins"] if p["scope"] == "user"][0]
        self.assertNotIn("projectPath", user_entry)

    def test_sorts_plugins_by_scope_then_id(self):
        result = config.build_plugins_manifest(PLUGIN_LIST, MARKETPLACE_LIST, "/Users/alice")
        self.assertEqual([p["scope"] for p in result["plugins"]], ["project", "user"])

    def test_marketplace_keeps_source_identifier_only(self):
        result = config.build_plugins_manifest(PLUGIN_LIST, MARKETPLACE_LIST, "/Users/alice")
        self.assertEqual(
            result["marketplaces"][0],
            {"name": "example-marketplace", "source": "github", "repo": "example-org/plugins"},
        )

    def test_marketplace_path_is_normalized(self):
        result = config.build_plugins_manifest(PLUGIN_LIST, MARKETPLACE_LIST, "/Users/alice")
        local = [m for m in result["marketplaces"] if m["name"] == "local-marketplace"][0]
        self.assertEqual(local["path"], "__HOME__/dev/marketplace")


class TestBuildMcpManifest(unittest.TestCase):
    def test_user_scope_server_from_top_level(self):
        result = config.build_mcp_manifest(CLAUDE_JSON, "/Users/alice", set())
        docs = [s for s in result["servers"] if s["name"] == "docs"][0]
        self.assertEqual(docs["scope"], "user")
        self.assertNotIn("projectPath", docs)
        self.assertEqual(docs["config"]["url"], "https://mcp.example.com/mcp")
        self.assertEqual(docs["config"]["headers"]["Authorization"], "Bearer ${DOCS_AUTHORIZATION}")

    def test_local_scope_server_from_projects(self):
        result = config.build_mcp_manifest(CLAUDE_JSON, "/Users/alice", set())
        ci = [s for s in result["servers"] if s["name"] == "ci"][0]
        self.assertEqual(ci["scope"], "local")
        self.assertEqual(ci["projectPath"], "__HOME__/workspace/app")
        self.assertEqual(ci["config"]["env"], {"CI_TOKEN": "${CI_CI_TOKEN}"})

    def test_args_are_normalized_but_not_redacted(self):
        result = config.build_mcp_manifest(CLAUDE_JSON, "/Users/alice", set())
        ci = [s for s in result["servers"] if s["name"] == "ci"][0]
        self.assertEqual(ci["config"]["args"], ["-y", "ci-mcp"])

    def test_sorted_by_scope_then_name(self):
        result = config.build_mcp_manifest(CLAUDE_JSON, "/Users/alice", set())
        self.assertEqual([s["name"] for s in result["servers"]], ["ci", "docs"])

    def test_missing_claude_json_yields_no_servers(self):
        self.assertEqual(config.build_mcp_manifest({}, "/Users/alice", set()), {"servers": []})


class TestExternalInputs(unittest.TestCase):
    def test_read_claude_json_returns_empty_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(config.read_claude_json(Path(tmp) / "nope.json"), {})

    def test_read_claude_json_raises_readable_error_on_broken_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / ".claude.json"
            broken.write_text("{not json", encoding="utf-8")
            with self.assertRaises(config.ClaudeCliError) as caught:
                config.read_claude_json(broken)
            self.assertIn(str(broken), str(caught.exception))

    def test_run_claude_json_raises_readable_error_when_cli_absent(self):
        with self.assertRaises(config.ClaudeCliError) as caught:
            config.run_claude_json(["plugin", "list", "--json"], executable="claude-does-not-exist")
        self.assertIn("claude-does-not-exist", str(caught.exception))

    def test_load_plain_env_is_empty_when_file_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(config.load_plain_env(Path(tmp)), set())

    def test_load_plain_env_reads_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "plain-env.json").write_text(json.dumps(["svc/PATH"]), encoding="utf-8")
            self.assertEqual(config.load_plain_env(Path(tmp)), {"svc/PATH"})


class TestManifestIO(unittest.TestCase):
    def test_write_then_load_round_trips(self):
        plugins = {"marketplaces": [], "plugins": [{"id": "a@m", "scope": "user", "enabled": True}]}
        mcp = {"servers": [{"name": "docs", "scope": "user", "config": {"type": "http"}}]}
        with tempfile.TemporaryDirectory() as tmp:
            config.write_manifest(Path(tmp), plugins, mcp)
            self.assertEqual(config.load_manifest(Path(tmp)), (plugins, mcp))

    def test_write_creates_missing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "dir"
            config.write_manifest(target, {"marketplaces": [], "plugins": []}, {"servers": []})
            self.assertTrue((target / "plugins.json").exists())

    def test_written_json_ends_with_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            config.write_manifest(Path(tmp), {"marketplaces": [], "plugins": []}, {"servers": []})
            self.assertTrue((Path(tmp) / "mcp.json").read_text(encoding="utf-8").endswith("\n"))

    def test_load_raises_when_directory_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.ClaudeCliError) as caught:
                config.load_manifest(Path(tmp) / "missing")
            self.assertIn("missing", str(caught.exception))

    def test_load_raises_when_manifest_file_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "plugins.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(config.ClaudeCliError) as caught:
                config.load_manifest(Path(tmp))
            self.assertIn("mcp.json", str(caught.exception))


class TestPathMap(unittest.TestCase):
    def test_apply_rewrites_matching_prefix(self):
        mapping = {"__HOME__/workspace": "__HOME__/src"}
        self.assertEqual(
            config.apply_path_map("__HOME__/workspace/app", mapping),
            "__HOME__/src/app",
        )

    def test_apply_passes_through_unmatched_path(self):
        mapping = {"__HOME__/workspace": "__HOME__/src"}
        self.assertEqual(config.apply_path_map("__HOME__/other/app", mapping), "__HOME__/other/app")

    def test_apply_prefers_longest_match(self):
        mapping = {
            "__HOME__/workspace": "__HOME__/src",
            "__HOME__/workspace/special": "__HOME__/elsewhere",
        }
        self.assertEqual(
            config.apply_path_map("__HOME__/workspace/special/app", mapping),
            "__HOME__/elsewhere/app",
        )

    def test_apply_does_not_match_partial_segment(self):
        mapping = {"__HOME__/work": "__HOME__/src"}
        self.assertEqual(
            config.apply_path_map("__HOME__/workspace/app", mapping),
            "__HOME__/workspace/app",
        )

    def test_apply_matches_whole_path(self):
        mapping = {"__HOME__/workspace": "__HOME__/src"}
        self.assertEqual(config.apply_path_map("__HOME__/workspace", mapping), "__HOME__/src")

    def test_learn_prefix_strips_common_suffix(self):
        self.assertEqual(
            config.learn_prefix("__HOME__/workspace/app", "__HOME__/src/app"),
            ("__HOME__/workspace", "__HOME__/src"),
        )

    def test_learn_prefix_handles_multi_segment_suffix(self):
        self.assertEqual(
            config.learn_prefix("__HOME__/workspace/team/app", "__HOME__/src/team/app"),
            ("__HOME__/workspace", "__HOME__/src"),
        )

    def test_learn_prefix_returns_none_when_nothing_shared(self):
        self.assertIsNone(config.learn_prefix("__HOME__/a", "__HOME__/b"))

    def test_load_path_map_is_empty_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(config.load_path_map(Path(tmp)), {})

    def test_save_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            config.save_path_map(Path(tmp), {"__HOME__/workspace": "__HOME__/src"})
            self.assertEqual(
                config.load_path_map(Path(tmp)), {"__HOME__/workspace": "__HOME__/src"}
            )

    def test_load_path_map_raises_on_broken_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "path-map.json").write_text("{broken", encoding="utf-8")
            with self.assertRaises(config.ClaudeCliError):
                config.load_path_map(Path(tmp))


def _plugin(id_, scope="user", project=None, enabled=True):
    entry = {"id": id_, "scope": scope, "enabled": enabled}
    if project:
        entry["projectPath"] = project
    return entry


class TestDiff(unittest.TestCase):
    def test_entry_present_in_both_is_not_reported(self):
        entries = [_plugin("a@m")]
        result = config.diff_entries(entries, list(entries), config.plugin_key, "/Users/alice")
        self.assertEqual(result["only_manifest"], [])
        self.assertEqual(result["only_local"], [])
        self.assertEqual(result["differs"], [])

    def test_manifest_only_entry_is_reported(self):
        result = config.diff_entries([], [_plugin("a@m")], config.plugin_key, "/Users/alice")
        self.assertEqual([e["id"] for e in result["only_manifest"]], ["a@m"])

    def test_local_only_entry_is_reported(self):
        result = config.diff_entries([_plugin("a@m")], [], config.plugin_key, "/Users/alice")
        self.assertEqual([e["id"] for e in result["only_local"]], ["a@m"])

    def test_same_key_different_content_is_differs(self):
        result = config.diff_entries(
            [_plugin("a@m", enabled=True)],
            [_plugin("a@m", enabled=False)],
            config.plugin_key,
            "/Users/alice",
        )
        self.assertEqual(len(result["differs"]), 1)
        self.assertEqual(result["only_manifest"], [])

    def test_redacted_local_matches_placeheld_manifest(self):
        # 両辺とも build_* を通した正規化後の形なので placeholder どうしが一致する。
        server = {"name": "docs", "scope": "user",
                  "config": {"headers": {"Authorization": "Bearer ${DOCS_AUTHORIZATION}"}}}
        result = config.diff_entries([server], [dict(server)], config.mcp_key, "/Users/alice")
        self.assertEqual(result["differs"], [])

    def test_missing_project_path_is_project_missing(self):
        entry = _plugin("a@m", scope="project", project="__HOME__/workspace/app")
        result = config.diff_entries(
            [], [entry], config.plugin_key, "/Users/alice", exists=lambda p: False
        )
        self.assertEqual([e["id"] for e in result["project_missing"]], ["a@m"])
        self.assertEqual(result["only_manifest"], [])

    def test_existing_project_path_is_only_manifest(self):
        entry = _plugin("a@m", scope="project", project="__HOME__/workspace/app")
        result = config.diff_entries(
            [], [entry], config.plugin_key, "/Users/alice", exists=lambda p: True
        )
        self.assertEqual([e["id"] for e in result["only_manifest"]], ["a@m"])
        self.assertEqual(result["project_missing"], [])

    def test_path_map_is_applied_before_existence_check(self):
        entry = _plugin("a@m", scope="project", project="__HOME__/workspace/app")
        seen = []

        def exists(path):
            seen.append(path)
            return True

        config.diff_entries(
            [], [entry], config.plugin_key, "/Users/alice",
            path_map={"__HOME__/workspace": "__HOME__/src"}, exists=exists,
        )
        self.assertEqual(seen, ["/Users/alice/src/app"])

    def test_same_name_different_scope_are_distinct_keys(self):
        local = [{"name": "docs", "scope": "user", "config": {}}]
        manifest = [{"name": "docs", "scope": "local", "projectPath": "__HOME__/workspace/app",
                     "config": {}}]
        result = config.diff_entries(
            local, manifest, config.mcp_key, "/Users/alice", exists=lambda p: True
        )
        self.assertEqual(len(result["only_manifest"]), 1)
        self.assertEqual(len(result["only_local"]), 1)


if __name__ == "__main__":
    unittest.main()
