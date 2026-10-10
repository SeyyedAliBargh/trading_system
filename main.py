from datetime import datetime, timezone
from news import collect_news
import ccxt
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session
from analyze import analyze
from label import label_signals
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
        next_funding_ts=ms_to_dt(fr.get("fundingTimestamp") or fr.get("nextFundingTimestamp")),
        oi_contracts=oi.get("openInterestAmount"),
        oi_base=oi.get("baseVolume"),
        raw_funding=fr,
        raw_oi=oi,
    )
    session.execute(insert(Derivative).values([row]).on_conflict_do_nothing())


def run_analyze():
    try:
        out = analyze(0.05, 1000)
        print(f"[analyze] {out.get('signal')} conf={out.get('confidence')} "
              f"model={out.get('model')} skipped={out.get('skipped', False)} "
              f"{str(out.get('problems') or '')[:150]}")
    except Exception as e:
        print("[analyze] failed:", e)

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

def run_label():
    try:
        label_signals()
    except Exception as e:
        print("[label] failed:", e)


if __name__ == "__main__":
    init_db()
    safe_run()  # یک بار فوراً
    try:
        collect_fng(limit=2)
        collect_news()
    except Exception as e:
        print("initial fng/news failed:", e)

    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(safe_run, "cron", minute="*", second=5,
                  max_instances=1, coalesce=True)
    print("scheduler started")
    sched.add_job(lambda: collect_fng(limit=2), "cron", minute=10)
    print("fng scheduler started")
    sched.add_job(collect_news, "interval", minutes=3,
                  max_instances=1, coalesce=True)
    print("news scheduler started")
    sched.add_job(run_analyze, "cron", minute="*/5", second=20,
                  max_instances=1, coalesce=True)
    print("analyze scheduler started")
    sched.add_job(run_label, "cron", minute="*/5", second=50,
                  max_instances=1, coalesce=True)
    print("labe scheduler started\n")
    print("scheduler all started, Ctrl+C to stop")
    sched.start()