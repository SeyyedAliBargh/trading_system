import json
from datetime import datetime

import anthropic

from llm_input import build_llm_input

MODEL = "claude-haiku-4-5-20251001"
client = anthropic.Anthropic()

SYSTEM = """You are a BTC/USDT signal analyst. The user already holds BTC and wants to know, for the next 5-15 minutes, whether to BUY more, SELL some, or HOLD.
Input is a JSON snapshot: candles (columns in candle_columns, oldest first, per timeframe), indicators, funding/open interest, Fear&Greed, recent news, portfolio.
Rules:
- Round-trip fees are about 0.1%. Signal BUY/SELL only if the evidence for a move larger than that is clear and consistent across timeframes. Otherwise HOLD.
- Minute-level direction is mostly noise. Do not overreact to one candle or one indicator.
- Fear&Greed is a daily value; treat it as background only.
Reply with ONLY a JSON object:
{"signal": "BUY|SELL|HOLD", "confidence": 0.0-1.0, "reason": "max 2 sentences, in Persian"}"""


def analyze(btc_amount, usdt_cash):
    data, problems = build_llm_input(btc_amount, usdt_cash)
    if problems:
        return {"signal": None, "skipped": True, "problems": problems}

    resp = client.messages.create(
        model=MODEL,
        max_tokens=300,
        temperature=0.2,
        system=SYSTEM,
        messages=[
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
            {"role": "assistant", "content": "{"},  # مجبور کردن به شروع JSON
        ],
    )
    out = json.loads("{" + resp.content[0].text)

    assert out["signal"] in ("BUY", "SELL", "HOLD")
    out["confidence"] = min(max(float(out["confidence"]), 0.0), 1.0)

    # قوانین ریسک توسط کد، نه LLM
    if out["signal"] == "BUY" and usdt_cash < 10:
        out["signal"], out["reason"] = "HOLD", "موجودی USDT کافی نیست"
    if out["signal"] == "SELL" and btc_amount <= 0:
        out["signal"], out["reason"] = "HOLD", "BTC برای فروش نیست"

    out["usage"] = {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}
    out["close"] = data["features"]["1m"]["close"]
    out["ts"] = data["now_utc"]
    return out


if __name__ == "__main__":
    print(json.dumps(analyze(0.05, 1000), ensure_ascii=False, indent=2))