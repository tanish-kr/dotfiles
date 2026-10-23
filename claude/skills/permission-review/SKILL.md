---
name: permission-review
description: Use when the user wants to review which Claude Code permission rules to add to their user-scope ~/.claude/settings.json based on their own session history, or to clean up per-repository settings.local.json allow entries that duplicate user-scope rules — e.g. '許可の候補を出して', 'permission を見直したい', '/permission-review'. Not for editing a single setting on request (use update-config).
---

# permission-review

会話履歴と各リポジトリの `settings.local.json` から許可ルールの候補を集め、利用者の承認を得たものだけを user scope (`~/.claude/settings.json`) に追加する。続けて、各リポジトリに残った重複エントリの掃除を提案する。

集計と書き換えは `~/.dotfiles/bin/claude-permission-candidates` が行う。このスキルの仕事は、候補の分類と利用者への確認である。

## 1. 集計する

```bash
mkdir -p ~/.claude/permission-review
~/.dotfiles/bin/claude-permission-candidates scan > ~/.claude/permission-review/scan.json
```

`scan.json` を Read で読む。`candidates` の各要素は次のとおり。

- `rule`: 許可ルール
- `sessions`: 使われた会話の数（直近 30 日）
- `calls`: 呼び出し回数
- `local_repos`: すでに「常に許可」しているリポジトリの数
- `example`: 実際のコマンド例

## 2. 分類する

各候補を次の 3 つに分ける。迷ったら安全側（書き込み系）に倒す。

- **読み取り専用**: 状態を変えず、外にも出ていかないもの。
  例: `git log` / `git status` / `git diff` / `gh issue view` / `gh pr view` / `ls` / `wc` / `head`、MCP の search・get・read・list 系、`WebSearch`、道具のディレクトリ（`~/.docker` や `/opt/homebrew` など）の Read。
- **書き込み・外部操作**: 状態を変える、外へ送る、任意のコードを実行できるもの。
  例: `git push` / `git commit` / `rm` / `curl` / `aws`、MCP の create・update・batch・run 系、`python3` / `bash` / `node` / `ruby` のようなインタプリタ。
  オプション次第で書き込めるもの（`sed -i`、`find -delete` / `-exec`、`xargs`、`awk` の `system()`）もここに入れる。
  `~/**` や `~/workspace/**` のように範囲が広すぎる Read もここに入れる。読み取りでも秘密情報まで読めてしまうため。
- **除外**: 許可しても意味がないもの、または集計のノイズ。
  例: 構文の断片、一度きりのスクリプト名、存在しないパス。

`gh issue *` のように、読み取りと書き込みが混ざった広いルールは、そのまま追加しない。読み取りのサブコマンド（`gh issue view *`、`gh issue list *`）に分けて読み取り専用に入れ、元の広いルールは書き込み系として扱う。

## 3. 読み取り専用を追加する

読み取り専用の候補を、番号付きの表で示す。列は「番号・ルール・会話数・リポジトリ数・例」。

続けて AskUserQuestion で 1 問だけ聞く。

- 「表の全件を追加」
- 「追加しない」
- 除外したい番号は Other に書いてもらう（例: `3, 7`）

承認されたルールを追加する。ルールは 1 つずつ引数として渡す。

```bash
~/.dotfiles/bin/claude-permission-candidates add 'Bash(git log *)' 'WebSearch' ...
```

## 4. 書き込み系を 1 件ずつ確認する

書き込み・外部操作の候補を表で示したうえで、会話数とリポジトリ数が多い順に、AskUserQuestion で **1 件ずつ** 追加するかどうかを聞く。1 回の呼び出しで 4 問まで、つまり 4 件ずつ聞ける。

- 質問文には、そのルールを許可すると何が確認なしで通るかを 1 行で書く。
  例: 「`git push *` を許可すると、force push や別リモートへの push も確認なしで通ります」
- 選択肢は「追加しない（推奨）」と「user scope に追加」の 2 つ。
- 12 件を聞いたら、残りも続けて聞くかどうかを確認する。

「user scope に追加」が選ばれたものだけを `add` で追加する。

## 5. 重複を掃除する

追加が終わったら、もう一度 `scan` を実行する。`duplicates` には「user scope の allow に含まれる、各リポジトリの `settings.local.json` のエントリ」が入っている。

ファイルごとに、消すルールを示す。そのうえで AskUserQuestion で「掃除する」か「残す」かを聞く。1 回の呼び出しで 4 ファイルまで聞ける。

「掃除する」が選ばれたファイルだけを処理する。

```bash
~/.dotfiles/bin/claude-permission-candidates prune <settings.local.json のパス> '<ルール>' ...
```

## 6. 報告する

最後に次を短く報告する。

- 追加したルール
- 掃除したファイルと件数
- バックアップの場所（コマンドの出力に出る `~/.claude/permission-review/backups/...`）

## 注意

- 承認されていないルールは、1 件も書き込まない。
- `settings.json` を Edit で直接書き換えない。必ずスクリプトの `add` / `prune` を使う。他の設定を壊さず、バックアップも取られるため。
- 判定に迷ったルールは、その理由を表に書き添える。
