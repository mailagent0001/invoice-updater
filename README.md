# invoice-updater

国税庁「適格請求書発行事業者公表サイト」の全件データ（CSV）を毎月自動ダウンロードし、
既存のGCSバケット（`keiriai-invoice-master`）にアップロードするツールです。

アップロード後は、別リポジトリで用意済みの Cloud Function
（`invoice_master/index.js`）が自動でBigQueryに取り込みます。
SQLite/DuckDB等への変換は行いません（BigQueryへの一本化で二重管理を避けています）。

## できること

- [x] STEP1〜4：国税庁サイトからのZIPダウンロード自動化（Playwrightで実ブラウザ操作）
- [x] 毎月自動実行（GitHub Actions cron）＋手動実行（workflow_dispatch）の両対応
- [x] ダウンロード後、既存のGCSバケットへ自動アップロード
- [ ] BigQueryへの取込・照会（→ 別リポジトリの `invoice_master` 側で対応済み）

## セットアップ手順

### 1. ローカルで動作確認する場合

```bash
pip install -r requirements.txt
playwright install --with-deps chromium

# ダウンロードのみ試す（アップロードなし）
python main.py --no-headless

# ダウンロード＋GCSアップロードまで試す
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
python main.py --upload --bucket keiriai-invoice-master
```

`--no-headless` を付けるとブラウザが実際に表示されるので、
サイト構造が変わってダウンロードが失敗する場合はここで様子を見てください。

### 2. GitHub Actionsで自動実行する場合

**① サービスアカウントを用意**

GCSバケット（`keiriai-invoice-master`）に書き込み権限を持つサービスアカウントを作成し、
JSON形式のキーを発行してください。

```bash
gcloud iam service-accounts create invoice-updater \
  --display-name="invoice-updater GitHub Actions"

gsutil iam ch \
  serviceAccount:invoice-updater@<PROJECT_ID>.iam.gserviceaccount.com:roles/storage.objectAdmin \
  gs://keiriai-invoice-master

gcloud iam service-accounts keys create key.json \
  --iam-account=invoice-updater@<PROJECT_ID>.iam.gserviceaccount.com
```

**② GitHubリポジトリにSecretsを登録**

リポジトリの Settings → Secrets and variables → Actions で、以下を登録してください。

| 名前 | 値 |
|---|---|
| `GCP_SA_KEY` | ①で発行した `key.json` の中身をそのまま貼り付け |
| `INVOICE_MASTER_BUCKET` | `keiriai-invoice-master` |

**③ 動作確認**

GitHubの「Actions」タブ →「Update Invoice Registration Master」→「Run workflow」で
手動実行して、正常にダウンロード・アップロードされるか確認してください。

問題なければ、あとは毎月3日に自動実行されます。

## 既知の制約・注意点

- 国税庁サイトのダウンロードリンクはJavaScriptで生成されているため、URLを直接指定せず
  実ブラウザ（Playwright）でクリックして辿る方式にしています。サイトのリニューアル等で
  構造が変わると失敗する可能性があるため、**失敗時はActionsのログと
  `debug-page-html` アーティファクト（保存されたページのHTML）を確認してください**。
- このコードは実際のサイトに対してテストできていません（開発環境からのアクセス制限のため）。
  初回は必ず手動実行（`workflow_dispatch`）で動作確認してから、自動実行に任せてください。
- 個人事業主のデータは、国税庁側の仕様により氏名・屋号等が2022年9月以降非公開（空文字）です。
