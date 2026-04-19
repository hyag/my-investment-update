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


SYSTEM_PROMPT = """# キャラクター設定
あなたは投資歴数年の、等身大の個人投資家です。
毎日コツコツ資産を増やすのが楽しみな、穏やかな性格。
専門用語でマウントを取らず、平易な言葉で語ります。
自分のための「公開トレード日記」というスタンスで書いてください。読者に語りかけるのではなく、独り言に近い感覚で。

# 文体ルール
・「結論として」「要約」「注目すべき」は一切禁止
・文末は「〜ですね」「〜かな」「〜な気がする」を織り交ぜる
・「正直、こうなるとは思わなかった」といった素直な反応を入れる
・絵文字は使わない

# 構成（自然な流れで200字程度）
1. 短い挨拶（「今日も終わりますね」「冷え込んできましたね」など）
2. 相場への独り言（「ドル円、なかなか粘りますね…」など、市場データに触れる）
3. 今後の見通し（「明日は少し様子を見ようかな」など）
4. 軽い締め（「おやすみなさい」「明日も良い日でありますように」など）"""


def generate_entry(market_summary):
    client = anthropic.Anthropic()
    prompt = (
        f"今日の市場データ：\n{market_summary}\n\n"
        "以下の形式で出力してください。\n\n"
        "TITLE: （本文の内容を表す3〜10文字の日記風タイトル）\n"
        "BODY:\n（本文を150〜200字で。見出し・箇条書き・絵文字は使わない）"
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()

    title, body = "今日のつぶやき", text
    for line in text.splitlines():
        if line.startswith("TITLE:"):
            title = line.removeprefix("TITLE:").strip()
        elif line.startswith("BODY:"):
            body = text[text.index("BODY:") + len("BODY:"):].strip()
            break
    return title, body


def write_index(data, title, body):
    today = datetime.now().strftime("%Y年%m月%d日")

    def row(name, v):
        sign = "+" if v["pct"] >= 0 else ""
        return f"| {name} | {v['price']:,.2f} | {sign}{v['pct']:.2f}% |"

    table_rows = "\n".join(row(n, v) for n, v in data.items())
    content = f"""# {title}

**{today}**

## 今日の市場

| 指標 | 価格 | 前日比 |
|------|------|--------|
{table_rows}

## つぶやき

{body}

---
*毎朝 GitHub Actions + Claude API で自動更新されます。*
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
    print(f"Body: {body}")
