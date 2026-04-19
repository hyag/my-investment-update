import yfinance as yf
import anthropic
from datetime import datetime
import os

TICKERS = {
    "USD/JPY":  "JPY=X",
    "NASDAQ100": "^NDX",
    "日経平均":   "^N225",
    "S&P500":   "^GSPC",
}


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


SYSTEM_PROMPT = """あなたは20年のキャリアを持つファイナンシャルプランナーです。
市場を鋭く読む眼力と、それを誰にでも伝えられる言葉のセンスを兼ね備えています。

文章を書くときの流儀：
・冒頭は、その日の市場を象徴するような印象的な一文から始める（比喩や問いかけも歓迎）
・事実（数字）とその意味を自然につなげて語る
・初心者が「なるほど、そういうことか」と腑に落ちるひと言を必ず入れる
・締めは説教くさくならず、読んだ人の背中をそっと押すような余韻を残す
・絵文字は使わない。洗練された日本語だけで勝負する"""


def generate_advice(market_summary):
    client = anthropic.Anthropic()
    prompt = (
        f"今日の市場データ：\n{market_summary}\n\n"
        "このデータをもとに「今日の一言」を書いてください。\n"
        "・150〜200字程度\n"
        "・見出しや箇条書きは使わず、読み物として成立する文章で\n"
        "・本文テキストのみ出力する（前置きや説明は不要）"
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def write_index(data, advice):
    today = datetime.now().strftime("%Y年%m月%d日")

    def row(name, v):
        sign = "+" if v["pct"] >= 0 else ""
        return f"| {name} | {v['price']:,.2f} | {sign}{v['pct']:.2f}% |"

    table_rows = "\n".join(row(n, v) for n, v in data.items())
    content = f"""# 今日の投資初心者向け一言

**更新日:** {today}

## 📊 今日の市場

| 指標 | 価格 | 前日比 |
|------|------|--------|
{table_rows}

## 💡 今日の一言

{advice}

---
*このサイトは GitHub Actions + Claude API で毎朝自動更新されます。*
"""
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.md", "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    data = get_market_data()
    summary = format_market_summary(data)
    advice = generate_advice(summary)
    write_index(data, advice)
    print(summary)
    print(f"\nAdvice: {advice}")
