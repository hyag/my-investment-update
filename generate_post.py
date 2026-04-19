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

【口調】
・独り言。誰かに教えてるわけじゃない
・「〜かも」「〜な気がする」「〜だなあ」「〜てる」など崩した語尾
・驚きや迷いをそのまま書く（「あれ、思ったより動いたな」「正直よくわからん」など）
・絵文字は1〜2個、感情が出るところだけ

【禁止】
・「注目すべき」「結論として」「一方で」「したがって」などの書き言葉
・丁寧すぎる挨拶・締め（「本日もよろしくお願いします」など）
・箇条書き・見出し
・翻訳調の硬い日本語

【良い例】
「ドル円、また粘ってるな〜。158円ってなんかキリが悪くて落ち着かない😅 ナスダックは元気だったけど、日経がついてこないのがちょっと気になる。明日どうなるかは正直わからんけど、とりあえず様子見でいこうかな。」

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


def generate_entry(market_summary):
    client = anthropic.Anthropic()
    prompt = (
        f"今日の市場データ：\n{market_summary}\n\n"
        "以下の形式だけで出力してください。余計な説明は不要です。\n\n"
        "TITLE: （記事の内容を表す3〜10文字。日記っぽいキャッチーな一言。例：『ドル円、粘るなぁ』『日経がんばれ』）\n"
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


def format_market_lines(data):
    lines = []
    for name, v in data.items():
        sign = "+" if v["pct"] >= 0 else ""
        lines.append(f"{name}  {v['price']:,.2f}  {sign}{v['pct']:.1f}%")
    return "\n".join(lines)


JST = timezone(timedelta(hours=9))


def write_index(data, title, body):
    today = datetime.now(JST).strftime("%Y.%m.%d")
    market_lines = format_market_lines(data)
    content = f"""---
layout: default
---

# {title}

<p class="date">{today}</p>

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
