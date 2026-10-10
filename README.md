# BTC/USDT AI Signal System

An early-stage prototype that produces one of three signals every 5 minutes for BTC/USDT: `BUY / SELL / HOLD`, along with a `confidence` score and a short `reason`.

> ⚠️ This is a research prototype only. **No real orders are placed** and no positions are tracked. Outputs are not financial advice.

## Idea
Assumption: the user already holds BTC and only wants to know whether to **buy more, sell some, or hold** over the next 5 to 15 minutes.

Project path:
1. **First prototype:** an LLM produces a signal from a market snapshot, and every signal is logged and labeled with the realized price.
2. **Next prototype:** a classic ML model (XGBoost/LightGBM) is trained on the collected logs and compared against the LLM.

**Success criterion:** a complete pipeline and an honest evaluation, not profitability. Predicting price direction at the minute level is very hard, and most models lose money after fees.

## Architecture

```
OKX (ccxt) ────► main.py ──► SQLite (trade.db)
alternative.me ► fng.py ──►      │
RSS (4 feeds) ─► news.py ──►     │
                                 ▼
                    features.py (RSI, EMA, ATR, relative volume)
                                 │
                                 ▼
                    llm_input.py → check_fresh() → build_llm_input()
                                 │
                                 ▼
                    analyze.py → providers in order (Groq, then OpenRouter)
                                 │
                                 ▼
                    signals table (input, output, errors)
                                 │
                                 ▼
                    label.py → price_5m / price_15m / price_30m
```

If the data is stale, the LLM is **not called at all** and a row with `skipped=1` is stored.

## File structure

```
trade/
├── analyze.py         # provider fallback loop, output validation, SYSTEM prompt
├── check.py           # quick query to inspect derivatives and fear_greed rows
├── db.py              # models, init_db(), ms_to_dt()
├── deriv_features.py  # funding/OI features (not yet fed to the LLM)
├── features.py        # load_candles() and compute_features()
├── fng.py             # Fear & Greed fetcher (alternative.me)
├── label.py           # fills price_5m/15m/30m for past signals
├── llm_input.py       # build_llm_input() and check_fresh()
├── main.py            # collectors + scheduler (also runs analyze and label)
├── news.py            # RSS collection and get_recent_news(minutes=60)
├── requirements.txt
├── .env               # API keys (do not commit)
└── trade.db           # SQLite database (do not commit)
```

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Create a `.env` file:

```
OPENROUTER_API_KEY=...
GROQ_API_KEY=...
GROQ_MODEL=qwen/qwen3.8-27b
```

Run:

```bash
# Terminal 1: collection + analysis + labeling (must stay open)
python main.py

# Optional manual checks:
python llm_input.py     # see the full LLM input and the problems list
python analyze.py       # one manual analysis
python check.py         # inspect the latest DB rows
```

At startup, `analyze.py` prints `[analyze] attempts: ...` showing the real provider order. Every 5 minutes you should see `[analyze] ...` and `[label] filled N` in the console.

> `main.py` must keep running. Funding and OI are point-in-time values and cannot be backfilled for downtime, and `analyze` writes `skipped` rows while data is stale. Candles are only backfilled up to 100 candles back (about 1h40m for 1m). Code changes take effect only after restarting `main.py`.

## Scheduler

| Job | Schedule |
|---|---|
| Candles, funding/OI | every minute |
| News (RSS) | every 3 minutes |
| `run_analyze` | every 5 minutes, at `second=20` |
| `run_label` | every 5 minutes, at `second=50` |

The 5-minute interval keeps usage well under the daily limits of free tiers. If a provider's daily token limit is lower than expected, lengthen the interval to 10 to 15 minutes.

## Technical decisions

| Topic | Decision |
|---|---|
| Exchange | OKX (Binance returns 451 and Bybit returns 403 from Iranian IPs). Fallback for funding/OI: KuCoin Futures |
| Database | SQLite via SQLAlchemy; change `DB_URL` in `db.py` to move to PostgreSQL |
| Scheduling | APScheduler (not Celery, not multiprocessing) |
| OI unit | `oi_base` (in BTC). Old and new data are not comparable if the exchange changes |
| LLM | Groq `qwen/qwen3.8-27b` first (non-reasoning, about 100 output tokens), then OpenRouter free models as fallback, tried in order. Errors of failed attempts are kept in the `problems` column. `max_retries=0` (SDK retries burn the daily 429 quota), `max_tokens=5000`, timeout 45s |
| Dropped provider | Mistral (Experiment plan needs phone verification, and requests may be used for training) |
| Prompt | `SYSTEM` in `analyze.py`, versioned by `PROMPT_VERSION` (currently `v2`). Change the version with every edit of `SYSTEM` |
| Risk | Volume caps, stop-loss and position size are set by **code**, not the LLM |
| Portfolio | Fixed `analyze(0.05, 1000)` until paper trading starts |
| Time | Everything in UTC (Iran = UTC + 3:30) |

Model and provider names change without notice on free tiers, so they are kept separate from the code logic (`OR_MODELS`, `.env`).

## Database tables

- **`candles`**: PK = (exchange, symbol, timeframe, ts). Columns: open, high, low, close, volume
- **`derivatives`**: PK = (exchange, symbol, ts). Columns: funding_rate, next_funding_ts, oi_contracts, oi_base, raw_funding, raw_oi
- **`fear_greed`**: PK = ts (start of day, UTC). Columns: value (0 to 100), classification, raw
- **`news`**: one row per RSS item, deduplicated by URL. Columns include `published_at` and `fetched_at`
- **`signals`**: one row per analysis. Columns include `ts`, `model`, `prompt_version`, `signal`, `confidence`, `reason`, `close`, `input_json`, `skipped`, `problems`, `price_5m`, `price_15m`, `price_30m`

## LLM input

`build_llm_input(btc, usdt)` builds a dictionary with these sections (about 4500 tokens, most of it raw candles):

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

`confidence` is defined in the prompt as the estimated probability that price moves more than 0.1% in the signalled direction within 15 minutes (for HOLD: that it stays within ±0.1%). The `reason` is written in Persian and must cite only numbers present in the input.

## Data freshness check
Before every analysis, `check_fresh()` verifies the following; if any fail, the LLM is not called:
- Not enough candles
- Last candle is older than `2 × timeframe + 2` minutes
- Gap within the last 20 candles
- Derivatives older than 3 minutes
- Fear & Greed older than 36 hours

## Evaluation rules
- Use only rows with `skipped=0`
- Always split by the `model` column: different models give different signals on the same input
- Evaluate only after a few hundred rows, and compare against baselines (always HOLD, previous 15-minute direction), not against zero
- Keep the prompt fixed while collecting; change `PROMPT_VERSION` with every prompt edit
- For ML, keep only signals collected after continuous collection began (the first news run has identical `fetched_at` values)

Example query:
```sql
SELECT model, signal, COUNT(*), ROUND(AVG((price_15m/close-1)*100), 4)
FROM signals
WHERE skipped=0 AND price_15m IS NOT NULL
GROUP BY model, signal;
```

## Current status
- ✅ Candle, funding/OI and Fear & Greed collection
- ✅ Real news via 4 RSS feeds (coindesk, cointelegraph, decrypt, theblock)
- ✅ Feature computation, LLM input builder and freshness check
- ✅ LLM call with provider fallback and output validation
- ✅ Signal log table and scheduled analysis every 5 minutes
- ✅ Outcome labeling (price after 5/15/30 minutes)
- ✅ `deriv_features.py` built (not yet fed to the LLM)
- ✅ Prompt v2 (defined confidence, grounded reason)
- ⏳ Collecting enough continuous rows for a first honest evaluation
- ⏳ Unattended operation

## Roadmap
1. Run continuously and review signal quality (format, consistency, grounding of `reason`, predictive value vs baselines)
2. Decide the role of news: direct signal or qualitative context. Consider a 180-minute window plus a prompt line ("news older than 60 minutes is context only") as `v3`
3. Feed `deriv_features` into the LLM input (after the baseline), and add ready-made returns (`ret_5m/15m/1h/4h`) to `features`
4. Multi-week paper trading (logging only)
5. Evaluation including fees and slippage
6. ML stage (XGBoost/LightGBM) and out-of-sample comparison with the LLM
7. Unattended operation (Windows Task Scheduler or a server)

Optional/later: order book and imbalance, economic calendar (CPI, rate decisions), macro news, tweets and social media, macro data (FRED) and Coinglass.

## How to contribute

**General rules:**
- Always use UTC
- Keep changes small and targeted; don't rewrite whole files
- Keep it simple and avoid over-engineering
- Test with real data and include real output in your PR/message
- Every new feature must be added in `features.py`/`llm_input.py` and documented in the "LLM input" section of this README
- Never commit `trade.db`, `venv/`, `.env` or API keys

## Known risks and notes
- RSS delay is large relative to the 5 to 15 minute horizon, the keyword filter is almost ineffective (all sources are crypto-only), deduplication is by URL only (one event from several sites counts several times), and macro news is not covered
- Free-tier limits (daily tokens, 429s from shared upstream pools) decide the scheduler interval and which fallbacks work; check the provider's limits before shortening it
- Different models give different signals on the same input
- `reason` can contain content that is not in the input, so do not trust it; `confidence` was nearly constant before prompt v2
- Any downtime of `main.py` creates a permanent gap in the data (derivatives cannot be backfilled)
- Old `derivatives` rows written before the `next_funding_ts` fix are off by +8 hours (the column is not used anywhere yet); back up `trade.db` before running the correcting `UPDATE`
- In `main.py`, `ex` is created every minute and ccxt reloads markets each time (optional optimization: create it once at module level)
- The `rows` number printed by `main.py` is the number of candles fetched, not the number of new rows stored