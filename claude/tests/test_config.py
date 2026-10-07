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
        result = config.redact_headers("github", {"Authorization": "Bearer s3cr3t-token-value"})
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

    def test_plugin_without_id_raises_readable_error(self):
        with self.assertRaises(config.ClaudeCliError) as caught:
            config.build_plugins_manifest([{"scope": "user"}], [], "/Users/alice")
        self.assertIn("id", str(caught.exception))

    def test_marketplace_without_identifier_raises_at_export(self):
        # 識別子を落としたまま manifest に入ると、失敗するのは import 側のマシンになる。
        with self.assertRaises(config.ClaudeCliError) as caught:
            config.build_plugins_manifest(
                [], [{"name": "orphan", "source": "github"}], "/Users/alice"
            )
        self.assertIn("orphan", str(caught.exception))
        self.assertIn("repo/url/path", str(caught.exception))

    def test_marketplace_without_name_raises_readable_error(self):
        with self.assertRaises(config.ClaudeCliError) as caught:
            config.build_plugins_manifest([], [{"source": "github"}], "/Users/alice")
        self.assertIn("name", str(caught.exception))

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

    def _config_of(self, server_config):
        claude_json = {"mcpServers": {"svc": server_config}}
        return config.build_mcp_manifest(claude_json, "/Users/alice", set())["servers"][0]["config"]

    def test_unknown_key_is_placeheld_even_when_nested(self):
        result = self._config_of({"type": "stdio", "oauth": {"client_secret": "real-secret"}})
        self.assertEqual(result["oauth"], "${SVC_OAUTH}")

    def test_unknown_scalar_key_is_placeheld(self):
        result = self._config_of({"type": "stdio", "apiKey": "real-secret"})
        self.assertEqual(result["apiKey"], "${SVC_APIKEY}")

    def test_env_that_is_not_a_dict_is_placeheld_whole(self):
        result = self._config_of({"type": "stdio", "env": [["TOKEN", "real-secret"]]})
        self.assertEqual(result["env"], "${SVC_ENV}")

    def test_headers_that_is_not_a_dict_is_placeheld_whole(self):
        result = self._config_of({"type": "http", "headers": "Authorization: Bearer real"})
        self.assertEqual(result["headers"], "${SVC_HEADERS}")

    def test_known_keys_keep_real_values(self):
        result = self._config_of({
            "type": "stdio", "url": "https://mcp.example.com/mcp",
            "command": "/Users/alice/bin/server", "args": ["--flag", "/Users/alice/data"],
        })
        self.assertEqual(result["type"], "stdio")
        self.assertEqual(result["url"], "https://mcp.example.com/mcp")
        self.assertEqual(result["command"], "__HOME__/bin/server")
        self.assertEqual(result["args"], ["--flag", "__HOME__/data"])


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


class TestManifestSchema(unittest.TestCase):
    def _load(self, tmp, plugins, mcp):
        (Path(tmp) / "plugins.json").write_text(json.dumps(plugins), encoding="utf-8")
        (Path(tmp) / "mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
        with self.assertRaises(config.ClaudeCliError) as caught:
            config.load_manifest(Path(tmp))
        return str(caught.exception)

    def test_empty_objects_raise_naming_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            message = self._load(tmp, {}, {})
            self.assertIn("plugins.json", message)
            self.assertIn("plugins", message)

    def test_missing_marketplaces_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            message = self._load(tmp, {"plugins": []}, {"servers": []})
            self.assertIn("marketplaces", message)

    def test_missing_servers_raises_naming_mcp_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            message = self._load(tmp, {"marketplaces": [], "plugins": []}, {})
            self.assertIn("mcp.json", message)
            self.assertIn("servers", message)

    def test_non_list_value_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            message = self._load(
                tmp, {"marketplaces": [], "plugins": {}}, {"servers": []}
            )
            self.assertIn("plugins", message)

    def test_plugin_without_id_raises_naming_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            message = self._load(
                tmp, {"marketplaces": [], "plugins": [{"scope": "user"}]}, {"servers": []}
            )
            self.assertIn("plugins.json", message)
            self.assertIn("id", message)

    def test_marketplace_without_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            message = self._load(
                tmp, {"marketplaces": [{"source": "github"}], "plugins": []}, {"servers": []}
            )
            self.assertIn("plugins.json", message)
            self.assertIn("name", message)

    def test_server_without_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            message = self._load(
                tmp, {"marketplaces": [], "plugins": []}, {"servers": [{"scope": "user"}]}
            )
            self.assertIn("mcp.json", message)
            self.assertIn("name", message)

    def test_valid_manifest_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = {"marketplaces": [], "plugins": [_plugin("a@m")]}
            mcp = {"servers": [{"name": "docs", "scope": "user", "config": {}}]}
            config.write_manifest(Path(tmp), plugins, mcp)
            self.assertEqual(config.load_manifest(Path(tmp)), (plugins, mcp))


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


class TestExpand(unittest.TestCase):
    def test_substitutes_known_variable(self):
        value, missing = config.expand_env_refs("Bearer ${TOK}", {"TOK": "secret"})
        self.assertEqual(value, "Bearer secret")
        self.assertEqual(missing, [])

    def test_reports_unknown_variable_and_leaves_it(self):
        value, missing = config.expand_env_refs("Bearer ${TOK}", {})
        self.assertEqual(value, "Bearer ${TOK}")
        self.assertEqual(missing, ["TOK"])

    def test_passes_through_plain_text(self):
        value, missing = config.expand_env_refs("https://mcp.example.com/mcp", {})
        self.assertEqual(value, "https://mcp.example.com/mcp")
        self.assertEqual(missing, [])

    def test_expand_server_config_localizes_home_and_expands(self):
        server_config = {
            "type": "stdio", "command": "__HOME__/bin/server", "args": ["--flag"],
            "env": {"TOKEN": "${TOK}"},
        }
        result, missing = config.expand_server_config(server_config, "/Users/bob", {"TOK": "s"})
        self.assertEqual(result["command"], "/Users/bob/bin/server")
        self.assertEqual(result["env"], {"TOKEN": "s"})
        self.assertEqual(missing, [])

    def test_expand_server_config_collects_all_missing_names(self):
        server_config = {"type": "http", "url": "https://mcp.example.com/mcp",
                         "headers": {"Authorization": "Bearer ${A}", "X-Key": "${B}"}}
        _, missing = config.expand_server_config(server_config, "/Users/bob", {})
        self.assertEqual(missing, ["A", "B"])


class TestArgv(unittest.TestCase):
    def test_marketplace_argv_uses_repo(self):
        entry = {"name": "m", "source": "github", "repo": "example-org/plugins"}
        self.assertEqual(
            config.marketplace_argv(entry, "/Users/bob"),
            ["plugin", "marketplace", "add", "example-org/plugins"],
        )

    def test_marketplace_argv_localizes_path(self):
        entry = {"name": "m", "source": "path", "path": "__HOME__/dev/marketplace"}
        self.assertEqual(
            config.marketplace_argv(entry, "/Users/bob"),
            ["plugin", "marketplace", "add", "/Users/bob/dev/marketplace"],
        )

    def test_plugin_argv_passes_id_and_scope(self):
        self.assertEqual(
            config.plugin_argv({"id": "a@m", "scope": "user", "enabled": True}),
            ["plugin", "install", "a@m", "-s", "user", "-y"],
        )

    def test_plugin_disable_argv(self):
        self.assertEqual(
            config.plugin_disable_argv({"id": "a@m"}), ["plugin", "disable", "a@m"]
        )

    def test_mcp_argv_serialises_config_as_json(self):
        entry = {"name": "docs", "scope": "user"}
        server_config = {"type": "http", "url": "https://mcp.example.com/mcp"}
        argv = config.mcp_argv(entry, server_config)
        self.assertEqual(argv[:3], ["mcp", "add-json", "docs"])
        self.assertEqual(json.loads(argv[3]), server_config)
        self.assertEqual(argv[4:], ["-s", "user"])

    def test_mcp_argv_has_no_transport_branching(self):
        stdio = config.mcp_argv(
            {"name": "ci", "scope": "local"},
            {"type": "stdio", "command": "npx", "args": ["-y", "ci-mcp"]},
        )
        self.assertEqual(stdio[:3], ["mcp", "add-json", "ci"])
        self.assertNotIn("--header", stdio)
        self.assertNotIn("-e", stdio)


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

    def test_local_holding_real_token_equals_manifest_holding_placeholder(self):
        # 設計の中核: 実トークンを持つローカル状態と placeholder を持つ manifest が
        # 差分なしになる。両辺を build_* で manifest 空間に落としてから比べるため。
        def claude_json(home):
            return {
                "mcpServers": {
                    "docs": {"type": "http", "url": "https://mcp.example.com/mcp",
                             "headers": {"Authorization": "Bearer real-token-value"}},
                },
                "projects": {
                    "%s/workspace/app" % home: {
                        "mcpServers": {
                            "ci": {"type": "stdio", "command": "npx", "args": ["-y", "ci-mcp"],
                                   "env": {"CI_TOKEN": "another-real-secret"}},
                        },
                    },
                },
            }

        with tempfile.TemporaryDirectory() as tmp:
            # export 側のマシン
            exported_plugins = config.build_plugins_manifest(
                PLUGIN_LIST, MARKETPLACE_LIST, "/Users/alice"
            )
            exported_mcp = config.build_mcp_manifest(claude_json("/Users/alice"), "/Users/alice", set())
            config.write_manifest(Path(tmp), exported_plugins, exported_mcp)
            written = (Path(tmp) / "mcp.json").read_text(encoding="utf-8")
            self.assertNotIn("real-token-value", written)
            self.assertNotIn("another-real-secret", written)

            manifest_plugins, manifest_mcp = config.load_manifest(Path(tmp))

            # import 側のマシン。$HOME も実トークンも違うが、同じ正規化を通す。
            local_plugins = config.build_plugins_manifest(
                [dict(p, projectPath=p["projectPath"].replace("/Users/alice", "/Users/bob"))
                 if p.get("projectPath") else dict(p) for p in PLUGIN_LIST],
                [dict(m, path=m["path"].replace("/Users/alice", "/Users/bob"))
                 if m.get("path") else dict(m) for m in MARKETPLACE_LIST],
                "/Users/bob",
            )
            local_mcp = config.build_mcp_manifest(claude_json("/Users/bob"), "/Users/bob", set())

            for local, manifest, key_fn in (
                (local_plugins["plugins"], manifest_plugins["plugins"], config.plugin_key),
                (local_mcp["servers"], manifest_mcp["servers"], config.mcp_key),
            ):
                result = config.diff_entries(
                    local, manifest, key_fn, "/Users/bob", exists=lambda p: True
                )
                self.assertEqual(
                    {name: entries for name, entries in result.items() if entries}, {}
                )

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

    def test_entry_present_on_both_sides_is_never_project_missing(self):
        # 既に入っているものは導入する必要がないので、ディレクトリの所在は関係ない。
        entry = _plugin("a@m", scope="project", project="__HOME__/workspace/app")
        result = config.diff_entries(
            [dict(entry)], [entry], config.plugin_key, "/Users/alice", exists=lambda p: False
        )
        self.assertEqual(result["project_missing"], [])
        self.assertEqual(result["only_manifest"], [])
        self.assertEqual(result["differs"], [])

    def test_differing_entry_present_on_both_sides_is_differs(self):
        local = _plugin("a@m", scope="project", project="__HOME__/workspace/app", enabled=True)
        manifest = _plugin("a@m", scope="project", project="__HOME__/workspace/app", enabled=False)
        result = config.diff_entries(
            [local], [manifest], config.plugin_key, "/Users/alice", exists=lambda p: False
        )
        self.assertEqual(len(result["differs"]), 1)
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


class TestResolveMissingPaths(unittest.TestCase):
    def test_asks_once_per_distinct_path(self):
        entries = [
            _plugin("a@m", scope="project", project="__HOME__/workspace/app"),
            _plugin("b@m", scope="project", project="__HOME__/workspace/app"),
        ]
        asked = []

        def prompt(message):
            asked.append(message)
            return "/Users/bob/src/app"

        config.resolve_missing_paths(
            entries, "/Users/bob", {}, prompt, exists=lambda p: True
        )
        self.assertEqual(len(asked), 1)

    def test_learns_prefix_and_returns_mapping(self):
        entries = [_plugin("a@m", scope="project", project="__HOME__/workspace/app")]
        mapping = config.resolve_missing_paths(
            entries, "/Users/bob", {}, lambda message: "/Users/bob/src/app",
            exists=lambda p: True,
        )
        self.assertEqual(mapping, {"__HOME__/workspace": "__HOME__/src"})

    def test_blank_answer_skips_without_mapping(self):
        entries = [_plugin("a@m", scope="project", project="__HOME__/workspace/app")]
        mapping = config.resolve_missing_paths(
            entries, "/Users/bob", {}, lambda message: "", exists=lambda p: True
        )
        self.assertEqual(mapping, {})

    def test_falls_back_to_exact_mapping_when_no_common_suffix(self):
        entries = [_plugin("a@m", scope="project", project="__HOME__/workspace/app")]
        mapping = config.resolve_missing_paths(
            entries, "/Users/bob", {}, lambda message: "/Users/bob/elsewhere",
            exists=lambda p: True,
        )
        self.assertEqual(mapping, {"__HOME__/workspace/app": "__HOME__/elsewhere"})

    def test_no_prompt_callable_means_no_mapping(self):
        entries = [_plugin("a@m", scope="project", project="__HOME__/workspace/app")]
        self.assertEqual(config.resolve_missing_paths(entries, "/Users/bob", {}, None), {})

    def test_rejects_answer_whose_target_does_not_exist(self):
        entries = [_plugin("a@m", scope="project", project="__HOME__/workspace/app")]
        mapping = config.resolve_missing_paths(
            entries, "/Users/bob", {}, lambda message: "/Users/bob/src/app",
            exists=lambda p: False, log=lambda line: None,
        )
        self.assertEqual(mapping, {})

    def test_asks_before_extending_prefix_to_other_entries(self):
        entries = [
            _plugin("a@m", scope="project", project="__HOME__/workspace/app"),
            _plugin("b@m", scope="project", project="__HOME__/workspace/other"),
        ]
        asked = []
        config.resolve_missing_paths(
            entries, "/Users/bob", {}, lambda message: "/Users/bob/src/app",
            confirm=lambda message: (asked.append(message), True)[1],
            exists=lambda p: True,
        )
        self.assertEqual(len(asked), 1)
        self.assertIn("__HOME__/workspace", asked[0])
        self.assertIn("__HOME__/src", asked[0])

    def test_accepted_confirmation_applies_prefix_to_the_rest(self):
        entries = [
            _plugin("a@m", scope="project", project="__HOME__/workspace/app"),
            _plugin("b@m", scope="project", project="__HOME__/workspace/other"),
        ]
        prompted = []

        def prompt(message):
            prompted.append(message)
            return "/Users/bob/src/app"

        mapping = config.resolve_missing_paths(
            entries, "/Users/bob", {}, prompt,
            confirm=lambda message: True, exists=lambda p: True,
        )
        self.assertEqual(mapping, {"__HOME__/workspace": "__HOME__/src"})
        self.assertEqual(len(prompted), 1)

    def test_declined_confirmation_keeps_mapping_to_the_answered_path(self):
        entries = [
            _plugin("a@m", scope="project", project="__HOME__/workspace/app"),
            _plugin("b@m", scope="project", project="__HOME__/workspace/other"),
        ]
        answers = iter(["/Users/bob/src/app", ""])
        mapping = config.resolve_missing_paths(
            entries, "/Users/bob", {}, lambda message: next(answers),
            confirm=lambda message: False, exists=lambda p: True,
        )
        self.assertEqual(mapping, {"__HOME__/workspace/app": "__HOME__/src/app"})

    def test_does_not_confirm_when_no_other_entry_is_affected(self):
        entries = [_plugin("a@m", scope="project", project="__HOME__/workspace/app")]
        mapping = config.resolve_missing_paths(
            entries, "/Users/bob", {}, lambda message: "/Users/bob/src/app",
            confirm=lambda message: self.fail("適用先が他に無いのに確認した"),
            exists=lambda p: True,
        )
        self.assertEqual(mapping, {"__HOME__/workspace": "__HOME__/src"})


class TestRunCommand(unittest.TestCase):
    def test_dry_run_reports_without_executing(self):
        lines = []
        ok = config.run_command(
            ["plugin", "install", "a@m"], dry_run=True, log=lines.append,
        )
        self.assertTrue(ok)
        self.assertIn("claude plugin install a@m", lines[0])

    def test_returns_false_and_logs_when_executable_missing(self):
        lines = []
        ok = config.run_command(
            ["plugin", "install", "a@m"], log=lines.append,
            executable="claude-does-not-exist",
        )
        self.assertFalse(ok)
        self.assertTrue(any("claude-does-not-exist" in line for line in lines))


class TestImportConfig(unittest.TestCase):
    def _manifest_dir(self, tmp):
        plugins = {
            "marketplaces": [{"name": "m", "source": "github", "repo": "example-org/plugins"}],
            "plugins": [_plugin("a@m")],
        }
        mcp = {"servers": [{"name": "docs", "scope": "user",
                            "config": {"type": "http", "url": "https://mcp.example.com/mcp"}}]}
        config.write_manifest(Path(tmp), plugins, mcp)
        return Path(tmp)

    def test_dry_run_executes_nothing_and_lists_commands(self):
        lines = []
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = self._manifest_dir(tmp)
            code = config.import_config(
                manifest_dir, "/Users/bob", dry_run=True, no_prompt=True,
                environ={}, log=lines.append,
                collect=lambda d, h: ({"marketplaces": [], "plugins": []}, {"servers": []}),
            )
        self.assertEqual(code, 0)
        joined = "\n".join(lines)
        self.assertIn("plugin marketplace add example-org/plugins", joined)
        self.assertIn("mcp add-json docs", joined)

    def test_skips_server_with_unresolved_placeholder(self):
        lines = []
        with tempfile.TemporaryDirectory() as tmp:
            config.write_manifest(
                Path(tmp),
                {"marketplaces": [], "plugins": []},
                {"servers": [{"name": "docs", "scope": "user",
                              "config": {"type": "http", "url": "https://mcp.example.com/mcp",
                                         "headers": {"Authorization": "Bearer ${TOK}"}}}]},
            )
            code = config.import_config(
                Path(tmp), "/Users/bob", dry_run=True, no_prompt=True, environ={},
                log=lines.append,
                collect=lambda d, h: ({"marketplaces": [], "plugins": []}, {"servers": []}),
            )
        self.assertEqual(code, 1)
        self.assertTrue(any("TOK" in line for line in lines))

    def test_already_present_entry_is_not_reinstalled(self):
        lines = []
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = self._manifest_dir(tmp)
            local_plugins, local_mcp = config.load_manifest(manifest_dir)
            code = config.import_config(
                manifest_dir, "/Users/bob", dry_run=True, no_prompt=True, environ={},
                log=lines.append, collect=lambda d, h: (local_plugins, local_mcp),
            )
        self.assertEqual(code, 0)
        self.assertNotIn("plugin install", "\n".join(lines))

    def test_no_prompt_leaves_project_missing_unasked(self):
        lines = []
        with tempfile.TemporaryDirectory() as tmp:
            config.write_manifest(
                Path(tmp),
                {"marketplaces": [],
                 "plugins": [_plugin("a@m", scope="project", project="__HOME__/workspace/app")]},
                {"servers": []},
            )
            code = config.import_config(
                Path(tmp), "/Users/bob", dry_run=False, no_prompt=True, environ={},
                log=lines.append,
                collect=lambda d, h: ({"marketplaces": [], "plugins": []}, {"servers": []}),
                prompt=lambda message: self.fail("非対話なのに入力を求めた"),
            )
        self.assertEqual(code, 0)
        self.assertTrue(any("workspace/app" in line for line in lines))

    def _record_commands(self):
        """run_command を記録に差し替える。対話テストで実際の CLI を叩かないため。"""
        calls = []
        original = config.run_command

        def recorder(argv, cwd=None, dry_run=False, executable="claude", log=print):
            calls.append((argv, cwd))
            return True

        config.run_command = recorder
        self.addCleanup(setattr, config, "run_command", original)
        return calls

    def _missing_projects_manifest(self, tmp):
        config.write_manifest(
            Path(tmp),
            {"marketplaces": [],
             "plugins": [_plugin("a@m", scope="project", project="__HOME__/workspace/app"),
                         _plugin("b@m", scope="project", project="__HOME__/workspace/other")]},
            {"servers": []},
        )
        return Path(tmp)

    @staticmethod
    def _empty_local(manifest_dir, home):
        return {"marketplaces": [], "plugins": []}, {"servers": []}

    @staticmethod
    def _only_src_exists(path):
        return path.startswith("/Users/bob/src/")

    def test_interactive_declined_confirmation_remaps_only_the_answered_path(self):
        calls = self._record_commands()
        answers = iter(["/Users/bob/src/app", ""])
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = self._missing_projects_manifest(tmp)
            lines = []
            code = config.import_config(
                manifest_dir, "/Users/bob", environ={}, log=lines.append,
                collect=self._empty_local, exists=self._only_src_exists,
                prompt=lambda message: next(answers), confirm=lambda message: False,
            )
            saved = config.load_path_map(manifest_dir)
        self.assertEqual(code, 0)
        self.assertEqual(saved, {"__HOME__/workspace/app": "__HOME__/src/app"})
        self.assertEqual(calls, [(["plugin", "install", "a@m", "-s", "project", "-y"],
                                  "/Users/bob/src/app")])
        self.assertTrue(any("workspace/other" in line for line in lines))

    def test_interactive_accepted_confirmation_applies_prefix_to_the_rest(self):
        calls = self._record_commands()
        asked = []
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = self._missing_projects_manifest(tmp)
            code = config.import_config(
                manifest_dir, "/Users/bob", environ={}, log=lambda line: None,
                collect=self._empty_local, exists=self._only_src_exists,
                prompt=lambda message: (asked.append(message), "/Users/bob/src/app")[1],
                confirm=lambda message: True,
            )
            saved = config.load_path_map(manifest_dir)
        self.assertEqual(code, 0)
        self.assertEqual(len(asked), 1)
        self.assertEqual(saved, {"__HOME__/workspace": "__HOME__/src"})
        self.assertEqual(
            sorted(cwd for _, cwd in calls), ["/Users/bob/src/app", "/Users/bob/src/other"]
        )

    def test_interactive_rejects_answer_whose_target_does_not_exist(self):
        calls = self._record_commands()
        lines = []
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = self._missing_projects_manifest(tmp)
            code = config.import_config(
                manifest_dir, "/Users/bob", environ={}, log=lines.append,
                collect=self._empty_local, exists=lambda path: False,
                prompt=lambda message: "/Users/bob/src/app",
                confirm=lambda message: self.fail("実在しない回答なのに確認した"),
            )
            self.assertFalse((manifest_dir / config.PATH_MAP_NAME).exists())
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertTrue(any("存在しません" in line for line in lines))
        self.assertTrue(any("workspace/app" in line for line in lines))

    def test_interactive_blank_answer_skips_without_stopping_the_run(self):
        calls = self._record_commands()
        with tempfile.TemporaryDirectory() as tmp:
            config.write_manifest(
                Path(tmp),
                {"marketplaces": [],
                 "plugins": [_plugin("a@m", scope="project", project="__HOME__/workspace/app"),
                             _plugin("user@m")]},
                {"servers": []},
            )
            lines = []
            code = config.import_config(
                Path(tmp), "/Users/bob", environ={}, log=lines.append,
                collect=self._empty_local, exists=self._only_src_exists,
                prompt=lambda message: "", confirm=lambda message: True,
            )
            self.assertFalse((Path(tmp) / config.PATH_MAP_NAME).exists())
        self.assertEqual(code, 0)
        self.assertEqual(calls, [(["plugin", "install", "user@m", "-s", "user", "-y"], None)])
        self.assertTrue(any("workspace/app" in line for line in lines))

    def test_saved_path_map_is_reapplied_without_prompting(self):
        calls = self._record_commands()
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = self._missing_projects_manifest(tmp)
            config.save_path_map(manifest_dir, {"__HOME__/workspace": "__HOME__/src"})
            code = config.import_config(
                manifest_dir, "/Users/bob", environ={}, log=lambda line: None,
                collect=self._empty_local, exists=self._only_src_exists,
                prompt=lambda message: self.fail("保存済みの読み替えがあるのに尋ねた"),
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            sorted(cwd for _, cwd in calls), ["/Users/bob/src/app", "/Users/bob/src/other"]
        )

    def test_dry_run_never_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config.write_manifest(
                Path(tmp),
                {"marketplaces": [],
                 "plugins": [_plugin("a@m", scope="project", project="__HOME__/workspace/app")]},
                {"servers": []},
            )
            config.import_config(
                Path(tmp), "/Users/bob", dry_run=True, no_prompt=False, environ={},
                log=lambda line: None,
                collect=lambda d, h: ({"marketplaces": [], "plugins": []}, {"servers": []}),
                prompt=lambda message: self.fail("dry-run なのに入力を求めた"),
            )


if __name__ == "__main__":
    unittest.main()
