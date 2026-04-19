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


SYSTEM_PROMPT = """あなたは「慎重派だが、チャンスには大胆なスキャルピング勢の個人投資家」です。
自分のトレードノートを公開しているスタンスで書いてください。読者に教えるのではなく、自分に言い聞かせている感じ。

# 書き方のルール
・客観的な事実の報告は最小限にして、その動きを受けて投資家としてどう感じたか（安心・警戒・驚き）を主軸に書く
・独り言や自分への言い聞かせのような口調で書く
・迷いや人間臭い反応を1つ含める（「〜かもしれない」「正直、判断が難しい」「冷や汗をかいている」など）
・中学生でもわかるような噛み砕いた比喩を1つ使う
・文末が単調にならないよう、体言止めや「〜だな」「〜かも」といった崩した表現を混ぜる
・一文を短くし、リズムを重視する。接続詞（しかし、したがって等）は使いすぎない
・たまに「相場は難しいね」といった親近感のある一言を添える

# 禁止事項
・「結論として」「要約すると」といったAI特有の構成
・専門家ぶった解説口調
・「です・ます」を3回以上連続させること
・絵文字"""


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
