"""Claude Code の MCP / plugin 設定を manifest と相互変換する。

manifest はマシン非依存であるべきなので、$HOME は __HOME__ トークンに
正規化し、資格情報は ${PLACEHOLDER} に置き換えてから書き出す。

ただし manifest は「資格情報が無いファイル」ではない。伏せる範囲は次のとおりで、
これを誤解したまま持ち出さないこと。

- env と headers の値は無条件で ${PLACEHOLDER} になる。既知のキー以外も値ごと
  伏せるので、設定スキーマにキーが増えても既定で漏れない
- url / command / args は設計上そのままの実値が残る。args は --api-key <値> の
  ような形で資格情報を含みうる

したがって manifest を共有する前には中身を目で確認する。資格情報を含むサーバは
manifest から手で除外する運用とする。

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
_ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)\}")


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
        name = entry.get("name") if isinstance(entry, dict) else None
        if not name:
            raise ClaudeCliError(
                "marketplace の一覧に name が無いエントリがあります: %r" % (entry,)
            )
        item = {"name": name, "source": entry.get("source")}
        for key in _MARKETPLACE_ID_KEYS:
            if entry.get(key):
                item[key] = normalize_home(entry[key], home) if key == "path" else entry[key]
                break
        else:
            # ここで止めないと、識別子を失った marketplace が manifest に入り、
            # 失敗するのは import を走らせた別マシンになる。
            raise ClaudeCliError(
                "marketplace %s に repo/url/path がありません。export できません" % name
            )
        marketplaces.append(item)
    marketplaces.sort(key=lambda m: m["name"])

    plugins = []
    for entry in plugin_list or []:
        identifier = entry.get("id") if isinstance(entry, dict) else None
        if not identifier:
            raise ClaudeCliError("plugin の一覧に id が無いエントリがあります: %r" % (entry,))
        item = {"id": identifier, "scope": entry.get("scope", "user")}
        if entry.get("projectPath"):
            item["projectPath"] = normalize_home(entry["projectPath"], home)
        item["enabled"] = bool(entry.get("enabled"))
        plugins.append(item)
    plugins.sort(key=lambda p: (p["scope"], p["id"], p.get("projectPath", "")))

    return {"marketplaces": marketplaces, "plugins": plugins}


# 実値のまま manifest に残すキー。これ以外はすべて placeholder にする。
_REAL_VALUE_KEYS = ("type", "url", "command", "args")


def _redact_server(name, server_config, plain_keys, home):
    """サーバ設定を manifest 空間へ落とす。既知のキー以外は値を伏せる。

    分岐を網羅的にし、どの枝にも当たらない値は placeholder にする。CLI の
    設定スキーマにキーが増えても、既定で伏せられるので秘密が漏れない。
    """
    clean = {}
    for key, value in (server_config or {}).items():
        placeholder = "${%s}" % placeholder_name(name, key)
        if key == "headers":
            clean[key] = redact_headers(name, value) if isinstance(value, dict) else placeholder
        elif key == "env":
            clean[key] = (
                redact_env(name, value, plain_keys, home)
                if isinstance(value, dict) else placeholder
            )
        elif key == "args":
            clean[key] = (
                [normalize_home(v, home) for v in value]
                if isinstance(value, list) else normalize_home(value, home)
            )
        elif key in _REAL_VALUE_KEYS:
            clean[key] = normalize_home(value, home)
        else:
            clean[key] = placeholder
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


def expand_env_refs(value, environ):
    """${VAR} を environ の値で置き換え、未解決の変数名を返す。"""
    if not isinstance(value, str):
        return value, []
    missing = []

    def substitute(match):
        name = match.group(1)
        if name in environ:
            return environ[name]
        missing.append(name)
        return match.group(0)

    return _ENV_REF.sub(substitute, value), missing


def expand_server_config(server_config, home, environ):
    """manifest の config を、このマシンで実行できる形に戻す。"""
    missing = []

    def convert(value):
        if isinstance(value, str):
            expanded, gaps = expand_env_refs(localize_home(value, home), environ)
            missing.extend(gaps)
            return expanded
        if isinstance(value, list):
            return [convert(v) for v in value]
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        return value

    return convert(server_config), sorted(set(missing))


def marketplace_argv(entry, home):
    """claude plugin marketplace add に渡す引数を作る。"""
    for key in _MARKETPLACE_ID_KEYS:
        if entry.get(key):
            source = localize_home(entry[key], home) if key == "path" else entry[key]
            return ["plugin", "marketplace", "add", source]
    raise ClaudeCliError("marketplace %s に repo/url/path がありません" % entry.get("name"))


def plugin_argv(entry):
    """claude plugin install に渡す引数を作る。"""
    return ["plugin", "install", entry["id"], "-s", entry.get("scope", "user"), "-y"]


def plugin_disable_argv(entry):
    return ["plugin", "disable", entry["id"]]


def mcp_argv(entry, server_config):
    """claude mcp add-json に渡す引数を作る。

    config をそのまま JSON で渡すので、http か stdio かで分岐する必要がない。
    """
    return [
        "mcp", "add-json", entry["name"],
        json.dumps(server_config, ensure_ascii=False),
        "-s", entry.get("scope", "user"),
    ]


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


def _require_records(payload, key, identifier, path):
    """manifest の 1 セクションがリストで、各要素が識別子を持つことを確かめる。

    ここで止めないと、壊れた manifest が差分計算の奥で KeyError になり、
    どのファイルのどこが悪いのか分からないまま traceback で終わる。
    """
    records = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise ClaudeCliError("%s に %s のリストがありません" % (path, key))
    for record in records:
        if not isinstance(record, dict) or not record.get(identifier):
            raise ClaudeCliError(
                "%s の %s に %s が無いエントリがあります: %r" % (path, key, identifier, record)
            )
    return records


def load_manifest(manifest_dir):
    """manifest ディレクトリから plugins / mcp を読む。形式も検査する。"""
    manifest_dir = Path(manifest_dir)
    if not manifest_dir.is_dir():
        raise ClaudeCliError("%s がありません。先に export を実行してください" % manifest_dir)
    plugins_path = manifest_dir / "plugins.json"
    mcp_path = manifest_dir / "mcp.json"
    plugins, mcp = _read_json(plugins_path), _read_json(mcp_path)
    _require_records(plugins, "marketplaces", "name", plugins_path)
    _require_records(plugins, "plugins", "id", plugins_path)
    _require_records(mcp, "servers", "name", mcp_path)
    return plugins, mcp


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


def _confirm_from_prompt(prompt):
    """[Y/n] の問い合わせを prompt の上に組み立てる。"""
    def confirm(message):
        return not prompt(message).strip().lower().startswith("n")
    return confirm


def resolve_missing_paths(
    entries, home, path_map, prompt, confirm=None, exists=None, log=print,
):
    """見つからない projectPath を対話的に解決し、読み替え表を返す。

    同じパスは 1 度しか尋ねない。回答の実在を確かめてから採用し、1 件の回答から
    導いた共通プレフィックスを残りのエントリにも適用してよいかを確認する。
    読み替え表は保存されるため、確認なしに広げると以後の実行まで巻き込む。
    """
    if prompt is None:
        return {}
    if exists is None:
        exists = os.path.isdir
    if confirm is None:
        confirm = _confirm_from_prompt(prompt)
    learned = {}
    asked = set()
    for entry in entries:
        raw = entry.get("projectPath")
        if not raw or raw in asked:
            continue
        if apply_path_map(raw, learned) != raw:
            continue
        asked.add(raw)
        answer = prompt("%s が見つかりません。新しいパス（空 Enter でスキップ）: " % raw).strip()
        if not answer:
            continue
        normalized = normalize_home(os.path.expanduser(answer).rstrip("/"), home)
        if not exists(localize_home(normalized, home)):
            log("  ! %s は存在しません。このエントリはスキップします" % normalized)
            continue
        pair = learn_prefix(raw, normalized)
        if pair:
            others = sorted(
                {e.get("projectPath") for e in entries if e.get("projectPath")}
                - asked
            )
            affected = [p for p in others if apply_path_map(p, {pair[0]: pair[1]}) != p]
            if affected and not confirm(
                "  同じ読み替え %s → %s を残り %d 件にも適用しますか? [Y/n]: "
                % (pair[0], pair[1], len(affected))
            ):
                pair = None
        if pair:
            learned[pair[0]] = pair[1]
        else:
            learned[raw] = normalized
    return learned


def run_command(argv, cwd=None, dry_run=False, executable="claude", log=print):
    """claude CLI を 1 回実行する。失敗しても例外にせず False を返す。"""
    shown = "%s %s" % (executable, " ".join(argv))
    if dry_run:
        log("  [dry-run] %s" % shown)
        return True
    log("  %s" % shown)
    try:
        completed = subprocess.run([executable] + list(argv), cwd=cwd, check=False)
    except OSError as error:
        log("  ! 実行できません: %s (%s)" % (shown, error))
        return False
    if completed.returncode != 0:
        log("  ! 失敗 (終了コード %d): %s" % (completed.returncode, shown))
        return False
    return True


def export_config(manifest_dir, home):
    """このマシンの状態を manifest に書き出す。"""
    plugins, mcp = collect_local(manifest_dir, home)
    return write_manifest(manifest_dir, plugins, mcp)


def _report(log, label, entries, describe):
    if not entries:
        return
    log("%s (%d)" % (label, len(entries)))
    for entry in entries:
        log("  %s" % describe(entry))


def _describe_plugin(entry):
    suffix = " @ %s" % entry["projectPath"] if entry.get("projectPath") else ""
    return "%s [%s]%s" % (entry["id"], entry.get("scope", "user"), suffix)


def _describe_mcp(entry):
    suffix = " @ %s" % entry["projectPath"] if entry.get("projectPath") else ""
    return "%s [%s]%s" % (entry["name"], entry.get("scope", "user"), suffix)


def _diffs(manifest_dir, home, path_map, collect, exists=None):
    # manifest を先に読む。ディレクトリが無いときに claude CLI を呼ばずに済む。
    manifest_plugins, manifest_mcp = load_manifest(manifest_dir)
    local_plugins, local_mcp = collect(manifest_dir, home)
    plugin_diff = diff_entries(
        local_plugins["plugins"], manifest_plugins["plugins"], plugin_key, home,
        path_map, exists,
    )
    mcp_diff = diff_entries(
        local_mcp["servers"], manifest_mcp["servers"], mcp_key, home, path_map, exists
    )
    return manifest_plugins, plugin_diff, mcp_diff


def status_config(manifest_dir, home, log=print, collect=None, exists=None):
    """ローカル状態と manifest の差分を表示する。"""
    collect = collect or collect_local
    path_map = load_path_map(manifest_dir)
    _, plugin_diff, mcp_diff = _diffs(manifest_dir, home, path_map, collect, exists)
    for label, diff, describe in (
        ("plugins", plugin_diff, _describe_plugin),
        ("mcp", mcp_diff, _describe_mcp),
    ):
        log("== %s ==" % label)
        _report(log, "manifest のみ", diff["only_manifest"], describe)
        _report(log, "ローカルのみ", diff["only_local"], describe)
        _report(log, "内容が異なる", diff["differs"], describe)
        _report(log, "プロジェクト未配置", diff["project_missing"], describe)
    total = sum(len(v) for diff in (plugin_diff, mcp_diff) for v in diff.values())
    if total == 0:
        log("差分はありません")
    return 0


def import_config(
    manifest_dir, home, dry_run=False, no_prompt=False,
    environ=None, prompt=None, confirm=None, log=print, collect=None, exists=None,
):
    """manifest の内容をこのマシンに導入する。追加のみで、削除はしない。"""
    collect = collect or collect_local
    environ = os.environ if environ is None else environ
    interactive = not dry_run and not no_prompt and prompt is not None
    path_map = load_path_map(manifest_dir)

    manifest_plugins, plugin_diff, mcp_diff = _diffs(
        manifest_dir, home, path_map, collect, exists
    )

    if interactive:
        missing = plugin_diff["project_missing"] + mcp_diff["project_missing"]
        learned = resolve_missing_paths(
            missing, home, path_map, prompt, confirm=confirm, exists=exists, log=log
        )
        if learned:
            path_map = dict(path_map)
            path_map.update(learned)
            save_path_map(manifest_dir, path_map)
            manifest_plugins, plugin_diff, mcp_diff = _diffs(
                manifest_dir, home, path_map, collect, exists
            )

    failures = 0

    log("== marketplaces ==")
    for entry in manifest_plugins["marketplaces"]:
        if not run_command(marketplace_argv(entry, home), dry_run=dry_run, log=log):
            failures += 1

    log("== plugins ==")
    for entry in plugin_diff["only_manifest"]:
        cwd = resolved_project_path(entry, home, path_map)
        if not run_command(plugin_argv(entry), cwd=cwd, dry_run=dry_run, log=log):
            failures += 1
            continue
        if not entry.get("enabled", True):
            if not run_command(plugin_disable_argv(entry), cwd=cwd, dry_run=dry_run, log=log):
                failures += 1

    log("== mcp ==")
    for entry in mcp_diff["only_manifest"]:
        expanded, missing = expand_server_config(entry["config"], home, environ)
        if missing:
            failures += 1
            log("  ! %s をスキップ: %s が未設定です" % (entry["name"], ", ".join(missing)))
            log("    設定後に再実行してください")
            continue
        cwd = resolved_project_path(entry, home, path_map)
        if not run_command(mcp_argv(entry, expanded), cwd=cwd, dry_run=dry_run, log=log):
            failures += 1

    skipped = plugin_diff["project_missing"] + mcp_diff["project_missing"]
    if skipped:
        log("== プロジェクト未配置のためスキップ ==")
        for entry in skipped:
            log("  %s" % entry.get("projectPath"))
        log("  リポジトリを配置してから再実行してください")

    return 1 if failures else 0


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
        # ローカルにあるかを先に見る。既にあるものは導入しようがないので、
        # projectPath の所在は関係ない。project_missing は「入れたいのに
        # 作業ディレクトリが無い」エントリだけを指す。
        if key in local_by_key:
            if local_by_key[key] != entry:
                result["differs"].append(entry)
            continue
        target = resolved_project_path(entry, home, path_map)
        if target is not None and not exists(target):
            result["project_missing"].append(entry)
        else:
            result["only_manifest"].append(entry)
    for key, entry in local_by_key.items():
        if key not in manifest_by_key:
            result["only_local"].append(entry)
    return result
