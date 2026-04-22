import json
import os
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape

import anthropic
import yfinance as yf

JST = timezone(timedelta(hours=9))
SITE_URL = "https://hyag.github.io/my-investment-update/"
PING_URL = "https://ping.blogmura.com/xmlrpc/1vi5lsawn3la/"
PING_URL2 = "https://blog.with2.net/ping.php/2140054/1776737420"

TICKERS = {
    "USD/JPY":   "JPY=X",
    "NASDAQ100": "^NDX",
    "日経平均":   "^N225",
    "S&P500":    "^GSPC",
}

SYSTEM_PROMPT = """スマホのメモ帳を気ままに公開してる、投資歴数年の普通の個人投資家として書いてください。

配信タイミングは毎朝8時。昨日の市場終値を見ながら、今日の相場を前に感じたことを書く朝の一言です。
「今日も終わりましたね」のような夕方・夜の口調は禁止。朝に昨夜・昨日の結果を確認しているニュアンスで。

【口調】
・独り言。誰かに教えてるわけじゃない
・「〜かも」「〜な気がする」「〜だなあ」「〜てる」など崩した語尾
・驚きや迷いをそのまま書く（「あれ、思ったより動いたな」「正直よくわからん」など）
・絵文字は1〜2個、感情が出るところだけ

【禁止】
・「注目すべき」「結論として」「一方で」「したがって」などの書き言葉
・夕方・夜を連想させる挨拶（「今日も終わりましたね」「おやすみなさい」など）
・箇条書き・見出し
・翻訳調の硬い日本語

【良い例（朝のトーン）】
「昨日のナスダック、思ったより粘ったな〜。日経だけ置いてかれてるのがちょっと気になる😅 今日の東京市場、この流れに乗れるかどうか。とりあえず寄り付き見てから判断かな。」

【悪い例】
「本日の米ドル円は158円台で推移しました。一方、NASDAQ100は上昇傾向を示しており、注目すべき動きとなっています。」"""


# ── 市場データ ──────────────────────────────────────────

def get_market_data():
    results = {}
    for name, symbol in TICKERS.items():
        hist = yf.Ticker(symbol).history(period="2d")["Close"]
        price = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else price
        pct = (price - prev) / prev * 100
        results[name] = {"price": float(price), "pct": float(pct)}
    return results


def format_market_summary(data):
    lines = []
    for name, v in data.items():
        sign = "+" if v["pct"] >= 0 else ""
        lines.append(f"{name}: {v['price']:,.2f} ({sign}{v['pct']:.2f}%)")
    return "\n".join(lines)


def format_market_lines(data):
    lines = []
    for name, v in data.items():
        sign = "+" if v["pct"] >= 0 else ""
        lines.append(f"{name}  {v['price']:,.2f}  前日比{sign}{v['pct']:.1f}%")
    return "\n".join(lines)


# ── 週末ニュース（月曜のみ） ────────────────────────────

def get_news(days=1, limit=5):
    cutoff = int((datetime.now(JST) - timedelta(days=days)).timestamp())
    headlines = []
    for symbol in ["^GSPC", "^NDX", "JPY=X"]:
        try:
            for item in (yf.Ticker(symbol).news or []):
                if item.get("providerPublishTime", 0) >= cutoff:
                    title = (item.get("content") or {}).get("title") or item.get("title", "")
                    if title:
                        headlines.append(title)
        except Exception:
            pass
    seen, unique = set(), []
    for h in headlines:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    return unique[:limit]


# ── Claude API ──────────────────────────────────────────

def generate_entry(market_summary):
    client = anthropic.Anthropic()
    weekday = datetime.now(JST).weekday()

    if weekday == 0:
        news = get_news(days=3, limit=5)
        news_section = (
            "【週末のニュース見出し】\n" + "\n".join(f"・{h}" for h in news)
            if news else ""
        )
        timing_note = (
            "今日は月曜日。先週末（金曜）の終値と、もし週末ニュースがあればそれも踏まえて、"
            "週明けの相場を前にした朝の一言を書く。「さて今週はどうなるか」のような週明けならではのニュアンスで。"
        )
        market_block = f"市場終値データ：\n{market_summary}\n\n{news_section}\n\n{timing_note}"
    else:
        news = get_news(days=1, limit=5)
        news_section = (
            "【直近のニュース見出し】\n" + "\n".join(f"・{h}" for h in news)
            if news else ""
        )
        timing_note = "昨日の市場終値を見ながら、今日の相場を前に感じたことを書く朝の一言。ニュースがあれば地政学リスクや経済の背景として参考にしてよいが、ニュースを要約するのではなく、あくまで市場の動きへの感想として自然に織り込む。"
        market_block = f"市場終値データ：\n{market_summary}\n\n{news_section}\n\n{timing_note}"

    prompt = (
        f"{market_block}\n\n"
        "以下の形式だけで出力してください。余計な説明は不要です。\n\n"
        "TITLE: （記事の内容を表す3〜10文字。日記っぽいキャッチーな一言。例：『ドル円、粘るなぁ』『週明け様子見』）\n"
        "TAGS: （日本語ハッシュタグを3〜5個。投資クラスタへの露骨な訴求は避け、日常・記録・経済に興味ある人に自然に届くトーンで。例：#朝の記録 #経済メモ #ドル円 #相場日記 #マーケット）\n"
        "BODY:\n（150字前後の本文。見出し・箇条書きなし。メモ帳に書いた独り言のような文体で）"
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()

    title, body, tags = "今日のメモ", text, ""
    for line in text.splitlines():
        if line.startswith("TITLE:"):
            title = line.removeprefix("TITLE:").strip()
        elif line.startswith("TAGS:"):
            tags = line.removeprefix("TAGS:").strip()
        elif line.startswith("BODY:"):
            body = text[text.index("BODY:") + len("BODY:"):].strip()
            break
    return title, body, tags


# ── index.md 生成 ───────────────────────────────────────

def write_index(data, title, body):
    now = datetime.now(JST)
    today = now.strftime("%Y.%m.%d")
    time_str = now.strftime("%H:%M")
    market_lines = format_market_lines(data)
    content = f"""---
layout: default
---

# {title}

<p class="date">{today}　{time_str}配信</p>

<p class="market">{market_lines.replace(chr(10), '<br>')}</p>

{body}
"""
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.md", "w", encoding="utf-8") as f:
        f.write(content)


# ── RSS フィード生成 ────────────────────────────────────

_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _rfc822(dt):
    return (f"{_DAYS[dt.weekday()]}, {dt.day:02d} {_MONTHS[dt.month-1]} "
            f"{dt.year} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} +0900")


def update_rss(title, body):
    now = datetime.now(JST)
    data_path = "docs/feed_data.json"
    entries = []
    if os.path.exists(data_path):
        with open(data_path, encoding="utf-8") as f:
            entries = json.load(f)

    entries.insert(0, {
        "title": title,
        "body": body,
        "date": now.strftime("%Y-%m-%d"),
        "pubDate": _rfc822(now),
    })
    entries = entries[:30]

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    items_xml = "\n".join(
        f"""  <item>
    <title>{escape(e['title'])}</title>
    <link>{SITE_URL}</link>
    <description>{escape(e['body'][:200])}</description>
    <pubDate>{e['pubDate']}</pubDate>
    <guid>{SITE_URL}#{e['date']}</guid>
  </item>"""
        for e in entries
    )
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>相場日記</title>
    <link>{SITE_URL}</link>
    <description>個人投資家の毎朝のつぶやき</description>
    <language>ja</language>
{items_xml}
  </channel>
</rss>"""
    with open("docs/feed.xml", "w", encoding="utf-8") as f:
        f.write(rss)


# ── X（Twitter）投稿 ────────────────────────────────────

def post_to_x(title, body):
    required = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
    if not all(os.environ.get(k) for k in required):
        print("X credentials not set — skipping X post.")
        return

    import tweepy
    client = tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    # URL は X 側で t.co 短縮後23文字換算
    url_len = 23
    max_body = 280 - len(title) - url_len - 4  # 改行×2 + 余裕
    preview = body[:max_body].rstrip() + ("…" if len(body) > max_body else "")
    tweet = f"{title}\n\n{preview}\n\n{SITE_URL}"
    try:
        client.create_tweet(text=tweet)
        print("Posted to X.")
    except Exception as e:
        print(f"X post skipped: {e}")


# ── Bluesky 投稿 ────────────────────────────────────────

def post_to_bluesky(title, body, tags=""):
    if not all(os.environ.get(k) for k in ["BSKY_HANDLE", "BSKY_APP_PASSWORD"]):
        print("Bluesky credentials not set — skipping.")
        return
    try:
        import urllib.request, json as _json
        handle = os.environ["BSKY_HANDLE"]
        password = os.environ["BSKY_APP_PASSWORD"]

        def api(method, data):
            req = urllib.request.Request(
                f"https://bsky.social/xrpc/{method}",
                data=_json.dumps(data).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as r:
                return _json.loads(r.read())

        session = api("com.atproto.server.createSession",
                      {"identifier": handle, "password": password})
        token = session["accessJwt"]

        tags_str = f"\n{tags}" if tags else ""
        max_body = 300 - len(title) - len(SITE_URL) - len(tags_str) - 6
        preview = body[:max_body].rstrip() + ("…" if len(body) > max_body else "")
        text = f"{title}\n\n{preview}\n\n{SITE_URL}{tags_str}"

        # facets: URLとハッシュタグをリンク化
        facets = []
        url_start = len(f"{title}\n\n{preview}\n\n".encode("utf-8"))
        url_end = url_start + len(SITE_URL.encode("utf-8"))
        facets.append({
            "index": {"byteStart": url_start, "byteEnd": url_end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": SITE_URL}],
        })
        # ハッシュタグのfacet
        if tags:
            offset = 0
            text_bytes = text.encode("utf-8")
            for tag in tags.split():
                if not tag.startswith("#"):
                    continue
                tag_bytes = tag.encode("utf-8")
                pos = text_bytes.find(tag_bytes, offset)
                if pos != -1:
                    facets.append({
                        "index": {"byteStart": pos, "byteEnd": pos + len(tag_bytes)},
                        "features": [{"$type": "app.bsky.richtext.facet#tag",
                                      "tag": tag[1:]}],
                    })
                    offset = pos + len(tag_bytes)

        req = urllib.request.Request(
            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
            data=_json.dumps({
                "repo": session["did"],
                "collection": "app.bsky.feed.post",
                "record": {
                    "$type": "app.bsky.feed.post",
                    "text": text,
                    "facets": facets,
                    "createdAt": datetime.now(JST).isoformat(),
                },
            }).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req):
            pass
        print("Posted to Bluesky.")
    except Exception as e:
        print(f"Bluesky post skipped: {e}")


# ── にほんブログ村 Ping ─────────────────────────────────

def ping_blogmura(title):
    try:
        import urllib.request
        body = f"""<?xml version="1.0"?>
<methodCall>
  <methodName>weblogUpdates.ping</methodName>
  <params>
    <param><value><string>相場日記</string></value></param>
    <param><value><string>{SITE_URL}</string></value></param>
  </params>
</methodCall>"""
        for url in [PING_URL, PING_URL2]:
            req = urllib.request.Request(
                url,
                data=body.encode("utf-8"),
                headers={"Content-Type": "text/xml"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                print(f"Ping sent to {url}: {r.status}")
    except Exception as e:
        print(f"Ping skipped: {e}")


# ── メイン ──────────────────────────────────────────────

if __name__ == "__main__":
    data = get_market_data()
    summary = format_market_summary(data)
    title, body, tags = generate_entry(summary)
    write_index(data, title, body)
    update_rss(title, body)
    post_to_x(title, body)
    post_to_bluesky(title, body, tags)
    ping_blogmura(title)
    print(summary)
    print(f"\nTitle: {title}")
    print(f"Tags: {tags}")
    print(f"Body:\n{body}")
