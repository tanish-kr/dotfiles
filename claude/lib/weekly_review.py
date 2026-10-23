"""直近の Claude Code の会話から、open な GitHub Issue に紐づくものを一覧にする。

会話と Issue の対応は、最初のプロンプトに書かれた Issue URL だけで決める。
ブランチ名の番号はどのリポジトリの Issue か特定できないので使わない。

launchd から /usr/bin/python3 (3.9) で動かすため、新しい構文は使わない。
"""

import calendar
import json
import os
import plistlib
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

ISSUE_RE = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/issues/(\d+)")
COMMAND_RE = re.compile(r"<command-name>/?([^<]+)</command-name>")

# 作業内容を表さない組み込みコマンド。/clear の直後に本題が来ることが多い。
SKIP_COMMANDS = {
    "clear", "exit", "compact", "resume", "mcp", "plugin", "model", "config",
    "login", "logout", "help", "status", "cost", "permissions", "doctor", "fast",
}
# コマンドの出力やシェル実行の記録は利用者のプロンプトではない。
SKIP_PREFIXES = ("<local-command", "<bash-input", "<bash-stdout", "<bash-stderr")


AGENT_LABEL = "local.claude-weekly-review"
# launchd はログインシェルの PATH を引き継がない。gh を見つけられるようにする。
AGENT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


class ReviewError(Exception):
    pass


def message_text(content):
    """message.content からテキスト部分だけを取り出す。tool_result だけなら空文字。"""
    if isinstance(content, str):
        return content
    parts = []
    for item in content or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join(parts)


def is_prompt(text):
    """作業の中身を表すプロンプトかどうか。"""
    stripped = text.strip()
    if not stripped or stripped.startswith(SKIP_PREFIXES):
        return False
    match = COMMAND_RE.search(stripped)
    if match and match.group(1).strip() in SKIP_COMMANDS:
        return False
    return True


def parse_transcript(lines):
    """transcript の行から一覧に必要な情報を集める。"""
    info = {
        "session_id": None, "cwd": None, "branch": None, "entrypoint": None,
        "title": None, "first_prompt": None, "last_reply": None, "last_at": None,
    }
    ai_title = custom_title = None
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        kind = record.get("type")
        if kind == "ai-title":
            ai_title = record.get("aiTitle") or ai_title
            continue
        if kind == "custom-title":
            custom_title = record.get("customTitle") or custom_title
            continue
        if kind not in ("user", "assistant") or record.get("isSidechain"):
            continue
        info["session_id"] = info["session_id"] or record.get("sessionId")
        info["cwd"] = info["cwd"] or record.get("cwd")
        info["branch"] = record.get("gitBranch") or info["branch"]
        info["entrypoint"] = info["entrypoint"] or record.get("entrypoint")
        info["last_at"] = record.get("timestamp") or info["last_at"]
        text = message_text((record.get("message") or {}).get("content"))
        if kind == "user":
            if info["first_prompt"] is None and not record.get("isMeta") and is_prompt(text):
                info["first_prompt"] = text
        elif text.strip():
            info["last_reply"] = text
    # 利用者が付けた名前を自動の題名より優先する。
    info["title"] = custom_title or ai_title
    return info


def is_interactive(info):
    """手で操作した会話か。SDK 経由の自動実行 (sdk-cli など) は除く。"""
    entrypoint = info.get("entrypoint") or ""
    return bool(entrypoint) and not entrypoint.startswith("sdk")


def find_issues(text):
    """テキスト中の Issue URL を、正規化した形で出現順に重複なく返す。"""
    seen = []
    for owner, repo, number in ISSUE_RE.findall(text or ""):
        url = "https://github.com/%s/%s/issues/%s" % (owner, repo, number)
        if url not in seen:
            seen.append(url)
    return seen


def collect_sessions(projects, days, now=None):
    """直近 days 日以内に更新された、手で操作した会話を返す。"""
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    sessions = []
    for path in Path(projects).glob("*/*.jsonl"):
        if path.stat().st_mtime < cutoff:
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            info = parse_transcript(f)
        info["session_id"] = info["session_id"] or path.stem
        if is_interactive(info):
            sessions.append(info)
    return sessions


def gh_issue(url):
    """gh で Issue の状態と題名を取る。取れなければ None。"""
    try:
        result = subprocess.run(
            ["gh", "issue", "view", url, "--json", "state,title"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def group_by_issue(sessions, fetch=gh_issue):
    """会話を Issue ごとにまとめる。closed の Issue は落とす。

    状態が取れなかった Issue は、黙って消さずに状態不明として残す。
    Issue は最も新しい会話の順、会話も新しい順に並べる。
    """
    by_url = {}
    for info in sessions:
        for url in find_issues(info.get("first_prompt")):
            by_url.setdefault(url, []).append(info)
    groups = []
    for url, members in by_url.items():
        issue = fetch(url)
        state = (issue or {}).get("state")
        if state == "CLOSED":
            continue
        members.sort(key=lambda s: s.get("last_at") or "", reverse=True)
        groups.append({
            "url": url,
            "title": (issue or {}).get("title"),
            "known": issue is not None,
            "sessions": members,
        })
    groups.sort(key=lambda g: g["sessions"][0].get("last_at") or "", reverse=True)
    return groups


def excerpt(text, max_lines=8, max_chars=600):
    """長い応答の先頭だけを残す。"""
    text = (text or "").strip()
    lines = text.splitlines()
    cut = "\n".join(lines[:max_lines])
    if len(cut) > max_chars:
        cut = cut[:max_chars]
    if cut != text:
        cut = cut.rstrip() + "\n…"
    return cut


def format_time(stamp):
    """ISO 8601 の UTC 時刻をローカル時刻の "MM-DD HH:MM" にする。"""
    if not stamp:
        return "-"
    try:
        moment = datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return stamp
    return datetime.fromtimestamp(calendar.timegm(moment.timetuple())).strftime("%m-%d %H:%M")


def quote(text):
    return "\n".join("> " + line if line else ">" for line in text.splitlines())


def render_markdown(groups, generated_at, days):
    """一覧を Markdown にする。"""
    out = [
        "# 作業途中の会話 (%s 作成, 直近 %d 日)" % (generated_at.strftime("%Y-%m-%d %H:%M"), days),
        "",
    ]
    if not groups:
        out += ["open な Issue に紐づく会話はありません。", ""]
        return "\n".join(out)
    for group in groups:
        title = group["title"] or "(題名を取得できませんでした)"
        out.append("## %s" % title)
        out.append("")
        out.append(group["url"] + ("" if group["known"] else " (状態不明: gh で取得できませんでした)"))
        out.append("")
        for info in group["sessions"]:
            out.append("### %s" % (info.get("title") or "(無題)"))
            out.append("")
            out.append("- session: `%s`" % info["session_id"])
            out.append("- 最終: %s" % format_time(info.get("last_at")))
            out.append("- 場所: `%s` (%s)" % (info.get("cwd") or "-", info.get("branch") or "-"))
            if info.get("cwd"):
                out.append("- 再開: `cd %s && claude --resume %s`" % (info["cwd"], info["session_id"]))
            out.append("")
            if info.get("last_reply"):
                out.append(quote(excerpt(info["last_reply"])))
                out.append("")
    return "\n".join(out)


def write_report(text, out_dir, generated_at):
    """日付付きのファイルと latest.md を書き、日付付きのほうのパスを返す。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dated = out_dir / ("%s.md" % generated_at.strftime("%Y-%m-%d"))
    for path in (dated, out_dir / "latest.md"):
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(str(tmp), str(path))
    return dated


def notify(message, title="Claude weekly review"):
    """macOS の通知を出す。失敗しても処理は止めない。"""
    script = "display notification %s with title %s" % (json.dumps(message), json.dumps(title))
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def build_agent(program_args, weekday, hour, minute, log_path):
    """launchd の LaunchAgent 定義を dict で返す。weekday は 0=日曜。"""
    return {
        "Label": AGENT_LABEL,
        "ProgramArguments": list(program_args),
        "StartCalendarInterval": {"Weekday": weekday, "Hour": hour, "Minute": minute},
        "EnvironmentVariables": {"PATH": AGENT_PATH},
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }


def agent_path(home):
    return Path(home) / "Library" / "LaunchAgents" / ("%s.plist" % AGENT_LABEL)


def install_agent(definition, plist_path, run=subprocess.run):
    """定義を書き出して launchd に登録する。既に登録済みなら入れ替える。

    ~/Library/LaunchAgents に置くユーザー単位のエージェントなので sudo は要らない。
    """
    plist_path = Path(plist_path)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    Path(definition["StandardOutPath"]).parent.mkdir(parents=True, exist_ok=True)
    with plist_path.open("wb") as f:
        plistlib.dump(definition, f)
    domain = "gui/%d" % os.getuid()
    run(["launchctl", "bootout", "%s/%s" % (domain, AGENT_LABEL)], capture_output=True)
    result = run(["launchctl", "bootstrap", domain, str(plist_path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise ReviewError("launchctl bootstrap に失敗しました: %s" % (result.stderr or "").strip())


def uninstall_agent(plist_path, run=subprocess.run):
    """launchd から外し、定義ファイルを消す。未登録でもエラーにしない。"""
    run(["launchctl", "bootout", "gui/%d/%s" % (os.getuid(), AGENT_LABEL)], capture_output=True)
    plist_path = Path(plist_path)
    if plist_path.exists():
        plist_path.unlink()
