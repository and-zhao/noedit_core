<p align="center"><img src="img/logo.svg" alt="NoEdit Core" width="96"></p>

<h1 align="center">NoEdit Core</h1>

<p align="center">
  <b>PPT を作るための Agent Skill。</b><br>
  <code>noedit-core</code> を skill 対応のエージェントにインストールして、あとは要望を伝えるだけ —— 要素 JSON はエージェントが書き、この skill が描画して
  <b>pptx · pdf · html · png · svg</b> に書き出します。
</p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh-CN.md">简体中文</a> |
  <b>日本語</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/export-pptx%20%7C%20pdf%20%7C%20png%20%7C%20svg%20%7C%20html-success?style=flat-square" alt="Export">
  <img src="https://img.shields.io/badge/icons-1800%2B-orange?style=flat-square" alt="Icons">
</p>

<p align="center"><b>最小構成の PPT 作成コア</b>：素の Python パッケージで複数ページのキャンバス（スライド）を作り、pptx / pdf / html / png / svg に書き出せます。</p>

**主な特徴**

- **pptx** 形式で超高精細に書き出し、劣化なし
- **編集可能性**を最大限に保持
- **マイクロシーン**モジュールが動的な効果を生み出す（世界初）
- フルセットの**ベクターツール**と **1800+ のベクターライブラリ**で、PPT を「文字 + カード + 画像」の形式から解放
- 強力な**科学図作成**能力：統計図、フローチャート、アーキテクチャ図、トポロジ図……すべて対応

**スコープ**：プロジェクトの読み書き、ページと要素の追加・変更・削除、20 種のグラフ、ベクター図形（shape / path / connector）、
**内蔵のベクターアイコンライブラリ**（1800+ アイコン。検索して挿入すると編集可能な `path` 要素になる）、表 / コード / 数式、
プロジェクト内ローカル素材、5 種類の書き出し形式、そして**内蔵のブラウザエディタ**（ローカルでサーバーを起動し、ブラウザで開くだけで
プレビューと、要素を選んでのプロパティ編集ができる）。要素アニメーション（`anim`）とマイクロシーン（`scene`）——
**HTML は必ず動く。PPTX でもマイクロシーンは動く**（コアが自動でフレームを取り込み GIF を埋め込む）。PDF / PNG / SVG は静止フレームになります。

**含まれないもの**：AI によるコンテンツの自動生成（シーンコード / カバーフレームを含む）、グローバル素材ライブラリ、テンプレート、
スクリーンショット検証、デスクトップクライアント。（マイクロシーンで使う内蔵 JS ライブラリは、必要に応じて**ネットワークから
ローカルキャッシュへダウンロード**して使います。`install_scene_lib` を参照。）

## デモ

<p align="center">
  <img src="img/NoEdit_core%E6%BC%94%E7%A4%BA%E5%9B%BE.png" alt="NoEdit Core デモ" width="100%">
</p>

<p align="center">
  <img src="img/slide1.png" width="24%">
  <img src="img/slide2.png" width="24%">
  <img src="img/slide3.png" width="24%">
  <img src="img/slide4.png" width="24%">
</p>

## NoEdit · フルバージョン

> **NoEdit** は **NoEdit_core** のフルバージョンで、すぐに使えます。

アーキテクチャには **MCP** 構造を採用し、外部エージェントに PPT 生成サービスを提供できます。内部では
**メインエージェント + サブエージェント**方式を採用し、PPT 生成時間を大幅に短縮するとともに、キャッシュヒット
戦略を最大限に最適化してトークンを節約します。

**フルデスクトップ版**

- 並列サブエージェントアーキテクチャによる超高速な生成
- よりトークンを節約する戦略
- 内蔵のプロフェッショナル agent アシスタントによる 1 対 1 の最適化
- より強力な手動編集・修正機能と滑らかな操作性
- 手動の科学図作成ツールとインタラクションを一式
- 科学図の模写（トレース）ツール（AI + 手動）
- 開いてすぐ使える、超簡単な設定（NoEdit_core と比較して）
- ビジュアル素材管理、テンプレート
- プラグイン機構：プラグインを自作・インストールでき、柔軟に設定可能
- 下層まで調整可能：ツール、MCP、skill、workflow、team、権限管理、キャンバス設定……無限の可能性
- ……さらに多くの強力な機能が、あなたの探索を待っています

<p align="center">
  <img src="img/%E8%BD%AF%E4%BB%B6%E5%85%A8%E8%B2%8C.png" alt="NoEdit ソフト全体像" width="100%">
</p>

<table>
  <tr>
    <td width="48%" valign="top">
      <img src="img/%E7%9F%A2%E9%87%8F%E5%BA%93.png" alt="ベクターライブラリ" width="100%">
      <img src="img/%E5%B1%9E%E6%80%A7%E9%9D%A2%E6%9D%BF.png" alt="プロパティパネル" width="100%">
      <img src="img/%E4%B8%B4%E6%91%B9%E6%A8%A1%E5%BC%8F.png" alt="模写モード" width="100%">
    </td>
    <td width="52%" valign="top">
      <img src="img/%E6%8F%92%E4%BB%B6%E6%9C%BA%E5%88%B6.png" alt="プラグイン機構" width="100%">
    </td>
  </tr>
</table>

<h2 align="center">
  <a href="https://www.bilibili.com/video/BV1hQHZ6uEiT">クリックして視聴 — 本プロジェクトが生み出す驚きの効果</a>
</h2>

<p align="center">
  <a href="https://www.bilibili.com/video/BV1hQHZ6uEiT">
    <img src="https://img.shields.io/badge/%E2%96%B6%20WATCH%20THE%20DEMO-BILIBILI-FB7299?style=for-the-badge&logo=bilibili&logoColor=white" alt="Bilibili でデモを見る" width="440">
  </a>
</p>

<p align="center">
  <video src="img/NoEdit%E4%B8%80%E5%8F%A5%E8%AF%9D%E7%94%9F%E6%88%90ppt.mp4" controls width="720"></video>
</p>

## ディレクトリ構成

```
noedit_core/
├─ main.py                 # CLI エントリ（python main.py <サブコマンド>）
├─ img/                    # README 用画像（logo.svg など）
├─ noedit_core/
│  ├─ api.py               # 公開 API（import が必要な唯一のモジュール）
│  ├─ cli.py               # コマンドライン実装
│  ├─ server.py            # ローカル HTTP サーバー（ブラウザ UI のバックエンド：静的ファイル + /api/call + /canvas プレビュー）
│  ├─ ui/                  # 内蔵ブラウザ UI（index.html + app.css + app.js + i18n.js）
│  └─ core/                # コア実装：projects / export / actions / element_schema /
│                          #   assets / icon_catalog / shape_outline / connector_geom / store ...
│  └─ web/                 # レンダリング時の資産：element-schema.json、icon-catalog*.json、render-kit、katex
├─ skill/                  # Agent Skill：このコアの使い方（SKILL.md + references/）
└─ tests/smoke.py          # エンドツーエンドのスモークテスト
```

## 動作環境

- **Python 3.10+**（`X | Y` 型構文と `from __future__ import annotations` を使用）
- 書き出しの依存：
  - `pptx` → **python-pptx**（必須）
  - `pdf` / `png` / `svg` → ローカルに **Edge または Chrome**（ヘッドレスレンダリング）

```bash
pip install python-pptx
```

## クイックスタート

### ブラウザ UI（サーバーを起動してブラウザで開く）

```bash
python main.py serve --project D:\work\report     # 起動後に http://127.0.0.1:8760/ を開く
```

`--project` を省略した場合は、まず `http://127.0.0.1:8760/` を開き、ランディングページでプロジェクトフォルダを**新規作成**または**開く**。

UI の機能：ページ / 要素リスト、キャンバスプレビュー（キャンバス内の要素をクリックすると選択される）、プロパティパネル
（x / y / w / h、テキスト、色、フォントサイズ、重ね順、不透明度などを編集）、要素とページの追加・削除、素材のインポート、
書き出し（HTML / PPTX / PDF / PNG / SVG）。プレビューは**書き出しと同じレンダラー**を使うため WYSIWYG。変更は即座にディスクへ
保存され、プレビューが更新されます。データは同じ `project.manifest.json` に保存され、API / CLI と完全に相互運用できます。

UI は**簡体字中国語 / English / 日本語**に対応（既定は簡体字中国語、選択はローカルに記憶されます）。
左側の「ページ」と「要素」パネルは既定で半分ずつ、境界をドラッグして高さを変更できます。列の幅も
ドラッグで変更でき（境界線をダブルクリックで既定に戻る）、列幅とキャンバスの拡大率はウィンドウサイズに追従します。
キャンバス上でホイールを回すとページを切り替えられます。プロジェクトを開いているときは、
「新規作成 / 開く」パネルを背景クリック・閉じるボタン・Esc キーで閉じて編集画面に戻れます。

#### ローカル UI の HTTP エンドポイント

サーバーはループバックのみで待ち受け、**単一プロセス・単一プロジェクト**です。上記の画面に加えて、
エージェント（や他のツール）が現在のプロジェクトを切り替え、プロジェクト設定を操作できる小さな
HTTP API を公開しています：

| エンドポイント | リクエストボディ | 戻り値 |
| --- | --- | --- |
| `GET /api/ping` | — | `{"ok":true,"app":"..."}`（死活監視） |
| `GET /api/ui/current` | — | `{"ok":true,"result":{"project":<ディレクトリ>\|null,"name","type","port","url"}}` |
| `POST /api/ui/open` | `{"path":"<プロジェクトディレクトリ>"}`（`?path=` も可） | 実行中の UI をそのプロジェクトに切り替え（再起動不要） |
| `POST /api/call` | `{"method":"<メソッド名>","args":[...]}` | `{"ok":true,"result":...}` または `{"ok":false,"message":"..."}` |
| `GET /canvas?page=<0 始まり>` | — | 現在のプロジェクトのページを書き出しと同じレンダラーで描画 |

`POST /api/call` は**プロジェクト設定 / プロジェクト切替 / ディレクトリ閲覧**用のメソッド群
（`ping`、`state`、`create_project`、`open_project`、`close_project`、`get_settings`、`set_default_dir`、
`browse_roots`、`browse_dir`、`upload_asset`）を自身で処理し、**それ以外のメソッドは `noedit_core.api` へ転送**します
（プロジェクトの `path` が第 1 引数）。例：`{"method":"insert","args":["D:\\work\\report", {...}, 0]}`。

デフォルトディレクトリ（新規プロジェクトの親フォルダ / ディレクトリツリーの起点 / 書き出し先）は
`data/settings.json` に保存されます。実行中のサーバーは発見用に `data/ui.json`
（`{app, version, host, port, url, pid, project, startedAt}`）も書き出します。強制終了後は古い内容が
残り得るため、ポートを取得したらまず `GET /api/ping` で確認してください。

完全なシグネチャと戻り値の構造は [skill/references/api.md](skill/references/api.md) の「本地 UI 服务」節を参照。

### コマンドライン

```bash
python main.py create "四半期報告" --dir D:\work
python main.py insert D:\work\report --json "{\"type\":\"text\",\"props\":{\"text\":\"タイトル\"}}"
python main.py export D:\work\report --fmt pptx
```

すべてのサブコマンドは JSON を出力します。エラー時はエラーを表示し、0 以外の終了コードを返します。

| サブコマンド | 説明 |
| --- | --- |
| `serve [--host] [--port] [--project] [--open]` | ローカル UI サーバーを起動（ブラウザで URL を開けばプレビュー / 編集） |
| `create <name> --dir <親ディレクトリ> [--preset] [--type]` | プロジェクトを新規作成 |
| `open <path>` | 概要 + アウトライン |
| `types` | 要素タイプと modelNote を一覧 |
| `pages <path>` / `add-page <path>` | ページ一覧 / ページ追加 |
| `elements <path> [--page] [--full]` | 要素を一覧 |
| `insert <path> --json <要素 JSON> [--page]` | 挿入 |
| `update <path> --props <ドットパス JSON> [--id/--match]` | 更新 |
| `delete <path> [--id/--match]` | 削除 |
| `reorder <path> [--index/--front/--back] [--id/--match]` | 重ね順 |
| `asset-add <path> <ファイル...>` / `assets <path>` | 素材のインポート / 一覧 |
| `icon-groups` / `icon-list <グループ> [--limit]` | ベクターアイコン：グループ一覧 / グループ内のアイコン一覧 |
| `icon-search [キーワード] [--group] [--limit]` | ベクターアイコンを検索（英語名 / id / 中国語グループ名に一致） |
| `icon-insert <path> <アイコンid> [--x/--y/--size/--color/--page]` | アイコンを挿入（編集可能な `path` 要素を生成） |
| `export <path> [--fmt] [--out] [--pages] [--dpi] [--transparent] [--no-scene-gif]` | 書き出し |
| `scene-libs` / `scene-lib-add [id]` / `scene-lib-remove <id>` | マイクロシーンライブラリ：一覧 / ダウンロード / 削除 |
| `scene-gif <path> [--id/--match] [--fps] [--scale] [--opaque]` | 単一シーンをキャプチャして GIF を書き出し |

### Python

```python
import sys
sys.path.insert(0, r"D:\NoEdit\noedit_core")
from noedit_core import api

p = api.create_project("四半期報告", r"D:\work")
path = p["path"]

# 1 ページ目（新規プロジェクトに付属する空白ページ）に表紙を書く
api.insert(path, {"type": "text", "x": 80, "y": 60, "w": 900, "h": 80,
                  "props": {"text": "2025 年 第4四半期 振り返り"},
                  "style": {"fontSize": 40, "fontWeight": "700"}}, page_index=0)

# 2 ページ目を追加して画像を配置
api.add_page(path, name="データ")
rec = api.import_asset(path, [r"D:\pics\chart.png"])["imported"][0]
api.insert(path, {"type": "image", "x": 80, "y": 100, "w": 500, "h": 300,
                  "props": {"src": rec["relPath"], "fit": "cover"}}, page_index=1)

api.export(path, "pptx")
```

## API 一覧

| 関数 | 役割 |
| --- | --- |
| `create_project(name, parent_dir, preset="ppt-16:9", ptype="ppt")` | プロジェクトを新規作成 |
| `open_project(path)` | 開く：概要 + アウトライン + プレビュー URL |
| `canvas(path)` / `list_pages(path)` / `add_page(path, ...)` | キャンバス / ページ |
| `update_page(path, props, ..., all_pages=False)` / `delete_page(path, index)` | ページプロパティの変更（背景 / ページ名）/ ページ削除 |
| `list_elements(path, page_index=-1, full=False)` | 要素を一覧 |
| `insert(path, element, page_index=0, ...)` | 要素を挿入 |
| `update(path, props, element_id="", match=None, ...)` | 更新（props はドットパス） |
| `delete(path, element_id="", match=None, ...)` / `reorder(path, ...)` | 削除 / 重ね順 |
| `import_asset(path, source_paths)` / `list_assets(path)` | プロジェクト内ローカル素材 |
| `icon_groups()` / `icon_list(group="", limit=200)` | ベクターアイコン：グループ概要 / グループ内の一覧 |
| `icon_search(keyword="", group="", limit=40)` | ベクターアイコンを検索 |
| `icon_insert(path, icon_id, x=None, y=None, size=150, color="#2f6fed", ...)` | アイコンを挿入（単色 → `path` 1 個；多色 → `group` コンテナ + レイヤー構成のメンバー） |
| `export(path, fmt="pptx", out_dir="", scene_gifs=None, **options)` | 書き出し（pptx はマイクロシーンの GIF を自動で埋め込む） |
| `scene_libs()` / `install_scene_lib(lib_id="")` / `remove_scene_lib(lib_id)` | マイクロシーンライブラリ：一覧 / ダウンロード / 削除 |
| `export_scene_gif(path, ...)` / `compose_scene_gif(path, frames, ...)` | 単一シーンをキャプチャして GIF 化 / 既存フレームから GIF を合成 |
| `element_types()` | 要素タイプ + modelNote |

完全なシグネチャ、戻り値の構造、フィールド辞書は [`skill/references/`](skill/references/) を参照：

- [api.md](skill/references/api.md) — API の完全なシグネチャと戻り値の構造
- [element-schema.md](skill/references/element-schema.md) — 12 種類の要素のフィールド辞書
- [export.md](skill/references/export.md) — 書き出しの詳細と依存関係
- [design-recipes.md](skill/references/design-recipes.md) — 用語 / タイポグラフィ / 6 種の配色 / レイアウト / 装飾 / 図の構成
- [page-templates.md](skill/references/page-templates.md) — ベースボード + 5 種のページ型の要素ごとの座標
- [sci-vector-drawing.md](skill/references/sci-vector-drawing.md) — 科学図とベクター描画のハードルール
- [vector-playbook.md](skill/references/vector-playbook.md) — ベクター機能の実践ガイド
- [diagram-atlas.md](skill/references/diagram-atlas.md) — 分野横断の原理図アトラス

## Agent Skill として使う

このリポジトリは、そのまま自己完結型の **Agent Skill**（名前は `noedit-core`）としてインストールできます。
skill 対応のエージェントに入れれば、あとは要望を伝えるだけで、エージェントが要素 JSON を書き、
CLI / API を叩いて PPT を作り上げます。

**インストール**

```bash
python packaging/build_skill.py     # dist/noedit-core/ と dist/noedit-core-skill.zip を生成
```

`noedit-core/` フォルダごと skills ルートに置きます：

- グローバル：`~/.trae-cn/skills/noedit-core/`
- プロジェクト単位：`<プロジェクト>/.trae/skills/noedit-core/`

フォルダ名は `noedit-core` のままにしてください（`SKILL.md` の frontmatter にある `name` と一致必須）。
実行データ（`settings.json` / `ui.json` / ロック）は既定で `~/.noedit_core/` に、既定のプロジェクト
フォルダは skill フォルダの**隣**に作られます。`NOEDIT_CORE_ROOT` / `NOEDIT_CORE_PROJECTS` で上書きできます。

**使い方** —— インストール後は、エージェントに要望を伝えるだけです（例：「X についての 10 ページの PPT を作って pptx で書き出して」）。
エージェントは [`skill/SKILL.md`](skill/SKILL.md) に従って進めます。要点は 3 つ：

1. **書くのはエージェント自身** — コアはコンテンツを生成しません。要素 JSON はエージェントが書きます。
2. **「動く」もの：HTML は必ず動き、PPTX ではマイクロシーンも動く** — 要素アニメーション（`anim`）とマイクロシーン（`scene`）は HTML 書き出しで動作します。PPTX ではマイクロシーンをコアが自動でフレーム合成し GIF を埋め込みます。PDF / PNG / SVG は静止フレーム（マイクロシーンは `props.poster` を使用）。
3. **素材はプロジェクト内のローカルコピーのみ** — `import_asset` の後、`relPath` を `props.src` に書き込めば、プロジェクトフォルダごと持ち運べます。

## セルフテスト

```bash
python tests/smoke.py
```

一連の流れを実行：プロジェクト作成 → 3 種類の要素を挿入 → 更新 → ページ追加 → 素材インポート → 重ね順 / 削除 →
HTML / PPTX 書き出し（マイクロシーンの自動フレーム取り込み GIF を含む）→ ローカル UI サーバーのセルフチェック
（`/api/ping`、`/api/call` の追加・変更・削除、`/canvas` プレビュー）→ ベクターアイコンライブラリ（グループ / 検索 /
単色・多色の挿入）。出力は `_smoke_out/`（削除可）。最後に `SMOKE OK` と表示されれば成功です。

## 著者

**趙佳楽（Zhao Jiale）** —— 中国科学院大学 計算機技術修士

Email：andzhaojiale@163.com
