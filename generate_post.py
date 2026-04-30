import json
import os
import urllib.request
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

# VIXは別管理（%変化より水準が重要なため）
_VIX_SYMBOL = "^VIX"


def _vix_label(vix: float) -> str:
    if vix >= 30: return "高（市場パニック圏）"
    if vix >= 20: return "やや高（警戒圏）"
    if vix >= 15: return "通常圏"
    return "低（安心圏）"


def get_vix() -> float | None:
    """VIX現在値を取得する"""
    try:
        hist = yf.Ticker(_VIX_SYMBOL).history(period="2d")["Close"]
        return float(hist.iloc[-1]) if not hist.empty else None
    except Exception:
        return None

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


# ── FX急変サマリー取得 ──────────────────────────────────

_SPIKE_SUMMARY_URL = (
    "https://raw.githubusercontent.com/hyag/fx_alert_bot/main/daily_summary.json"
)
_OUTCOME_JA = {"continued": "その後継続", "reversed": "半値戻し", "flat": "横ばい"}


def get_fx_spikes() -> str:
    """
    前日の USD/JPY 急変サマリーを fx_alert_bot リポジトリから取得し、
    プロンプト挿入用の文字列を返す。取得失敗や前日データなければ空文字。
    """
    try:
        req = urllib.request.Request(
            _SPIKE_SUMMARY_URL,
            headers={"Cache-Control": "no-cache"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
        if data.get("date") != yesterday:
            return ""

        spikes = data.get("spikes", [])
        if not spikes:
            return ""

        lines = []
        for s in spikes:
            direction = "急落" if s.get("direction") == "down" else "急騰"
            pips      = s.get("magnitude_pips", 0)
            cause     = (s.get("cause") or "原因不明")[:80]
            conf      = s.get("confidence", "")
            outcome   = _OUTCOME_JA.get(s.get("outcome", ""), "")
            time_jst  = s.get("time_jst", "")
            outcome_str = f" → 30分後:{outcome}" if outcome else ""
            lines.append(
                f"・{time_jst} {direction}{pips:.0f}pips"
                f"（{cause}）[信頼度:{conf}]{outcome_str}"
            )

        return "【昨日のUSD/JPY急変アラート】\n" + "\n".join(lines)
    except Exception:
        return ""


# ── 週末ニュース（月曜のみ） ────────────────────────────

def _parse_yf_news_item(item: dict) -> tuple[str, datetime | None]:
    """
    yfinanceニュースアイテムからタイトルと公開日時を取得する。
    旧API: item.providerPublishTime（Unix秒）
    新API: item.content.pubDate（ISO文字列）
    """
    content = item.get("content") or {}
    title = content.get("title") or item.get("title", "")

    pub_dt: datetime | None = None
    pub_date_str = content.get("pubDate", "")
    if pub_date_str:
        try:
            pub_dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
        except Exception:
            pass
    if pub_dt is None:
        pub_ts = item.get("providerPublishTime") or 0
        if pub_ts:
            pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc)

    return title, pub_dt


def get_news(days=1, limit=8):
    """yfinanceから複数銘柄のニュース見出しを取得して重複排除する"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    headlines = []
    # JPY=X/USDJPY=X: 為替ニュース / ^GSPC,^NDX: 株式 / ^DXY: ドル指数
    for symbol in ["JPY=X", "USDJPY=X", "^GSPC", "^NDX", "^DXY"]:
        try:
            for item in (yf.Ticker(symbol).news or []):
                title, pub_dt = _parse_yf_news_item(item)
                if not title:
                    continue
                if pub_dt is not None and pub_dt < cutoff:
                    continue
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

def generate_entry(market_summary, vix: float | None = None):
    client = anthropic.Anthropic()
    weekday = datetime.now(JST).weekday()

    # VIXセクション（取得できた場合のみ追加）
    vix_section = ""
    if vix is not None:
        vix_section = f"\n【恐怖指数（VIX）】{vix:.1f} → {_vix_label(vix)}"

    # 前日の USD/JPY 急変サマリー（fx_alert_bot から取得）
    spike_section = get_fx_spikes()

    if weekday == 0:
        news = get_news(days=3, limit=8)
        news_section = (
            "【週末のニュース見出し】\n" + "\n".join(f"・{h}" for h in news)
            if news else ""
        )
        timing_note = (
            "今日は月曜日。先週末（金曜）の終値と、もし週末ニュースがあればそれも踏まえて、"
            "週明けの相場を前にした朝の一言を書く。「さて今週はどうなるか」のような週明けならではのニュアンスで。"
        )
        market_block = (
            f"市場終値データ：\n{market_summary}{vix_section}\n\n"
            + (f"{spike_section}\n\n" if spike_section else "")
            + f"{news_section}\n\n{timing_note}"
        )
    else:
        news = get_news(days=1, limit=8)
        news_section = (
            "【直近のニュース見出し】\n" + "\n".join(f"・{h}" for h in news)
            if news else ""
        )
        timing_note = (
            "昨日の市場終値を見ながら、今日の相場を前に感じたことを書く朝の一言。"
            "VIXが高い時はリスクオフの空気感を自然に反映させてよい。"
            "急変アラートがあれば、その動きを踏まえた感想を自然に織り込んでよい。"
            "ニュースがあれば地政学リスクや経済の背景として参考にしてよいが、"
            "ニュースを要約するのではなく、あくまで市場の動きへの感想として自然に織り込む。"
        )
        market_block = (
            f"市場終値データ：\n{market_summary}{vix_section}\n\n"
            + (f"{spike_section}\n\n" if spike_section else "")
            + f"{news_section}\n\n{timing_note}"
        )

    prompt = (
        f"{market_block}\n\n"
        "以下の形式だけで出力してください。余計な説明は不要です。\n\n"
        "TITLE: （記事の内容を表す3〜10文字。日記っぽいキャッチーな一言。例：『ドル円、粘るなぁ』『週明け様子見』）\n"
        "TAGS: （日本語ハッシュタグを3〜5個。投資クラスタへの露骨な訴求は避け、日常・記録・経済に興味ある人に自然に届くトーンで。例：#朝の記録 #経済メモ #ドル円 #相場日記 #マーケット）\n"
        "BODY:\n（160〜180字前後の本文。見出し・箇条書きなし。メモ帳に書いた独り言のような文体で。話題や気持ちの切れ目で自然に改行を入れる。\n\n"
        "本文の最後は空行を1つ入れてから、読者を穏やかに送り出す一文で締めること。\n"
        "トーンは相場の状況に合わせて自然に変える。毎回同じ表現は使わない。\n"
        "例：「今日も一喜一憂せず、いってらっしゃい。」「焦らず、今日も良い一日を。」「無理せず、相場と付き合っていこう。」\n"
        "投資を煽らない。損切りを急かさない。キャラクター設定（独り言の文体）を崩さない）"
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

def write_index(data, title, body, vix: float | None = None):
    now = datetime.now(JST)
    today = now.strftime("%Y.%m.%d")
    time_str = now.strftime("%H:%M")
    market_lines = format_market_lines(data)
    if vix is not None:
        market_lines += f"\nVIX  {vix:.1f}  {_vix_label(vix)}"
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

    today = now.strftime("%Y-%m-%d")
    # 同日エントリが既にあれば上書き（重複防止）
    entries = [e for e in entries if e.get("date") != today]
    entries.insert(0, {
        "title": title,
        "body": body,
        "date": today,
        "pubDate": _rfc822(now),
    })
    entries = entries[:30]

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    items_xml = "\n".join(
        f"""  <item>
    <title>{escape(e['title'])}</title>
    <link>{SITE_URL}#{e['date']}</link>
    <description>{escape(e['body'][:200])}</description>
    <pubDate>{e['pubDate']}</pubDate>
    <guid isPermaLink="false">{SITE_URL}#{e['date']}</guid>
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
    data    = get_market_data()
    vix     = get_vix()
    summary = format_market_summary(data)
    title, body, tags = generate_entry(summary, vix=vix)
    write_index(data, title, body, vix=vix)
    update_rss(title, body)
    post_to_x(title, body)
    post_to_bluesky(title, body, tags)
    print(summary)
    if vix is not None:
        print(f"VIX: {vix:.1f} ({_vix_label(vix)})")
    print(f"\nTitle: {title}")
    print(f"Tags: {tags}")
    print(f"Body:\n{body}")
