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

import re

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
