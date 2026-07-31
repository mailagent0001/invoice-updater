"""
===== invoice-updater: 国税庁 適格請求書発行事業者 全件データ 自動ダウンロード =====

やること：
  1. https://www.invoice-kohyo.nta.go.jp/download/zenken を実際のブラウザ（Playwright）で開く
     → ダウンロードリンクはJavaScriptで生成されているため、実ブラウザで「クリック」して
       ダウンロードイベントを捕まえる方式にする（URLを直接推測しない）
  2. CSV形式の「法人」「人格のない社団等」「個人」の全ダウンロードボタンを順にクリックしてzipを取得
  3. ダウンロードしたzipを ./downloads/ に保存
  4. --upload オプション指定時は、そのまま既存のGCSバケット（keiriai-invoice-master/incoming/）に
     アップロードする（アップロード後は、既存のCloud Function（invoice_master/index.js）が
     自動でBigQueryに取り込む。SQLite/DuckDB等への変換は不要＝二重に仕組みを作らない）

前提：
  pip install -r requirements.txt
  playwright install chromium
"""

import argparse
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DOWNLOAD_PAGE = "https://www.invoice-kohyo.nta.go.jp/download/zenken"
DOWNLOAD_DIR = Path(__file__).parent / "downloads"


def download_all_csv_files(headless: bool = True) -> list[Path]:
    """CSV形式の全ダウンロードボタン（法人5分割・人格のない社団等1・個人5分割）をクリックし、
    保存したファイルパスの一覧を返す。"""
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    saved_files: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(accept_downloads=True)
        page.goto(DOWNLOAD_PAGE, wait_until="networkidle")

        # 「CSV形式」の見出しの直後にある表（法人／人格のない社団等／個人の3行）を対象にする。
        # サイト構造の変更に強くするため、id誘導ではなく見出しテキストからの相対探索にしている。
        csv_heading = page.locator("h2, h3", has_text="CSV形式").first
        csv_heading.scroll_into_view_if_needed()

        # 見出し以降・次の見出し（XML形式）より前にある <a> タグのみを対象にする
        csv_section = page.locator("xpath=//h2[contains(text(),'CSV形式')]/following::table[1]")
        links = csv_section.locator("a")
        count = links.count()
        print(f"CSV形式のダウンロードリンクを {count} 件検出しました。")

        if count == 0:
            print("★ リンクが見つかりませんでした。サイト構造が変わっている可能性があります。")
            print("  ページのHTMLを downloads/page_debug.html に保存するので確認してください。")
            DOWNLOAD_DIR.mkdir(exist_ok=True)
            (DOWNLOAD_DIR / "page_debug.html").write_text(page.content(), encoding="utf-8")
            browser.close()
            return saved_files

        for i in range(count):
            link = links.nth(i)
            label = link.inner_text().strip()
            print(f"  [{i+1}/{count}] クリック: {label}")
            try:
                with page.expect_download(timeout=60000) as download_info:
                    link.click()
                download = download_info.value
                # ファイル名は国税庁側の命名規則（h_all_作成年月日_csv_連番.zip 等）をそのまま使う
                dest = DOWNLOAD_DIR / download.suggested_filename
                download.save_as(dest)
                saved_files.append(dest)
                print(f"      → 保存完了: {dest.name} ({dest.stat().st_size / 1024:.0f} KB)")
            except Exception as e:
                print(f"      ★ ダウンロード失敗: {label} ({e})")
            time.sleep(1)  # サイトへの連続アクセス負荷を軽減

        browser.close()

    return saved_files


def upload_to_gcs(files: list[Path], bucket_name: str) -> None:
    """既存のGCSバケットのincoming/フォルダにアップロードする。
    アップロード後は既存のCloud Function（invoice_master/index.js）が自動でBigQueryに取り込む。"""
    from google.cloud import storage  # 遅延importでrequirements最小化

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    for f in files:
        blob_path = f"incoming/{f.name}"
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(str(f))
        print(f"  GCSへアップロード完了: gs://{bucket_name}/{blob_path}")


def main():
    parser = argparse.ArgumentParser(description="国税庁 適格請求書発行事業者 全件データ 自動ダウンロード")
    parser.add_argument("--upload", action="store_true", help="ダウンロード後にGCSへアップロードする")
    parser.add_argument("--bucket", default=os.environ.get("INVOICE_MASTER_BUCKET", "keiriai-invoice-master"),
                         help="アップロード先GCSバケット名")
    parser.add_argument("--no-headless", action="store_true", help="ブラウザを表示して動作確認する（デバッグ用）")
    args = parser.parse_args()

    print("===== ダウンロード開始 =====")
    files = download_all_csv_files(headless=not args.no_headless)

    if not files:
        print("ダウンロードできたファイルがありませんでした。処理を終了します。")
        sys.exit(1)

    print(f"===== ダウンロード完了：{len(files)}件 =====")
    for f in files:
        print(" -", f.name)

    if args.upload:
        print("===== GCSへアップロード開始 =====")
        upload_to_gcs(files, args.bucket)
        print("===== アップロード完了 =====")
    else:
        print("（--upload オプションが無いため、GCSへのアップロードはスキップしました）")

    print("ダウンロード成功")


if __name__ == "__main__":
    main()
