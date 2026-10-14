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
| `config.json` | サイト名・ページのタイトルと説明文・ジャンルと「選び方のポイント」の文章 |
| `scripts/build.py` | 楽天からランキングを取ってきて、トップ・ジャンル別ページ・sitemap.xml などを作るプログラム |
| `site/style.css` | ページの見た目(色・レイアウト) |
| `site/app.js` | 価格帯・送料無料の絞り込み |
| `site/ogp.png` | SNSでシェアされたときに表示される画像 |
| `.github/workflows/update.yml` | 毎日の自動実行と公開の設定 |

## 文章を変えたいとき

各ページのタイトル・説明文・「選び方のポイント」は `config.json` に書いてあります。GitHub上で直接書き換えて保存すると、自動でページが作り直されます。

## Google Search Console の確認コード

所有権の確認には、Search Console からダウンロードした確認用ファイル `site/google0a0575c348633de9.html` を使っています。このファイルは消さないでください(消すと確認が外れます)。

HTMLタグで確認する場合は、`config.json` の `google_site_verification` に確認コード(`content="..."` の中身)を入れると、全ページに確認用のタグが入ります。

## ジャンルを変えたいとき

`config.json` の `genres` を書き換えます。`id` には楽天のジャンル番号、`slug` にはページのURLに使う英数字(例: `kaden` → `/kaden/`)を入れます。
楽天市場でカテゴリを開いたときの URL に含まれる数字(例: `https://www.rakuten.co.jp/category/558944/` の `558944`)がジャンル番号です。

## 必要な GitHub Secrets

| 名前 | 中身 |
| --- | --- |
| `RAKUTEN_APPLICATION_ID` | 楽天ウェブサービスのアプリID |
| `RAKUTEN_ACCESS_KEY` | 楽天ウェブサービスのアクセスキー |
| `RAKUTEN_AFFILIATE_ID` | 楽天アフィリエイトID |
