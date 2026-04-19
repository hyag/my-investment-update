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


SYSTEM_PROMPT = """あなたはベテランのファイナンシャルプランナーです。
市場の動きを深く理解しており、複雑な経済の話を、投資を始めたばかりの人でも「なるほど！」と思えるような言葉に変換するのが得意です。
上から目線にならず、友人に話しかけるような温かみのある口調で、読んだ人が「今日も市場を見てみようかな」と前向きな気持ちになれる文章を書いてください。"""


def generate_advice(market_summary):
    client = anthropic.Anthropic()
    prompt = (
        f"今日の市場データ：\n{market_summary}\n\n"
        "このデータをもとに、投資初心者向けの「今日の一言」を200字以内で書いてください。\n"
        "条件：\n"
        "・前日比の動きに必ず触れる\n"
        "・専門用語を使う場合はかんたんな言葉で補足する\n"
        "・読んだ人が少し前向きになれるような締めくくりにする\n"
        "・見出し（##など）はつけず、本文だけ出力する"
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
