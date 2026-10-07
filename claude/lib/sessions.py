"""Claude Code の会話 transcript をアーカイブし、別マシンへ復元する。

アーカイブ側はパスを書き換えず、元の $HOME を meta.json に記録するだけに
する。書き換えは import 側に一本化し、$HOME が同じならコストをゼロにする。

書き換えるのはディレクトリ名とトップレベルの cwd だけに限る。resume の
動作に必要なのはこの 2 つであり、transcript 本文に現れるパスは履歴として
忠実に残すべきだからである。
"""

import json

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
