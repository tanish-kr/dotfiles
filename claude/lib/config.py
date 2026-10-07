"""Claude Code の MCP / plugin 設定を manifest と相互変換する。

manifest はマシン非依存であるべきなので、$HOME は __HOME__ トークンに
正規化し、資格情報は ${PLACEHOLDER} に置き換えてから書き出す。

将来 PyPI パッケージとして公開する可能性がある。そのため、このモジュールの
関数は argparse.Namespace を受け取らず、Path / str / bool といった素の値で
引数を受ける。公開時に動かすのは bin/ 側の argparse 定義だけで済み、この
モジュールは変更不要になる。移行作業は lib/ をパッケージ化して
[project.scripts] を宣言すること、$HOME/Desktop などの macOS 前提を外すこと、
サポートする Python バージョンの下限を決めることの 3 点。
"""

import json
import os
import re
import subprocess
from pathlib import Path

HOME_TOKEN = "__HOME__"

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_AUTH_SCHEMES = ("Bearer", "Basic", "Token")


def normalize_home(value, home):
    """$HOME で始まるパスを __HOME__ トークンに置き換える。"""
    if not isinstance(value, str):
        return value
    if value == home:
        return HOME_TOKEN
    if value.startswith(home + "/"):
        return HOME_TOKEN + value[len(home):]
    return value


def localize_home(value, home):
    """__HOME__ トークンをこのマシンの $HOME に戻す。"""
    if not isinstance(value, str):
        return value
    if value == HOME_TOKEN:
        return home
    if value.startswith(HOME_TOKEN + "/"):
        return home + value[len(HOME_TOKEN):]
    return value


def placeholder_name(server, key):
    """${...} に入れる環境変数名を作る。"""
    return _NON_ALNUM.sub("_", "%s_%s" % (server, key)).strip("_").upper()


def redact_env(server, env, plain_keys, home):
    """env の値を placeholder に置き換える。

    plain_keys に "<server>/<key>" が含まれるキーだけ実値を残す。既定で
    すべて伏せるため、新しいサーバを足したときに秘密を見落とすことがない。
    """
    result = {}
    for key, value in (env or {}).items():
        if "%s/%s" % (server, key) in plain_keys:
            result[key] = normalize_home(value, home)
        else:
            result[key] = "${%s}" % placeholder_name(server, key)
    return result


def redact_headers(server, headers):
    """headers の値を placeholder に置き換える。認証スキームだけ残す。

    ヘッダは定義上ほぼ資格情報なので allowlist は設けない。
    """
    result = {}
    for key, value in (headers or {}).items():
        ref = "${%s}" % placeholder_name(server, key)
        scheme = value.split(" ", 1)[0] if isinstance(value, str) else ""
        if scheme in _AUTH_SCHEMES:
            result[key] = "%s %s" % (scheme, ref)
        else:
            result[key] = ref
    return result


class ClaudeCliError(Exception):
    """claude CLI またはその設定ファイルを読めなかった。"""


_MARKETPLACE_ID_KEYS = ("repo", "url", "path")


def build_plugins_manifest(plugin_list, marketplace_list, home):
    """claude plugin list --json / marketplace list --json を manifest に変換する。

    version や installPath はこのマシン固有の状態なので捨てる。
    """
    marketplaces = []
    for entry in marketplace_list or []:
        item = {"name": entry["name"], "source": entry.get("source")}
        for key in _MARKETPLACE_ID_KEYS:
            if entry.get(key):
                item[key] = normalize_home(entry[key], home) if key == "path" else entry[key]
                break
        marketplaces.append(item)
    marketplaces.sort(key=lambda m: m["name"])

    plugins = []
    for entry in plugin_list or []:
        item = {"id": entry["id"], "scope": entry.get("scope", "user")}
        if entry.get("projectPath"):
            item["projectPath"] = normalize_home(entry["projectPath"], home)
        item["enabled"] = bool(entry.get("enabled"))
        plugins.append(item)
    plugins.sort(key=lambda p: (p["scope"], p["id"], p.get("projectPath", "")))

    return {"marketplaces": marketplaces, "plugins": plugins}


def _redact_server(name, server_config, plain_keys, home):
    clean = {}
    for key, value in (server_config or {}).items():
        if key == "headers" and isinstance(value, dict):
            clean[key] = redact_headers(name, value)
        elif key == "env" and isinstance(value, dict):
            clean[key] = redact_env(name, value, plain_keys, home)
        elif key == "args" and isinstance(value, list):
            clean[key] = [normalize_home(v, home) for v in value]
        else:
            clean[key] = normalize_home(value, home)
    return clean


def build_mcp_manifest(claude_json, home, plain_keys):
    """~/.claude.json の MCP サーバ定義を manifest に変換する。"""
    servers = []
    for name, server_config in (claude_json.get("mcpServers") or {}).items():
        servers.append({
            "name": name,
            "scope": "user",
            "config": _redact_server(name, server_config, plain_keys, home),
        })
    for project, state in (claude_json.get("projects") or {}).items():
        for name, server_config in ((state or {}).get("mcpServers") or {}).items():
            servers.append({
                "name": name,
                "scope": "local",
                "projectPath": normalize_home(project, home),
                "config": _redact_server(name, server_config, plain_keys, home),
            })
    servers.sort(key=lambda s: (s["scope"], s["name"], s.get("projectPath", "")))
    return {"servers": servers}


def run_claude_json(args, executable="claude"):
    """claude CLI を呼び、その JSON 出力を返す。"""
    try:
        completed = subprocess.run(
            [executable] + list(args),
            capture_output=True, text=True, check=False,
        )
    except OSError as error:
        raise ClaudeCliError(
            "%s を実行できません。PATH を確認してください (%s)" % (executable, error)
        ) from error
    if completed.returncode != 0:
        raise ClaudeCliError(
            "%s %s が失敗しました: %s"
            % (executable, " ".join(args), completed.stderr.strip() or completed.returncode)
        )
    try:
        return json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as error:
        raise ClaudeCliError(
            "%s %s の出力を JSON として読めません: %s" % (executable, " ".join(args), error)
        ) from error


def read_claude_json(path):
    """~/.claude.json を読む。無ければ空の設定として扱う。"""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ClaudeCliError("%s を JSON として読めません: %s" % (path, error)) from error


def load_plain_env(manifest_dir):
    """実値のまま残す env キーの allowlist を読む。無ければ空。"""
    path = Path(manifest_dir) / "plain-env.json"
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as error:
        raise ClaudeCliError("%s を JSON として読めません: %s" % (path, error)) from error


def collect_local(manifest_dir, home):
    """このマシンの状態から plugins / mcp manifest を組み立てる。"""
    plain_keys = load_plain_env(manifest_dir)
    plugins = build_plugins_manifest(
        run_claude_json(["plugin", "list", "--json"]),
        run_claude_json(["plugin", "marketplace", "list", "--json"]),
        home,
    )
    mcp = build_mcp_manifest(read_claude_json(Path(home) / ".claude.json"), home, plain_keys)
    return plugins, mcp


def _write_json(path, payload):
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_manifest(manifest_dir, plugins, mcp):
    """manifest を書き出す。ディレクトリが無ければ作る。"""
    manifest_dir = Path(manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, payload in (("plugins.json", plugins), ("mcp.json", mcp)):
        path = manifest_dir / name
        _write_json(path, payload)
        written.append(path)
    return written


def _read_json(path):
    if not path.exists():
        raise ClaudeCliError("%s がありません。先に export を実行してください" % path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ClaudeCliError("%s を JSON として読めません: %s" % (path, error)) from error


PATH_MAP_NAME = "path-map.json"


def load_path_map(manifest_dir):
    """projectPath の読み替え表を読む。無ければ空。"""
    path = Path(manifest_dir) / PATH_MAP_NAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ClaudeCliError("%s を JSON として読めません: %s" % (path, error)) from error


def save_path_map(manifest_dir, mapping):
    """読み替え表を保存する。再実行時に同じ質問を繰り返さないため。"""
    manifest_dir = Path(manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    _write_json(manifest_dir / PATH_MAP_NAME, mapping)


def apply_path_map(path, mapping):
    """読み替え表をパスに適用する。最長一致で 1 度だけ置き換える。"""
    if not mapping:
        return path
    for old in sorted(mapping, key=len, reverse=True):
        if path == old:
            return mapping[old]
        if path.startswith(old + "/"):
            return mapping[old] + path[len(old):]
    return path


def learn_prefix(old, new):
    """1 件の読み替えから共通プレフィックスの差を導く。

    "__HOME__/workspace/<project>" -> "__HOME__/src/<project>" のように末尾が
    一致していれば ("__HOME__/workspace", "__HOME__/src") を返す。
    """
    old_parts = old.split("/")
    new_parts = new.split("/")
    shared = 0
    while (
        shared < len(old_parts) - 1
        and shared < len(new_parts) - 1
        and old_parts[-1 - shared] == new_parts[-1 - shared]
    ):
        shared += 1
    if shared == 0:
        return None
    return "/".join(old_parts[: len(old_parts) - shared]), "/".join(
        new_parts[: len(new_parts) - shared]
    )


def load_manifest(manifest_dir):
    """manifest ディレクトリから plugins / mcp を読む。"""
    manifest_dir = Path(manifest_dir)
    if not manifest_dir.is_dir():
        raise ClaudeCliError("%s がありません。先に export を実行してください" % manifest_dir)
    return _read_json(manifest_dir / "plugins.json"), _read_json(manifest_dir / "mcp.json")


def plugin_key(entry):
    return (entry["id"], entry.get("scope", "user"), entry.get("projectPath", ""))


def mcp_key(entry):
    return (entry["name"], entry.get("scope", "user"), entry.get("projectPath", ""))


def resolved_project_path(entry, home, path_map):
    """manifest の projectPath を、このマシンの実パスへ解決する。"""
    raw = entry.get("projectPath")
    if not raw:
        return None
    return localize_home(apply_path_map(raw, path_map or {}), home)


def diff_entries(local, manifest, key_fn, home, path_map=None, exists=None):
    """正規化済みの 2 つのエントリ列を比べる。

    local 側は collect_local() を通した manifest 空間の形であることが前提。
    実値と placeholder を直接比べると常に差分になるため、ここで生の状態を
    受け取ってはならない。
    """
    if exists is None:
        exists = os.path.isdir
    local_by_key = {key_fn(e): e for e in local}
    manifest_by_key = {key_fn(e): e for e in manifest}

    result = {"only_manifest": [], "only_local": [], "differs": [], "project_missing": []}
    for key, entry in manifest_by_key.items():
        target = resolved_project_path(entry, home, path_map)
        if target is not None and not exists(target):
            result["project_missing"].append(entry)
        elif key not in local_by_key:
            result["only_manifest"].append(entry)
        elif local_by_key[key] != entry:
            result["differs"].append(entry)
    for key, entry in local_by_key.items():
        if key not in manifest_by_key:
            result["only_local"].append(entry)
    return result
