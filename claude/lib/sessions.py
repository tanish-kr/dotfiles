"""Claude Code の会話 transcript をアーカイブし、別マシンへ復元する。

アーカイブ側はパスを書き換えず、元の $HOME を meta.json に記録するだけに
する。書き換えは import 側に一本化し、$HOME が同じならコストをゼロにする。

書き換えるのはディレクトリ名とトップレベルの cwd だけに限る。resume の
動作に必要なのはこの 2 つであり、transcript 本文に現れるパスは履歴として
忠実に残すべきだからである。
"""

import io
import json
import tarfile
import time
from datetime import datetime
from pathlib import Path

META_NAME = "meta.json"


def encode_project_dir(path):
    """作業ディレクトリのパスを projects/ 配下のディレクトリ名に変換する。

    Claude Code は "/" と "." を "-" に置き換える。この変換は不可逆だが、
    復元には元 $HOME のエンコード結果を新 $HOME のそれへ差し替えるだけで
    足りるため、デコードは必要ない。
    """
    return path.replace("/", "-").replace(".", "-")


def rewrite_dir_name(name, old_home, new_home):
    """projects/ 配下のディレクトリ名の $HOME 部分を差し替える。"""
    old = encode_project_dir(old_home)
    new = encode_project_dir(new_home)
    if name == old:
        return new
    if name.startswith(old + "-"):
        return new + name[len(old):]
    return name


def rewrite_jsonl_line(line, old_home, new_home):
    """transcript の 1 行のうち、トップレベルの cwd だけを書き換える。"""
    stripped = line.rstrip("\n")
    if not stripped:
        return line
    try:
        record = json.loads(stripped)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return line
    if not isinstance(record, dict):
        return line
    cwd = record.get("cwd")
    if not isinstance(cwd, str):
        return line
    if cwd == old_home:
        record["cwd"] = new_home
    elif cwd.startswith(old_home + "/"):
        record["cwd"] = new_home + cwd[len(old_home):]
    else:
        return line
    suffix = "\n" if line.endswith("\n") else ""
    return json.dumps(record, ensure_ascii=False) + suffix


def rewrite_jsonl_file(src, dest, old_home, new_home):
    """transcript を 1 行ずつ書き換えて別ファイルに書き出す。

    transcript にはコマンド出力がそのまま入るため不正な UTF-8 を含みうる。
    surrogateescape で読み書きし、復元できないバイト列もそのまま往復させる。
    """
    with open(src, "r", encoding="utf-8", errors="surrogateescape", newline="") as reader:
        with open(dest, "w", encoding="utf-8", errors="surrogateescape", newline="") as writer:
            for line in reader:
                writer.write(rewrite_jsonl_line(line, old_home, new_home))


class SessionError(Exception):
    """アーカイブまたは transcript ディレクトリを扱えなかった。"""


def scan_transcripts(projects, days, now=None):
    """transcript の id 集合を 2 つ返す。

    1 つ目は全件、2 つ目は日数条件を満たすもの。id は "<project>/<uuid>" の形。
    全件の集合は、<uuid>/ ディレクトリと memory/ のような普通のディレクトリを
    見分けるために要る。
    """
    projects = Path(projects)
    now = time.time() if now is None else now
    cutoff = None if days <= 0 else now - days * 86400
    all_ids, keep_ids = set(), set()
    for path in projects.glob("*/*.jsonl"):
        identifier = "%s/%s" % (path.parent.name, path.stem)
        all_ids.add(identifier)
        if cutoff is None or path.stat().st_mtime >= cutoff:
            keep_ids.add(identifier)
    return all_ids, keep_ids


def should_include(rel, all_ids, keep_ids):
    """アーカイブに入れるかを相対パスから判定する。

    transcript は日数で選別し、その兄弟ディレクトリは対応する transcript に
    従う。それ以外（memory/、.session-aliases など）は無条件で入れる。
    """
    if rel in (".", ""):
        return True
    parts = rel.split("/")
    if len(parts) == 1:
        return True
    if len(parts) == 2 and parts[1].endswith(".jsonl"):
        return "%s/%s" % (parts[0], parts[1][: -len(".jsonl")]) in keep_ids
    candidate = "%s/%s" % (parts[0], parts[1])
    if candidate in all_ids:
        return candidate in keep_ids
    return True


def _add_meta(tar, meta):
    payload = (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    info = tarfile.TarInfo(META_NAME)
    info.size = len(payload)
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(payload))


def export_sessions(projects, out_dir, days, home, now=None):
    """transcript をアーカイブし、(アーカイブのパス, transcript 数) を返す。"""
    projects = Path(projects)
    if not projects.is_dir():
        raise SessionError("transcript がありません: %s" % projects)
    all_ids, keep_ids = scan_transcripts(projects, days, now)
    if not keep_ids:
        raise SessionError("条件に合う transcript がありません (days: %d)" % days)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    archive = out_dir / ("claude-sessions-%s.tar.gz" % stamp)

    def select(info):
        rel = info.name[2:] if info.name.startswith("./") else info.name
        return info if should_include(rel, all_ids, keep_ids) else None

    with tarfile.open(archive, "w:gz") as tar:
        tar.add(projects, arcname=".", filter=select)
        _add_meta(tar, {
            "home": home,
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "transcripts": len(keep_ids),
        })
    return archive, len(keep_ids)
