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


def generate_advice(market_summary):
    client = anthropic.Anthropic()
    prompt = (
        f"今日の市場データ：\n{market_summary}\n\n"
        "投資初心者向けに、このデータをもとに150字以内の「今日の一言」を日本語で書いてください。"
        "前日比の動きに触れながら、難しい専門用語は避けやさしい言葉で。"
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
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
