import unittest

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


if __name__ == "__main__":
    unittest.main()
