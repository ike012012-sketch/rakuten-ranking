#!/usr/bin/env python3
"""楽天市場ランキングAPIからジャンル別ランキングを取得し、静的サイトを生成する。

使い方:
  python3 scripts/build.py           # 楽天APIから取得して _site/ に出力
  python3 scripts/build.py --sample  # APIを使わずダミーデータで見た目だけ確認

必要な環境変数 (GitHub Secrets から渡す):
  RAKUTEN_APPLICATION_ID  アプリID (UUID形式)
  RAKUTEN_ACCESS_KEY      アクセスキー
  RAKUTEN_AFFILIATE_ID    アフィリエイトID

出力するもの:
  index.html              トップページ (各ジャンルの上位を紹介)
  <slug>/index.html       ジャンル別ページ (1〜30位)
  sitemap.xml, robots.txt 検索エンジン向け
  data/ranking.json       翌日の順位変動の計算に使う今日の順位
"""

import argparse
import html
import json
import os
import random
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
STATIC_DIR = ROOT / "site"
OUT_DIR = ROOT / "_site"
DATA_PATH = "data/ranking.json"

API_ENDPOINT = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"
JST = timezone(timedelta(hours=9))
# 楽天APIは1秒に1回程度までが目安
REQUEST_INTERVAL_SEC = 1.5
MAX_RETRIES = 3
# トップページで各ジャンルから紹介する件数
HOME_ITEMS_PER_GENRE = 3
# 最初に画面に入る画像だけ先に読み込み、残りは遅延読み込みにする
EAGER_IMAGES = 3

PRICE_FILTERS = [
    ("すべて", 0, 0),
    ("〜2,000円", 0, 2000),
    ("2,000〜5,000円", 2000, 5000),
    ("5,000〜1万円", 5000, 10000),
    ("1万〜3万円", 10000, 30000),
    ("3万円〜", 30000, 0),
]


# ---------------------------------------------------------------- 取得


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


def fetch_previous(site_url):
    """公開中のサイトから前回の順位データを読む。初回や取得失敗時は None。"""
    url = urllib.parse.urljoin(site_url, DATA_PATH)
    try:
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=15) as res:
            data = json.loads(res.read().decode("utf-8"))
        return data if isinstance(data, dict) and "date" in data else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        print(f"前回データなし ({e})。順位変動は次回の更新から表示されます。")
        return None


def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_items(data, limit):
    """formatVersion 1 / 2 どちらの応答でも同じ形に揃え、1位から順に並べる。"""
    items = []
    for index, raw in enumerate(data.get("Items", [])):
        item = raw.get("Item", raw) if isinstance(raw, dict) else {}
        images = item.get("mediumImageUrls") or item.get("smallImageUrls") or []
        image = ""
        if images:
            first = images[0]
            image = first.get("imageUrl", "") if isinstance(first, dict) else str(first)
        if image:
            # 表示サイズ(96px)の2倍強に合わせ、軽い画像を取得する
            image = image.split("?")[0] + "?_ex=240x240"
        items.append(
            {
                "rank": to_int(item.get("rank"), index + 1),
                "code": item.get("itemCode", ""),
                "name": item.get("itemName", ""),
                "price": to_int(item.get("itemPrice")),
                "url": item.get("affiliateUrl") or item.get("itemUrl", ""),
                "image": image,
                "shop": item.get("shopName", ""),
                "review_average": to_float(item.get("reviewAverage")),
                "review_count": to_int(item.get("reviewCount"), 0),
                # postageFlag: 0 = 送料込み(送料無料) / 1 = 送料別
                "free_shipping": to_int(item.get("postageFlag"), 1) == 0,
            }
        )
    # APIの応答が下位から並んでいることがあるため、必ず順位の小さい順に並べ替える
    items.sort(key=lambda it: it["rank"])
    return items[:limit]


def sample_data(genre, count=30):
    """API応答と同じ形のダミーデータ。実際のAPIと同じく下位から並べておく。"""
    rnd = random.Random(genre["id"])
    return {
        "Items": [
            {
                "rank": i,
                "itemCode": f"sample:{genre['slug']}-{i}",
                "itemName": f"【サンプル】{genre['name']}のおすすめ商品 {i} 一人暮らしにぴったりのコンパクトサイズ",
                "itemPrice": rnd.choice([980, 1480, 2980, 4980, 7800, 12800, 24800, 39800]),
                "itemUrl": "https://www.rakuten.co.jp/",
                "shopName": "サンプルショップ",
                "reviewAverage": round(rnd.uniform(3.5, 4.9), 2),
                "reviewCount": rnd.choice([0, 12, 340, 2150]),
                "postageFlag": rnd.choice([0, 1]),
            }
            for i in range(count, 0, -1)
        ]
    }


def sample_previous(config):
    """--sample 用: 順位変動の表示を確かめるための「前日」データ。"""
    ranks = {}
    for g in config["genres"]:
        rnd = random.Random("prev" + g["id"])
        codes = [f"sample:{g['slug']}-{i}" for i in range(1, 31)]
        ranks[g["id"]] = {c: rnd.randint(1, 30) for c in codes if rnd.random() > 0.2}
    return {"date": "2000-01-01", "genres": {}, "ranks": ranks, "baseline": None}


def ranks_of(snapshot):
    if snapshot.get("ranks"):
        return snapshot["ranks"]
    return {
        gid: {it["code"]: it["rank"] for it in g.get("items", []) if it.get("code")}
        for gid, g in snapshot.get("genres", {}).items()
    }


def decide_baseline(previous, today):
    """順位変動の比較対象。同じ日に再実行しても「前日」との比較を保つ。"""
    if not previous:
        return None
    if previous.get("date") == today:
        return previous.get("baseline")
    return {"date": previous["date"], "ranks": ranks_of(previous)}


def apply_rank_changes(items, baseline_ranks):
    for it in items:
        it["change"] = None
        if baseline_ranks is None or not it["code"]:
            continue
        old = baseline_ranks.get(it["code"])
        it["change"] = "new" if old is None else old - it["rank"]


# ---------------------------------------------------------------- 表示


def esc(value):
    return html.escape(str(value), quote=True)


def yen(value):
    return f"{value:,}円" if value is not None else ""


def render_change(change):
    if change is None:
        return ""
    if change == "new":
        return '<span class="chg chg-new">NEW</span>'
    if change > 0:
        return f'<span class="chg chg-up" title="前日から{change}位アップ">↑{change}</span>'
    if change < 0:
        return f'<span class="chg chg-down" title="前日から{-change}位ダウン">↓{-change}</span>'
    return '<span class="chg chg-stay" title="前日と同じ順位">→</span>'


def render_item(item, eager=False):
    rank = item["rank"]
    rank_class = f" rank-{rank}" if rank <= 3 else ""
    if item["image"]:
        loading = 'fetchpriority="high"' if eager else 'loading="lazy"'
        img = f'<img src="{esc(item["image"])}" alt="" width="96" height="96" decoding="async" {loading}>'
    else:
        img = '<span class="noimg">No Image</span>'
    if item["review_count"]:
        review = (
            f'<span class="review"><span class="star" aria-hidden="true">★</span>'
            f'{item["review_average"]:.2f}<small>({item["review_count"]:,}件)</small></span>'
        )
    else:
        review = '<span class="review none">レビューなし</span>'
    ship = '<span class="tag-free">送料無料</span>' if item["free_shipping"] else ""
    price = item["price"] if item["price"] is not None else ""
    return f"""
      <li class="card" data-price="{esc(price)}" data-free="{1 if item['free_shipping'] else 0}">
        <a href="{esc(item['url'])}" target="_blank" rel="sponsored noopener">
          <span class="rankbox"><span class="rank{rank_class}">{rank}<small>位</small></span>{render_change(item.get('change'))}</span>
          <span class="thumb">{img}</span>
          <span class="info">
            <span class="name">{esc(item['name'])}</span>
            <span class="price">{esc(yen(item['price']))}{ship}</span>
            <span class="meta">{review}<span class="shop">{esc(item['shop'])}</span></span>
            <span class="btn">楽天市場で見る</span>
          </span>
        </a>
      </li>"""


def render_tabs(sections, current_slug, prefix):
    current = ' aria-current="page"'
    links = [f'<a href="{prefix or "./"}"{current if current_slug is None else ""}>トップ</a>']
    for s in sections:
        g = s["genre"]
        cur = current if g["slug"] == current_slug else ""
        links.append(f'<a href="{prefix}{esc(g["slug"])}/"{cur}>{esc(g["emoji"])} {esc(g["name"])}</a>')
    return '<nav class="tabs" aria-label="ジャンル切り替え">' + "".join(links) + "</nav>"


def render_filters():
    buttons = "".join(
        f'<button type="button" data-min="{lo}" data-max="{hi}" aria-pressed="{"true" if i == 0 else "false"}">{esc(label)}</button>'
        for i, (label, lo, hi) in enumerate(PRICE_FILTERS)
    )
    return f"""
      <div class="filters" hidden>
        <p class="filters-label">価格帯で絞り込み</p>
        <div class="chips" role="group" aria-label="価格帯">{buttons}</div>
        <div class="filters-row">
          <label class="free-toggle"><input type="checkbox" class="free-only"> 送料無料のみ</label>
          <p class="count" aria-live="polite"></p>
        </div>
      </div>"""


def json_ld(data):
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # </script> の誤認を防ぐ
    return '<script type="application/ld+json">' + text.replace("</", "<\\/") + "</script>"


def updated_line(updated):
    return (
        f'<p class="updated">最終更新: <time datetime="{updated.isoformat(timespec="minutes")}">'
        f'{updated.strftime("%Y年%m月%d日 %H:%M")}</time>(毎日自動更新)</p>'
    )


def render_layout(config, *, title, description, canonical, prefix, tabs, body, ld, updated):
    verification = config.get("google_site_verification", "").strip()
    verify_tag = f'\n<meta name="google-site-verification" content="{esc(verification)}">' if verification else ""
    og_image = urllib.parse.urljoin(config["site_url"], "ogp.png")
    home = prefix or "./"
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(canonical)}">{verify_tag}
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(config['site_name'])}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:image" content="{esc(og_image)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ja_JP">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#bf0000">
<link rel="icon" href="{prefix}favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://thumbnail.image.rakuten.co.jp">
<link rel="stylesheet" href="{prefix}style.css">
<script src="{prefix}app.js" defer></script>
{ld}
</head>
<body>
  <p class="ad-notice">当サイトはアフィリエイト広告を利用しています</p>
  <header class="site-header">
    <a class="site-name" href="{home}">{esc(config['site_name'])}</a>
  </header>
  {tabs}
  <main>{body}
  </main>
  <footer class="site-footer">
    {updated_line(updated)}
    <p>ランキングは楽天市場のデイリーランキングをもとに毎日自動更新しています。順位変動は前日の更新との比較です。価格・送料・在庫は変動するため、最新情報は各商品ページでご確認ください。</p>
    <p class="credit"><a href="https://webservice.rakuten.co.jp/" target="_blank" rel="noopener">Supported by Rakuten Developers</a></p>
    <p><a href="#">ページの先頭へ ↑</a></p>
  </footer>
</body>
</html>
"""


def item_list_ld(items, name):
    return {
        "@type": "ItemList",
        "name": name,
        "numberOfItems": len(items),
        "itemListOrder": "https://schema.org/ItemListOrderAscending",
        "itemListElement": [
            {"@type": "ListItem", "position": it["rank"], "name": it["name"], "url": it["url"]} for it in items
        ],
    }


def website_ld(config):
    return {
        "@type": "WebSite",
        "@id": config["site_url"] + "#website",
        "name": config["site_name"],
        "url": config["site_url"],
        "inLanguage": "ja",
    }


def render_home(config, sections, updated):
    home = config["home"]
    site_url = config["site_url"]
    guide = "".join(f"\n      <p>{esc(p)}</p>" for p in home["guide"])
    blocks = ""
    for n, s in enumerate(sections):
        g = s["genre"]
        top = s["items"][:HOME_ITEMS_PER_GENRE]
        cards = "".join(render_item(it, eager=(n == 0 and i == 0)) for i, it in enumerate(top))
        blocks += f"""
    <section class="genre">
      <h2>{esc(g['emoji'])} {esc(g['h1'])}</h2>
      <p class="note">{esc(g['intro'])}</p>
      <ol class="cards">{cards}
      </ol>
      <p class="more"><a href="{esc(g['slug'])}/">{esc(g['name'])}ランキングを{len(s['items'])}位まで見る →</a></p>
    </section>"""

    body = f"""
    <section class="hero">
      <h1>{esc(home['h1'])}</h1>
      <p class="lead">{esc(home['lead'])}</p>
      {updated_line(updated)}
    </section>
    <section class="guide">
      <h2>{esc(home['guide_title'])}</h2>{guide}
    </section>{blocks}"""

    ld = json_ld(
        {
            "@context": "https://schema.org",
            "@graph": [
                website_ld(config),
                {
                    "@type": "CollectionPage",
                    "name": home["title"],
                    "description": home["description"],
                    "url": site_url,
                    "inLanguage": "ja",
                    "dateModified": updated.isoformat(timespec="minutes"),
                    "isPartOf": {"@id": site_url + "#website"},
                    "mainEntity": {
                        "@type": "ItemList",
                        "itemListElement": [
                            {
                                "@type": "ListItem",
                                "position": i + 1,
                                "name": s["genre"]["h1"],
                                "url": site_url + s["genre"]["slug"] + "/",
                            }
                            for i, s in enumerate(sections)
                        ],
                    },
                },
            ],
        }
    )
    return render_layout(
        config,
        title=home["title"],
        description=home["description"],
        canonical=site_url,
        prefix="",
        tabs=render_tabs(sections, None, ""),
        body=body,
        ld=ld,
        updated=updated,
    )


def render_genre(config, section, sections, updated):
    g = section["genre"]
    site_url = config["site_url"]
    url = site_url + g["slug"] + "/"
    points = "".join(f"\n        <li>{esc(p)}</li>" for p in g["points"])
    cards = "".join(render_item(it, eager=i < EAGER_IMAGES) for i, it in enumerate(section["items"]))
    stale = (
        '\n      <p class="stale">本日の取得に失敗したため、前回のランキングを表示しています。</p>' if section["stale"] else ""
    )
    body = f"""
    <nav class="breadcrumb" aria-label="パンくずリスト"><a href="../">トップ</a> › {esc(g['name'])}ランキング</nav>
    <section class="hero">
      <h1>{esc(g['emoji'])} {esc(g['h1'])}</h1>
      <p class="lead">{esc(g['intro'])}楽天市場のデイリーランキング1〜{len(section['items'])}位を毎日更新しています。</p>
      {updated_line(updated)}
    </section>
    <section class="guide">
      <h2>一人暮らし向け{esc(g['name'])}の選び方のポイント</h2>
      <ul class="points">{points}
      </ul>
    </section>
    <section class="ranking">
      <h2>{esc(g['name'])}の人気ランキング</h2>{stale}{render_filters()}
      <ol class="cards">{cards}
      </ol>
      <p class="empty" hidden>条件に合う商品がありません。価格帯を変えてみてください。</p>
    </section>"""

    ld = json_ld(
        {
            "@context": "https://schema.org",
            "@graph": [
                website_ld(config),
                {
                    "@type": "CollectionPage",
                    "name": g["title"],
                    "description": g["description"],
                    "url": url,
                    "inLanguage": "ja",
                    "dateModified": updated.isoformat(timespec="minutes"),
                    "isPartOf": {"@id": site_url + "#website"},
                    "mainEntity": item_list_ld(section["items"], g["h1"]),
                },
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "トップ", "item": site_url},
                        {"@type": "ListItem", "position": 2, "name": g["name"] + "ランキング", "item": url},
                    ],
                },
            ],
        }
    )
    return render_layout(
        config,
        title=g["title"],
        description=g["description"],
        canonical=url,
        prefix="../",
        tabs=render_tabs(sections, g["slug"], "../"),
        body=body,
        ld=ld,
        updated=updated,
    )


def render_sitemap(config, sections, updated):
    lastmod = updated.isoformat(timespec="seconds")
    urls = [config["site_url"]] + [config["site_url"] + s["genre"]["slug"] + "/" for s in sections]
    entries = "".join(
        f"  <url><loc>{esc(u)}</loc><lastmod>{lastmod}</lastmod><changefreq>daily</changefreq></url>\n" for u in urls
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{entries}</urlset>\n'


def render_robots(config):
    return f"User-agent: *\nAllow: /\n\nSitemap: {urllib.parse.urljoin(config['site_url'], 'sitemap.xml')}\n"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- 本体


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="APIを使わずダミーデータで生成")
    args = parser.parse_args()

    config = load_config()
    limit = int(config.get("items_per_genre", 30))
    creds = None if args.sample else get_credentials()
    now = datetime.now(JST).replace(second=0, microsecond=0)
    today = now.strftime("%Y-%m-%d")

    previous = sample_previous(config) if args.sample else fetch_previous(config["site_url"])
    baseline = decide_baseline(previous, today)
    if baseline:
        print(f"順位変動の比較対象: {baseline['date']} のランキング")
    baseline_ranks = (baseline or {}).get("ranks") or {}

    sections = []
    failures = []
    for i, genre in enumerate(config["genres"]):
        stale = False
        if args.sample:
            items = normalize_items(sample_data(genre), limit)
        else:
            if i > 0:
                time.sleep(REQUEST_INTERVAL_SEC)
            try:
                data = fetch_ranking(genre["id"], creds, config["referer"])
                items = normalize_items(data, limit)
                print(f"OK  {genre['name']} (genreId={genre['id']}): {len(items)}件 / {data.get('title', '')}")
            except RuntimeError as e:
                print(f"NG  {genre['name']} (genreId={genre['id']}): {e}", file=sys.stderr)
                failures.append(genre["name"])
                # 取得に失敗したジャンルは、前回のランキングでページを残す
                items = ((previous or {}).get("genres", {}).get(genre["id"]) or {}).get("items", [])
                stale = bool(items)
        if not items:
            continue
        apply_rank_changes(items, None if stale or not baseline else baseline_ranks.get(genre["id"]))
        sections.append({"genre": genre, "items": items, "stale": stale})

    if not sections:
        sys.exit("エラー: どのジャンルも取得できなかったため、ページを更新しません。")

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    write(OUT_DIR / "index.html", render_home(config, sections, now))
    for s in sections:
        write(OUT_DIR / s["genre"]["slug"] / "index.html", render_genre(config, s, sections, now))
    write(OUT_DIR / "sitemap.xml", render_sitemap(config, sections, now))
    write(OUT_DIR / "robots.txt", render_robots(config))
    snapshot = {
        "date": today,
        "updated_at": now.isoformat(timespec="minutes"),
        "genres": {
            s["genre"]["id"]: {"items": [{k: v for k, v in it.items() if k != "change"} for it in s["items"]]}
            for s in sections
        },
        "baseline": baseline,
    }
    write(OUT_DIR / DATA_PATH, json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")))
    for f in STATIC_DIR.iterdir():
        if f.is_file():
            shutil.copy(f, OUT_DIR / f.name)

    print(f"生成完了: {OUT_DIR} (トップ + {len(sections)}ジャンル)")
    if failures:
        print("取得できなかったジャンル: " + ", ".join(failures), file=sys.stderr)


if __name__ == "__main__":
    main()
