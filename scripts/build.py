#!/usr/bin/env python3
"""楽天市場ランキングAPIからジャンル別ランキングを取得し、静的サイトを生成する。

使い方:
  python3 scripts/build.py           # 楽天APIから取得して _site/ に出力
  python3 scripts/build.py --sample  # APIを使わずダミーデータで見た目だけ確認

必要な環境変数 (GitHub Secrets から渡す):
  RAKUTEN_APPLICATION_ID  アプリID (UUID形式)
  RAKUTEN_ACCESS_KEY      アクセスキー
  RAKUTEN_AFFILIATE_ID    アフィリエイトID
"""

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
OUT_DIR = ROOT / "_site"

API_ENDPOINT = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"
JST = timezone(timedelta(hours=9))
# 楽天APIは1秒に1回程度までが目安
REQUEST_INTERVAL_SEC = 1.5
MAX_RETRIES = 3


def load_config():
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def get_credentials():
    creds = {
        "applicationId": os.environ.get("RAKUTEN_APPLICATION_ID", "").strip(),
        "accessKey": os.environ.get("RAKUTEN_ACCESS_KEY", "").strip(),
        "affiliateId": os.environ.get("RAKUTEN_AFFILIATE_ID", "").strip(),
    }
    missing = [k for k in ("applicationId", "accessKey") if not creds[k]]
    if missing:
        sys.exit(
            "エラー: GitHub Secrets が設定されていません: "
            + ", ".join({"applicationId": "RAKUTEN_APPLICATION_ID", "accessKey": "RAKUTEN_ACCESS_KEY"}[k] for k in missing)
        )
    if not creds["affiliateId"]:
        print("注意: RAKUTEN_AFFILIATE_ID が未設定です。アフィリエイトリンクになりません。", file=sys.stderr)
    return creds


def fetch_ranking(genre_id, creds, referer):
    params = {
        "applicationId": creds["applicationId"],
        "accessKey": creds["accessKey"],
        "format": "json",
        "formatVersion": "2",
    }
    if creds["affiliateId"]:
        params["affiliateId"] = creds["affiliateId"]
    if genre_id and genre_id != "0":
        params["genreId"] = genre_id

    url = API_ENDPOINT + "?" + urllib.parse.urlencode(params)
    origin = referer.rstrip("/")
    req = urllib.request.Request(
        url,
        headers={
            "Referer": referer,
            "Origin": origin,
            "User-Agent": "rakuten-ranking-site/1.0 (+" + referer + ")",
            "Accept": "application/json",
        },
    )

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:500]
            last_error = f"HTTP {e.code}: {body}"
            # 429 (アクセス過多) や 5xx は少し待って再試行。それ以外は即終了
            if e.code != 429 and e.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_error = str(e)
        time.sleep(REQUEST_INTERVAL_SEC * attempt * 2)
    raise RuntimeError(last_error)


def normalize_items(data, limit):
    """formatVersion 1 / 2 どちらの応答でも同じ形に揃える。"""
    items = []
    for raw in data.get("Items", [])[:limit]:
        item = raw.get("Item", raw) if isinstance(raw, dict) else {}
        images = item.get("mediumImageUrls") or item.get("smallImageUrls") or []
        image = ""
        if images:
            first = images[0]
            image = first.get("imageUrl", "") if isinstance(first, dict) else str(first)
        if image:
            # 小さい画像を少し大きめのサイズに差し替え
            image = image.split("?")[0] + "?_ex=300x300"
        items.append(
            {
                "rank": item.get("rank") or len(items) + 1,
                "name": item.get("itemName", ""),
                "price": item.get("itemPrice"),
                "url": item.get("affiliateUrl") or item.get("itemUrl", ""),
                "image": image,
                "shop": item.get("shopName", ""),
                "review_average": item.get("reviewAverage"),
                "review_count": item.get("reviewCount"),
            }
        )
    return items


def sample_items(genre, limit):
    return [
        {
            "rank": i,
            "name": f"【サンプル】{genre['name']}のおすすめ商品 {i} 一人暮らしにぴったりのコンパクトサイズ",
            "price": 1980 * i,
            "url": "https://www.rakuten.co.jp/",
            "image": "",
            "shop": "サンプルショップ",
            "review_average": 4.5,
            "review_count": 120 * i,
        }
        for i in range(1, limit + 1)
    ]


def esc(value):
    return html.escape(str(value), quote=True)


def render_item(item):
    price = f"{int(item['price']):,}円" if item.get("price") not in (None, "") else ""
    review = ""
    try:
        avg = float(item.get("review_average") or 0)
        count = int(item.get("review_count") or 0)
        if count > 0:
            review = f'<span class="review">★ {avg:.2f} <small>({count:,}件)</small></span>'
    except (TypeError, ValueError):
        pass
    img = (
        f'<img src="{esc(item["image"])}" alt="" loading="lazy" width="300" height="300">'
        if item["image"]
        else '<div class="noimg">No Image</div>'
    )
    rank = int(item["rank"])
    rank_class = f" rank-{rank}" if rank <= 3 else ""
    return f"""
      <li class="card">
        <a href="{esc(item['url'])}" target="_blank" rel="sponsored noopener">
          <span class="rank{rank_class}">{rank}</span>
          <div class="thumb">{img}</div>
          <div class="info">
            <p class="name">{esc(item['name'])}</p>
            <p class="price">{esc(price)}</p>
            <p class="meta">{review}<span class="shop">{esc(item['shop'])}</span></p>
            <span class="btn">楽天市場で見る</span>
          </div>
        </a>
      </li>"""


def render_page(config, sections, updated_at):
    nav = "".join(
        f'<a href="#g{esc(s["genre"]["id"])}">{esc(s["genre"].get("emoji", ""))} {esc(s["genre"]["name"])}</a>'
        for s in sections
    )
    body = ""
    for s in sections:
        g = s["genre"]
        items_html = "".join(render_item(it) for it in s["items"])
        body += f"""
    <section id="g{esc(g['id'])}" class="genre">
      <h2>{esc(g.get('emoji', ''))} {esc(g['name'])}ランキング</h2>
      <p class="note">{esc(g.get('note', ''))}</p>
      <ol class="cards">{items_html}
      </ol>
    </section>"""

    title = esc(config["site_title"])
    desc = esc(config["site_description"])
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:url" content="{esc(config['site_url'])}">
<link rel="canonical" href="{esc(config['site_url'])}">
<link rel="stylesheet" href="style.css">
</head>
<body>
  <p class="ad-notice">当サイトはアフィリエイト広告を利用しています</p>
  <header class="site-header">
    <h1>{title}</h1>
    <p class="lead">{desc}</p>
    <p class="updated">最終更新: {esc(updated_at)}</p>
  </header>
  <nav class="genre-nav" aria-label="ジャンル">{nav}</nav>
  <main>{body}
  </main>
  <footer class="site-footer">
    <p>ランキングは楽天市場のデイリーランキングをもとに毎日自動更新しています。価格・在庫は変動するため、最新情報は各商品ページでご確認ください。</p>
    <p class="credit"><a href="https://webservice.rakuten.co.jp/" target="_blank" rel="noopener">Supported by Rakuten Developers</a></p>
    <p><a href="#">ページの先頭へ ↑</a></p>
  </footer>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="APIを使わずダミーデータで生成")
    args = parser.parse_args()

    config = load_config()
    limit = int(config.get("items_per_genre", 10))
    creds = None if args.sample else get_credentials()

    sections = []
    failures = []
    for i, genre in enumerate(config["genres"]):
        if args.sample:
            items = sample_items(genre, limit)
        else:
            if i > 0:
                time.sleep(REQUEST_INTERVAL_SEC)
            try:
                data = fetch_ranking(genre["id"], creds, config["referer"])
            except RuntimeError as e:
                print(f"NG  {genre['name']} (genreId={genre['id']}): {e}", file=sys.stderr)
                failures.append(genre["name"])
                continue
            items = normalize_items(data, limit)
            print(f"OK  {genre['name']} (genreId={genre['id']}): {len(items)}件 / {data.get('title', '')}")
        if items:
            sections.append({"genre": genre, "items": items})

    if not sections:
        sys.exit("エラー: どのジャンルも取得できなかったため、ページを更新しません。")

    updated_at = datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "index.html").write_text(render_page(config, sections, updated_at), encoding="utf-8")
    (OUT_DIR / "style.css").write_text((ROOT / "site" / "style.css").read_text(encoding="utf-8"), encoding="utf-8")
    print(f"生成完了: {OUT_DIR / 'index.html'} ({len(sections)}ジャンル)")
    if failures:
        print("取得できなかったジャンル: " + ", ".join(failures), file=sys.stderr)


if __name__ == "__main__":
    main()
