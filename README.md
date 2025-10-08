# B.League Schedule Scraper → Google Calendar CSV

Bリーグの試合日程を各チーム公式サイトからスクレイピングし、Googleカレンダーにインポート可能なCSVに変換します。検証用のCSV比較機能もあります。

## 必要環境
- Python 3.8+
- 依存パッケージ: `requests`, `beautifulsoup4`
  - インストール: `pip install requests beautifulsoup4`

## 使い方
- アルバルク東京（2025-10〜2026-05）
  ```bash
  python b_league_schedule_scraper.py scrape --team alvark --start 2025-10 --end 2026-05 --out alvark_2025_10_to_2026_05.csv
  ```
- サンロッカーズ渋谷（2025-10〜2026-05）
  ```bash
  python b_league_schedule_scraper.py scrape --team sunrockers --start 2025-10 --end 2026-05 --out sunrockers_2025_10_to_2026_05.csv
  ```
- 生成したCSVの検証
  ```bash
  python b_league_schedule_scraper.py validate --actual your.csv --expected golden.csv
  ```

## チーム・アリーナ設定データ
- プログラムが参照するチーム情報（表示名・スケジュールURL・HOMEアリーナ）とアリーナ情報（アリーナ名・HOMEチーム）は `data/team_data.json` にまとめています。
- 新しいチームを追加する場合は、JSON 内の `teams` と `arenas` セクションを更新してください。

## 出力CSVの列
- Subject, Start Date, Start Time, End Date, End Time, All Day Event, Location

## メモ
- スクレイピング対象ページの微細なレイアウト変更にも強いように、正規表現と複数のフォールバックを併用しています。
- 試合開始時刻が未定の場合は終日イベントとして出力します（Subject末尾に「※時刻未定」を付与）。
