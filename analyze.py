import json
import os
from datetime import datetime, timezone

import openai
from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy.orm import Session

from db import Signal, engine
from llm_input import build_llm_input

load_dotenv()

PROMPT_VERSION = "v1"

or_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
    max_retries=0,
    timeout=45,
)

OR_MODELS = [
    "inclusionai/ling-3.1-flash:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-lightning:free",
]

ATTEMPTS = []  # (provider, client, model) به ترتیب تلاش
if os.getenv("GROQ_API_KEY") and os.getenv("GROQ_MODEL"):
    groq = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=os.environ["GROQ_API_KEY"],
        max_retries=0,
        timeout=45,
    )
    ATTEMPTS.append(("groq", groq, os.environ["GROQ_MODEL"]))
    
print("[analyze] attempts:", [f"{n}/{m}" for n, _, m in ATTEMPTS])

# v1
# SYSTEM = """You are a BTC/USDT signal analyst. The user already holds BTC and wants to know, for the next 5-15 minutes, whether to BUY more, SELL some, or HOLD.
# Input is a JSON snapshot: candles (columns in candle_columns, oldest first, per timeframe), indicators, funding/open interest, Fear&Greed, recent news, portfolio.
# Rules:
# - Round-trip fees are about 0.1%. Signal BUY/SELL only if the evidence for a move larger than that is clear and consistent across timeframes. Otherwise HOLD.
# - Minute-level direction is mostly noise. Do not overreact to one candle or one indicator.
# - Fear&Greed is a daily value; treat it as background only.
# Reply with ONLY a JSON object:
# {"signal": "BUY|SELL|HOLD", "confidence": 0.0-1.0, "reason": "max 2 sentences, in Persian"}
# Output must start with { and contain no other text."""


SYSTEM = """You are a BTC/USDT signal analyst. The user already holds BTC and wants to know, for the next 5-15 minutes, whether to BUY more, SELL some, or HOLD.
Input is a JSON snapshot: candles (columns in candle_columns, oldest first, per timeframe), indicators, funding/open interest, Fear&Greed, recent news, portfolio.
Rules:
- Round-trip fees are about 0.1%. Signal BUY/SELL only if the evidence for a move larger than that is clear and consistent across timeframes. Otherwise HOLD.
- Minute-level direction is mostly noise. Do not overreact to one candle or one indicator.
- Fear&Greed is a daily value; treat it as background only.
- confidence is your estimated probability (0.0-1.0) that price moves in the signalled direction by more than 0.1% within 15 minutes. For HOLD it is the probability that the move stays within ±0.1%. 0.5 means no edge; use the full range.
- reason: max 2 sentences in Persian. Cite only numbers that appear in the input; never mention data that is not in the input. English only for tickers and indicator names.
Reply with ONLY a JSON object:
{"signal": "BUY|SELL|HOLD", "confidence": 0.0, "reason": "..."}
Output must start with { and contain no other text."""

def save_signal(out, data, raw, model):
    now = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    usage = out.get("usage") or {}
    with Session(engine) as s:
        s.add(Signal(
            ts=now,
            close=out.get("close"),
            input_json=data,
            raw_output=raw,
            signal=out.get("signal"),
            confidence=out.get("confidence"),
            reason=out.get("reason"),
            tokens_in=usage.get("in"),
            tokens_out=usage.get("out"),
            prompt_version=PROMPT_VERSION,
            model=model,
            skipped=bool(out.get("skipped")),
            problems=out.get("problems"),
        ))
        s.commit()


def skip(problem, close, data, raw=None, model=None, usage=None):
    out = {"signal": None, "skipped": True, "problems": [problem], "close": close}
    if usage:
        out["usage"] = usage
    save_signal(out, data, raw, model)
    return out


def analyze(btc_amount, usdt_cash):
    data, problems = build_llm_input(btc_amount, usdt_cash)
    close = data["features"]["1m"]["close"]

    if problems:
        out = {"signal": None, "skipped": True, "problems": problems, "close": close}
        save_signal(out, data, None, None)
        return out

    errors = []
    resp = None
    for name, cl, model in ATTEMPTS:
        tag = f"{name}/{model}"
        try:
            r = cl.chat.completions.create(
                model=model,
                max_tokens=5000,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
                ],
            )
            if not r.choices:  # گاهی ۲۰۰ با بدنه‌ی error
                errors.append(f"{tag}: no choices {getattr(r, 'error', None)}")
                continue
            resp = r
            break
        except openai.APITimeoutError:
            errors.append(f"{tag}: timeout")
        except openai.APIStatusError as e:  # شامل 429 و 404 و 5xx
            errors.append(f"{tag}: http {e.status_code} {getattr(e, 'body', e)}")
        except openai.APIConnectionError as e:
            errors.append(f"{tag}: connection {e}")
        except Exception as e:
            errors.append(f"{tag}: unexpected {type(e).__name__}: {e}")

    if resp is None:  # همه‌ی مدل‌ها شکست خوردند
        out = {"signal": None, "skipped": True, "problems": errors, "close": close}
        save_signal(out, data, None, None)
        return out

    choice = resp.choices[0]
    txt = (choice.message.content or "").strip()
    u = resp.usage
    usage = {"in": u.prompt_tokens, "out": u.completion_tokens} if u else {}

    if choice.finish_reason == "length":
        return skip("truncated (finish_reason=length)", close, data, txt, resp.model, usage)
    if not txt:
        return skip("empty content", close, data, txt, resp.model, usage)

    try:
        out = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        assert out["signal"] in ("BUY", "SELL", "HOLD")
        out["confidence"] = min(max(float(out["confidence"]), 0.0), 1.0)
    except Exception as e:
        return skip(f"bad model output: {e}", close, data, txt, resp.model, usage)

    # قوانین ریسک توسط کد، نه LLM
    if out["signal"] == "BUY" and usdt_cash < 10:
        out["signal"], out["reason"] = "HOLD", "موجودی USDT کافی نیست"
    if out["signal"] == "SELL" and btc_amount <= 0:
        out["signal"], out["reason"] = "HOLD", "BTC برای فروش نیست"

    out["usage"] = usage
    out["close"] = close
    out["ts"] = data["now_utc"]
    out["model"] = resp.model
    out["problems"] = errors or None
    save_signal(out, data, txt, resp.model)
    return out


if __name__ == "__main__":
    print(json.dumps(analyze(0.05, 1000), ensure_ascii=False, indent=2))