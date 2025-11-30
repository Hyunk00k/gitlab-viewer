# GitLab Issue Viewer

GitLabのPersonal Access Token（PAT）でログインし、プロジェクトのIssueやEpicロードマップを閲覧・管理できるWebアプリケーションです。

## 主な機能

### 認証
- GitLab URL、PAT、デフォルトプロジェクトを入力してログイン
- セッションベースの認証管理

### Issue管理
- **Issue一覧**: プロジェクトのIssueをページネーション付きで表示
- **Issue詳細**: 本文、コメント、関連タスク、ラベルを表示
- **コメント投稿**: Issueにコメントを追加可能
- **幅調整機能**: Description表示エリアの幅を4段階で調整可能（狭く/通常/広く/全幅）

### ロードマップダッシュボード
- **Epic一覧**: グループ内のEpicを階層表示
- **進捗可視化**: 完了/進行中/合計のIssue数とプログレスバー
- **アコーディオン**: Epicをクリックして配下のIssue一覧を展開/折りたたみ
- **詳細情報**: 担当者、ラベル、期限日などを表示
- **内部リンク**: Issueをアプリ内で直接表示

> ⚠ セキュリティ注意: PATはFlaskセッションCookieに保存されます（署名済み、非暗号化）。  
> 本番環境ではHTTPS使用、`SESSION_COOKIE_SECURE=1`設定、Redis等のサーバーサイドセッション利用を推奨します。

## クイックスタート

```bash
cp .env.example .env

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run
```

http://127.0.0.1:5000 にアクセス → PATでログイン

## エンドポイント

- `GET /login` — ログインフォーム
- `POST /login` — トークン検証とセッション作成
- `GET /logout` — ログアウト
- `GET /projects/issues` — Issue一覧（`?project=<path or id>&page=n`）
- `GET /projects/<project_id>/issues/<iid>` — Issue詳細
- `POST /projects/<project_id>/issues/<iid>/comment` — コメント投稿
- `GET /projects/roadmap` — Epicロードマップダッシュボード

## 必要なスコープ

- **read_api** — Issue/コメント/Epic閲覧
- **api** — コメント投稿

## 技術スタック

- **バックエンド**: Flask（Python）
- **API**: GitLab REST API v4 + GraphQL
- **フロントエンド**: HTML/CSS/JavaScript
