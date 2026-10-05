# BTC/USDT AI Signal System

An early-stage prototype that produces one of three signals every minute for BTC/USDT: `BUY / SELL / HOLD`, along with a `confidence` score and a short `reason`.

> ⚠️ This is a research prototype only. **No real orders are placed** and no positions are tracked. Outputs are not financial advice.

## Idea
Assumption: the user already holds BTC and only wants to know whether to **buy more, sell some, or hold** over the next few minutes.

Project path:
1. **First prototype:** an LLM (Claude) produces a signal from a market snapshot.
2. **Next prototype:** a classic ML model (XGBoost/LightGBM) is trained on the collected logs and compared against the LLM.

**Success criterion:** a complete pipeline and an honest backtest/log, not profitability. Predicting price direction at the minute level is very hard, and most models lose money after fees.

## Architecture

```
OKX (ccxt) ────► main.py ──► SQLite (trade.db)
alternative.me ► fng.py ──►      │
                                 ▼
                    features.py (RSI, EMA, ATR, relative volume)
                                 │
news.py (mock for now) ──────────┤
                                 ▼
                    llm_input.py → check_fresh() → build_llm_input()
                                 │
                                 ▼
                    analyze.py → LLM → validation + risk rules
                                 │
                                 ▼
                    {"signal", "confidence", "reason", ...}
```

If the data is stale, the LLM is **not called at all** (`skipped`).

## File structure

```
trade/
├── analyze.py        # LLM call, output validation, risk rules
├── check.py          # quick query to inspect derivatives and fear_greed rows
├── db.py             # models, init_db(), ms_to_dt()
├── features.py       # load_candles() and compute_features()
├── fng.py            # Fear & Greed fetcher (alternative.me)
├── llm_input.py      # build_llm_input() and check_fresh()
├── main.py           # candle + funding/OI collection with scheduler
├── news.py           # get_recent_news(minutes=60) (mock for now)
├── requirements.txt
└── trade.db          # SQLite database (do not commit)
```

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
set ANTHROPIC_API_KEY=...      # only needed for analyze.py
```

Run:

```bash
# Terminal 1: data collection (must stay open)
python main.py

# Terminal 2:
python llm_input.py     # see the full LLM input and the problems list
python analyze.py       # get a signal
python check.py         # inspect the latest DB rows
```

> `main.py` must keep running. Funding and OI are point-in-time values and cannot be backfilled for downtime. Candles are only backfilled up to 100 candles back (about 1h40m for 1m).

## Technical decisions

| Topic | Decision |
|---|---|
| Exchange | OKX (Binance returns 451 and Bybit returns 403 from Iranian IPs). Fallback for funding/OI: KuCoin Futures |
| Database | SQLite via SQLAlchemy; change `DB_URL` in `db.py` to move to PostgreSQL |
| Scheduling | APScheduler (not Celery, not multiprocessing) |
| OI unit | `oi_base` (in BTC). Old and new data are not comparable if the exchange changes |
| LLM | `claude-haiku-4-5-20251001`, temperature 0.2, `max_tokens=300`, JSON output |
| Risk | Volume caps, stop-loss and position size are set by **code**, not the LLM |
| Time | Everything in UTC (Iran = UTC + 3:30) |

## Database tables

- **`candles`**: PK = (exchange, symbol, timeframe, ts). Columns: open, high, low, close, volume
- **`derivatives`**: PK = (exchange, symbol, ts). Columns: funding_rate, next_funding_ts, oi_contracts, oi_base, raw_funding, raw_oi
- **`fear_greed`**: PK = ts (start of day, UTC). Columns: value (0 to 100), classification, raw

## LLM input

`build_llm_input(btc, usdt)` builds a dictionary with these sections (about 1500 to 2000 tokens):

| Key | Content | Why |
|---|---|---|
| `now_utc` | Current time | The LLM has no clock |
| `candles` | Last 20 candles for 1m, 15m and 1h as `[ts, o, h, l, c, v]` | Short-term move + larger trend |
| `features` | RSI14, distance from EMA20/EMA50, ATR14 %, relative volume (latest value per timeframe) | Don't make the LLM do the math |
| `derivatives` | `funding_rate`, `next_funding_ts`, `oi_base_btc`, `age_min` | Crowding in leveraged positions |
| `fear_greed` | Today's value and class | Broad market background |
| `news` | News from the last 60 minutes | Events not yet reflected in price |
| `portfolio` | `{btc, usdt}` | "Buy or sell" depends on holdings |

**Output of `analyze.py`:**
```json
{"signal": "BUY|SELL|HOLD", "confidence": 0.0-1.0, "reason": "...", "usage": {...}, "close": ..., "ts": "..."}
```

Note: the `reason` field is currently written in Persian (set in the system prompt in `analyze.py`).

## Data freshness check
Before every analysis, `check_fresh()` verifies the following; if any fail, the LLM is not called:
- Not enough candles
- Last candle is older than `2 × timeframe + 2` minutes
- Gap within the last 20 candles
- Derivatives older than 3 minutes
- Fear & Greed older than 36 hours

## Current status
- ✅ Candle, funding/OI and Fear & Greed collection
- ✅ Feature computation
- ✅ LLM input builder and freshness check
- ✅ LLM call and output validation
- ⏳ Quality of `reason` and confidence not yet reviewed with fresh data
- ⏳ News is still a mock

## Roadmap
1. Review signal quality with fresh data and refine the prompt
2. Derivatives features: OI % change (15 min, 1 h, 4 h) and funding/OI z-scores
3. Signal log table (full input, model output, price at signal time)
4. Hook `analyze` into the scheduler (one call per closed 1m candle)
5. Outcome labeling: price 5/15/30 minutes after each signal
6. Multi-week paper trading (logging only)
7. Evaluation including fees and slippage
8. ML stage (XGBoost/LightGBM) and out-of-sample comparison with the LLM
9. Unattended operation (Windows Task Scheduler or a server)

Optional/later: order book and imbalance, economic calendar (CPI, rate decisions), tweets and social media, macro data (FRED) and Coinglass.

## How to contribute

**Real news (current need):** only the body of `get_recent_news(minutes=60)` in `news.py` needs to be replaced with a real source (RSS or CryptoPanic). The output contract is fixed:

```python
[
  {
    "published_at": "2026-10-03T20:24:10+00:00",  # ISO, UTC
    "source": "...",
    "title": "...",
    "summary": "..."
  },
  ...
]
```
Sorted newest to oldest, no duplicates, and only items from the last `minutes` minutes.

**General rules:**
- Always use UTC
- Keep changes small and targeted; don't rewrite whole files
- Keep it simple and avoid over-engineering
- Test with real data and include real output in your PR/message
- Every new feature must be added in `features.py`/`llm_input.py` and documented in the "LLM input" section of this README
- Never commit `trade.db`, `venv/` or API keys

## Known risks and notes
- The mock news is fake but the LLM treats it as real, which pollutes the logs; until the real version lands, it is better to send `"news": []`
- Cost: about 1440 calls per day; compute the exact cost from the `usage` field before enabling automatic runs
- Unusual volumes appear in some 15m and 1h candles (e.g. 381 and 417 vs. a typical 5 to 20), which affects `rel_volume`; not yet cross-checked against OKX
- In `main.py`, `ex` is created every minute and ccxt reloads markets each time (optional optimization: create it once at module level)
- The `rows` number printed by `main.py` is the number of candles fetched, not the number of new rows stored