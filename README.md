# 楽天ランキングサイト

一人暮らし・学生向けの便利グッズを、楽天市場のジャンル別ランキングから毎日自動で更新して表示するサイトです。

公開URL: https://ike012012-sketch.github.io/rakuten-ranking/

## しくみ

- 毎日 日本時間の朝6時ごろ、GitHub が自動で楽天からランキングを取ってきて、ページを作り直します。
- 「Actions」画面の「Run workflow」ボタンで、好きなときに手動で更新することもできます。
- AI は使っていません。

## ファイルの役割

| ファイル | 役割 |
| --- | --- |
| `config.json` | サイト名・表示するジャンル・各ジャンルの表示件数の設定 |
| `scripts/build.py` | 楽天からランキングを取ってきてページを作るプログラム |
| `site/style.css` | ページの見た目(色・レイアウト) |
| `.github/workflows/update.yml` | 毎日の自動実行と公開の設定 |

## ジャンルを変えたいとき

`config.json` の `genres` を書き換えます。`id` には楽天のジャンル番号を入れます。
楽天市場でカテゴリを開いたときの URL に含まれる数字(例: `https://www.rakuten.co.jp/category/558944/` の `558944`)がジャンル番号です。

## 必要な GitHub Secrets

| 名前 | 中身 |
| --- | --- |
| `RAKUTEN_APPLICATION_ID` | 楽天ウェブサービスのアプリID |
| `RAKUTEN_ACCESS_KEY` | 楽天ウェブサービスのアクセスキー |
| `RAKUTEN_AFFILIATE_ID` | 楽天アフィリエイトID |
