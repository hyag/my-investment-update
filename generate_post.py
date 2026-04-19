import yfinance as yf
import anthropic
from datetime import datetime, timezone, timedelta
import os

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


def get_weekend_news():
    now = datetime.now(JST)
    two_days_ago = now - timedelta(days=2)
    cutoff = int(two_days_ago.timestamp())

    headlines = []
    for symbol in ["^GSPC", "^NDX", "JPY=X"]:
        try:
            items = yf.Ticker(symbol).news or []
            for item in items:
                pub = item.get("providerPublishTime", 0)
                title = (item.get("content") or {}).get("title") or item.get("title", "")
                if pub >= cutoff and title:
                    headlines.append(title)
        except Exception:
            pass

    seen, unique = set(), []
    for h in headlines:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    return unique[:5]


def generate_entry(market_summary):
    client = anthropic.Anthropic()
    weekday = datetime.now(JST).weekday()  # 0=月曜

    if weekday == 0:
        news = get_weekend_news()
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
        timing_note = "昨日の市場終値を見ながら、今日の相場を前に感じたことを書く朝の一言。"
        market_block = f"市場終値データ：\n{market_summary}\n\n{timing_note}"

    prompt = (
        f"{market_block}\n\n"
        "以下の形式だけで出力してください。余計な説明は不要です。\n\n"
        "TITLE: （記事の内容を表す3〜10文字。日記っぽいキャッチーな一言。例：『ドル円、粘るなぁ』『週明け様子見』）\n"
        "BODY:\n（150字前後の本文。見出し・箇条書きなし。メモ帳に書いた独り言のような文体で）"
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()

    title, body = "今日のメモ", text
    for line in text.splitlines():
        if line.startswith("TITLE:"):
            title = line.removeprefix("TITLE:").strip()
        elif line.startswith("BODY:"):
            body = text[text.index("BODY:") + len("BODY:"):].strip()
            break
    return title, body


JST = timezone(timedelta(hours=9))


def format_market_lines(data):
    lines = []
    for name, v in data.items():
        sign = "+" if v["pct"] >= 0 else ""
        lines.append(f"{name}  {v['price']:,.2f}  前日比{sign}{v['pct']:.1f}%")
    return "\n".join(lines)


def write_index(data, title, body):
    now = datetime.now(JST)
    today = now.strftime("%Y.%m.%d")
    days_back = 3 if now.weekday() == 0 else 1
    prev_date = (now - timedelta(days=days_back)).strftime("%m/%d")
    market_lines = format_market_lines(data)
    content = f"""---
layout: default
---

# {title}

<p class="date">{today} 配信 ／ {prev_date} 終値</p>

<p class="market">{market_lines.replace(chr(10), '<br>')}</p>

{body}
"""
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.md", "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    data = get_market_data()
    summary = format_market_summary(data)
    title, body = generate_entry(summary)
    write_index(data, title, body)
    print(summary)
    print(f"\nTitle: {title}")
    print(f"Body:\n{body}")
