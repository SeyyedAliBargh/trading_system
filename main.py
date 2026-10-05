from datetime import datetime, timezone

import ccxt
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from db import Candle, Derivative, engine, init_db, ms_to_dt
from fng import collect_fng

EXCHANGE = "okx"
SPOT = "BTC/USDT"
PERP = "BTC/USDT:USDT"
TIMEFRAMES = ["1m", "15m", "1h"]


def collect_candles(ex, session, symbol, tf, limit=100):
    data = ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit)[:-1]  # حذف کندل بازِ آخر
    rows = [
        dict(exchange=EXCHANGE, symbol=symbol, timeframe=tf, ts=ms_to_dt(t),
             open=o, high=h, low=l, close=c, volume=v)
        for t, o, h, l, c, v in data
    ]
    if rows:
        session.execute(insert(Candle).values(rows).on_conflict_do_nothing())
    return len(rows)


def collect_derivatives(ex, session, symbol):
    fr = ex.fetch_funding_rate(symbol)
    oi = ex.fetch_open_interest(symbol)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0, tzinfo=None)
    row = dict(
        exchange=EXCHANGE, symbol=symbol, ts=now,
        funding_rate=fr.get("fundingRate"),
        next_funding_ts=ms_to_dt(fr.get("nextFundingTimestamp") or fr.get("fundingTimestamp")),
        oi_contracts=oi.get("openInterestAmount"),
        oi_base=oi.get("baseVolume"),
        raw_funding=fr,
        raw_oi=oi,
    )
    session.execute(insert(Derivative).values([row]).on_conflict_do_nothing())


def run_once():
    ex = getattr(ccxt, EXCHANGE)({"enableRateLimit": True})
    with Session(engine) as session:
        for tf in TIMEFRAMES:
            n = collect_candles(ex, session, SPOT, tf)
            print(f"{datetime.now():%H:%M:%S} candles {tf}: {n} rows")
        collect_derivatives(ex, session, PERP)
        session.commit()


def safe_run():
    try:
        run_once()
    except Exception as e:
        print("run failed:", e)  # یک خطای موقت نباید برنامه رو بکشه


if __name__ == "__main__":
    init_db()
    safe_run()  # یک بار فوراً
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(safe_run, "cron", minute="*", second=5,
                  max_instances=1, coalesce=True)
    sched.add_job(lambda: collect_fng(limit=2), "cron", minute=10)
    print("scheduler started, Ctrl+C to stop")
    sched.start()