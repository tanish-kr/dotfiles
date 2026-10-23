"""Claude Code の会話履歴と各リポジトリの許可設定から、許可ルールの候補を集める。

ここでは数えるだけで、読み取り専用か書き込みかの判定はしない。判定は
コマンドの意味の理解が要るので、この結果を読む Claude 側に任せる。

user scope の settings.json を書き換える操作 (add / prune) も持つが、
どちらも書き換える前に元のファイルをバックアップする。
"""

import json
import os
import re
import shlex
import shutil
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import weekly_review

# サブコマンドまで含めて区別するコマンドと、その深さ。
# 例: gh は "gh issue view" まで見ないと読み取りか書き込みか分からない。
SUBCOMMAND_DEPTH = {
    "git": 1, "gh": 2, "docker": 1, "aws": 2, "gcloud": 2, "kubectl": 1,
    "npm": 1, "yarn": 1, "pnpm": 1, "bundle": 1, "brew": 1, "colima": 1,
    "launchctl": 1, "rails": 1, "bin/rails": 1, "rake": 1, "asdf": 1, "mise": 1,
    "terraform": 1, "cargo": 1, "go": 1, "uv": 1, "pip": 1, "pip3": 1,
}
# サブコマンドの後にさらにサブコマンドを取るもの。
NESTED = {("docker", "compose"): 1, ("bundle", "exec"): 1}
SUBCOMMAND_RE = re.compile(r"^[a-z][a-z0-9:_-]*$")
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
COMMAND_RE = re.compile(r"^[\w./~+-]+$")
OPERATORS = {"&&", "||", ";", "|", "&", "\n", "(", ")"}
# 後ろに続くのがコマンド本体になる構文の語。
LEADING_KEYWORDS = {"do", "then", "else", "if", "while", "until", "!", "time", "{"}
# それだけでコマンドを含まない構文の語。for の行は変数とリストだけ。
SKIP_KEYWORDS = {"for", "done", "fi", "esac", "case", "}", "elif"}
# サブコマンドより前に大域オプションを取るコマンド。オプションは読み飛ばし、
# ここに挙げたものは値も一緒に読み飛ばす。
GLOBAL_OPTIONS = {"git": {"-C", "-c"}}


class CandidateError(Exception):
    pass


def split_segments(command):
    """コマンド文字列を &&, ||, ;, |, 改行で区切った単純コマンドのトークン列にする。

    ヒアドキュメントの本文はコマンドではないので、<< を含むなら 1 行目だけを見る。
    解釈できないもの (閉じていない引用符など) は空を返す。
    """
    if "<<" in command:
        command = command.splitlines()[0] if command.strip() else ""
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    segments, current = [], []
    for token in tokens:
        if token in OPERATORS or set(token) <= set("|&;\n"):
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def command_key(tokens):
    """単純コマンドのトークン列から、許可ルールの単位になる接頭辞を作る。"""
    tokens = list(tokens)
    while tokens and (ASSIGNMENT_RE.match(tokens[0]) or tokens[0] in LEADING_KEYWORDS):
        tokens.pop(0)
    if tokens and tokens[0] in SKIP_KEYWORDS:
        return None
    options = GLOBAL_OPTIONS.get(tokens[0] if tokens else None)
    while options is not None and len(tokens) > 1 and tokens[1].startswith("-"):
        del tokens[1:3 if tokens[1] in options else 2]
    # リダイレクト (2>/dev/null など) は SUBCOMMAND_RE に合わないので、ここで除く必要はない。
    if not tokens or not COMMAND_RE.match(tokens[0]):
        return None
    words = [tokens[0]]
    depth = SUBCOMMAND_DEPTH.get(tokens[0], 0)
    rest = tokens[1:]
    while depth > 0 and rest and SUBCOMMAND_RE.match(rest[0]):
        words.append(rest.pop(0))
        depth -= 1
        depth += NESTED.get(tuple(words[-2:]), 0)
    return " ".join(words)


def bash_rule(key):
    return "Bash(%s *)" % key


def read_rule(path, cwd, home):
    """作業ディレクトリの外を読んだパスを、まとめた Read ルールにする。中なら None。"""
    path = os.path.normpath(path)
    if cwd and (path == cwd or path.startswith(cwd.rstrip("/") + "/")):
        return None
    home = home.rstrip("/")
    if path.startswith(home + "/"):
        parts = path[len(home) + 1:].split("/")
        # 兄弟のリポジトリ (作業ディレクトリと同じ親の下) はリポジトリ単位、それ以外は
        # ~/.docker のようなホーム直下のディレクトリ単位にまとめる。
        parent = os.path.dirname(cwd or "")
        depth = 1
        if parent.startswith(home + "/") and path.startswith(parent + "/"):
            depth = len(parent[len(home) + 1:].split("/")) + 1
        if len(parts) <= depth:
            return None
        return "Read(~/%s/**)" % "/".join(parts[:depth])
    parts = path.strip("/").split("/")
    if len(parts) < 2:
        return None
    depth = 2 if len(parts) > 2 else 1
    return "Read(//%s/**)" % "/".join(parts[:depth])


def read_rule_dir(rule, home):
    """Read(~/x/**) や Read(//x/**) が指すディレクトリ。"""
    inner = rule[len("Read("):-len("/**)")]
    if inner.startswith("~/"):
        return os.path.join(home, inner[2:])
    return inner[1:]


def tool_rules(name, tool_input, cwd, home):
    """1 回のツール呼び出しから、候補になるルールを返す。"""
    tool_input = tool_input or {}
    if name == "Bash":
        rules = []
        for segment in split_segments(tool_input.get("command", "")):
            key = command_key(segment)
            if key:
                rules.append(bash_rule(key))
        return rules
    if name.startswith("mcp__") or name == "WebSearch":
        return [name]
    if name == "WebFetch":
        host = urlparse(tool_input.get("url", "")).hostname
        return ["WebFetch(domain:%s)" % host] if host else []
    if name == "Read" and tool_input.get("file_path"):
        rule = read_rule(tool_input["file_path"], cwd, home)
        return [rule] if rule else []
    return []


def scan_history(projects, days, home, now=None):
    """直近 days 日の手で操作した会話から、ルールごとの使用回数を数える。"""
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    stats = {}
    session_count = 0
    for path in Path(projects).glob("*/*.jsonl"):
        if path.stat().st_mtime < cutoff:
            continue
        entrypoint, cwd, calls = None, None, []
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("type") not in ("user", "assistant") or record.get("isSidechain"):
                    continue
                entrypoint = entrypoint or record.get("entrypoint")
                cwd = cwd or record.get("cwd")
                if record["type"] != "assistant":
                    continue
                for item in (record.get("message") or {}).get("content") or []:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        calls.append((item.get("name") or "", item.get("input"), record.get("cwd") or cwd))
        if not weekly_review.is_interactive({"entrypoint": entrypoint}):
            continue
        session_count += 1
        for name, tool_input, call_cwd in calls:
            example = (tool_input or {}).get("command") if name == "Bash" else None
            for rule in tool_rules(name, tool_input, call_cwd, home):
                # 移行前のマシンのパスなど、もう無い場所への Read は候補にしない。
                if rule.startswith("Read(") and not os.path.isdir(read_rule_dir(rule, home)):
                    continue
                entry = stats.setdefault(rule, {"calls": 0, "sessions": set(), "repos": set(), "example": None})
                entry["calls"] += 1
                entry["sessions"].add(path.stem)
                if call_cwd:
                    entry["repos"].add(call_cwd)
                if example and entry["example"] is None:
                    entry["example"] = example.splitlines()[0][:200]
    return stats, session_count


def project_dirs(claude_json, extra=()):
    """許可設定を探すリポジトリの一覧。~/.claude.json の projects と会話に出た cwd。"""
    dirs = set(extra)
    try:
        with Path(claude_json).open(encoding="utf-8") as f:
            dirs.update((json.load(f).get("projects") or {}).keys())
    except (OSError, ValueError):
        pass
    return sorted(dirs)


def load_permissions(path):
    try:
        with Path(path).open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data.get("permissions") or {}


def scan_local(dirs):
    """各リポジトリの settings.local.json にある allow ルールを集める。"""
    found = {}
    for d in dirs:
        path = Path(d) / ".claude" / "settings.local.json"
        for rule in set(load_permissions(path).get("allow") or []):
            found.setdefault(rule, []).append(str(path))
    return found


def rule_regex(rule):
    """許可ルールを、それが通すルールを判定する正規表現にする。"""
    return re.compile("^" + ".*".join(re.escape(part) for part in rule.split("*")) + "$")


def covered(candidate, rules):
    """candidate が rules のどれかに含まれるか。"""
    for rule in rules:
        if rule == candidate or ("*" in rule and rule_regex(rule).match(candidate)):
            return True
    return False


def build_candidates(history, local, user_perms, min_sessions=2, min_repos=2):
    """user scope にまだ無いルールを、使用頻度の高い順に並べる。"""
    existing = []
    for key in ("allow", "deny", "ask"):
        existing.extend(user_perms.get(key) or [])
    rules = set(r for r, s in history.items() if len(s["sessions"]) >= min_sessions)
    rules.update(r for r, files in local.items() if len(files) >= min_repos)
    out = []
    for rule in rules:
        if covered(rule, existing):
            continue
        stat = history.get(rule) or {"calls": 0, "sessions": (), "repos": (), "example": None}
        out.append({
            "rule": rule,
            "calls": stat["calls"],
            "sessions": len(stat["sessions"]),
            "repos": len(stat["repos"]),
            "local_repos": len(local.get(rule, ())),
            "example": stat["example"],
        })
    out.sort(key=lambda c: (c["sessions"] + c["local_repos"] * 5, c["calls"]), reverse=True)
    return out


def find_duplicates(local, user_allow):
    """user scope の allow に含まれる、各リポジトリの allow ルールを返す。"""
    dups = {}
    for rule, files in local.items():
        if covered(rule, user_allow):
            for f in files:
                dups.setdefault(f, []).append(rule)
    return [{"file": f, "rules": sorted(r)} for f, r in sorted(dups.items())]


def backup(path, backup_dir):
    """書き換える前のファイルを backup_dir に退避し、退避先を返す。"""
    path = Path(path)
    if not path.exists():
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    dest = backup_dir / ("%s-%s-%s" % (stamp, path.parent.parent.name or "root", path.name))
    shutil.copy2(str(path), str(dest))
    return dest


def _load(path):
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        try:
            return json.load(f)
        except ValueError:
            raise CandidateError("JSON として読めません: %s" % path)


def _save(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def add_rules(settings_path, rules, backup_dir):
    """settings.json の permissions.allow にルールを足す。既にあるものは足さない。"""
    data = _load(settings_path)
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    added = [r for r in rules if r not in allow]
    if not added:
        return [], None
    saved = backup(settings_path, backup_dir)
    allow.extend(added)
    Path(settings_path).parent.mkdir(parents=True, exist_ok=True)
    _save(settings_path, data)
    return added, saved


def prune_rules(settings_path, rules, backup_dir):
    """settings.local.json の permissions.allow からルールを消す。"""
    data = _load(settings_path)
    allow = (data.get("permissions") or {}).get("allow") or []
    removed = [r for r in allow if r in rules]
    if not removed:
        return [], None
    saved = backup(settings_path, backup_dir)
    data["permissions"]["allow"] = [r for r in allow if r not in rules]
    _save(settings_path, data)
    return removed, saved
