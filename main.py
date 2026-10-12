import logging
import subprocess
import time
from datetime import datetime, timezone

import ccxt
from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
)
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from analyze import ATTEMPTS, PROMPT_VERSION, analyze
from db import Candle, Derivative, engine, init_db, ms_to_dt
from fng import collect_fng
from label import label_signals
from log_config import setup_logging
from news import collect_news

logger = logging.getLogger(__name__)

EXCHANGE = "okx"
SPOT = "BTC/USDT"
PERP = "BTC/USDT:USDT"
TIMEFRAMES = ["1m", "15m", "1h"]

_job_starts = {}


def get_code_version():
    try:
        v = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        return f"git-{v}"
    except Exception:
        return "1.0.0"


def collect_candles(ex, session, symbol, tf, limit=100):
    try:
        data = ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit)[:-1]
    except Exception:
        logger.error(
            "Candle fetch failed: exchange=%s symbol=%s timeframe=%s",
            EXCHANGE, symbol, tf, exc_info=True
        )
        raise
    rows = [
        dict(exchange=EXCHANGE, symbol=symbol, timeframe=tf, ts=ms_to_dt(t),
             open=o, high=h, low=l, close=c, volume=v)
        for t, o, h, l, c, v in data
    ]
    stored = 0
    if rows:
        result = session.execute(insert(Candle).values(rows).on_conflict_do_nothing())
        stored = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0
    logger.info(
        "Candles exchange=%s symbol=%s timeframe=%s: fetched=%d stored=%d",
        EXCHANGE, symbol, tf, len(rows), stored
    )
    return len(rows)


def collect_derivatives(ex, session, symbol):
    logger.info("Fetching derivatives exchange=%s symbol=%s timeframe=point-in-time", EXCHANGE, symbol)
    source = EXCHANGE
    fr = None
    oi = None
    try:
        fr = ex.fetch_funding_rate(symbol)
        oi = ex.fetch_open_interest(symbol)
    except Exception as e:
        logger.warning(
            "Primary derivatives fetch failed exchange=%s symbol=%s timeframe=point-in-time: %s. Attempting KuCoin fallback.",
            EXCHANGE, symbol, e
        )
        try:
            fallback = ccxt.kucoinfutures({"enableRateLimit": True})
            fr = fallback.fetch_funding_rate(symbol)
            oi = fallback.fetch_open_interest(symbol)
            source = "kucoinfutures"
            logger.info("Successfully fetched derivatives from fallback exchange=%s symbol=%s", source, symbol)
        except Exception:
            logger.error(
                "Derivatives fetch failed on primary and fallback exchange=kucoinfutures symbol=%s timeframe=point-in-time",
                symbol, exc_info=True
            )
            raise

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0, tzinfo=None)
    oi_base = oi.get("baseVolume")
    if oi_base is None and source == "kucoinfutures":
        oi_contracts = oi.get("openInterestAmount")
        if oi_contracts is not None:
            oi_base = round(float(oi_contracts) * 0.001, 4)

    row = dict(
        exchange=source, symbol=symbol, ts=now,
        funding_rate=fr.get("fundingRate"),
        next_funding_ts=ms_to_dt(fr.get("fundingTimestamp") or fr.get("nextFundingTimestamp")),
        oi_contracts=oi.get("openInterestAmount"),
        oi_base=oi_base,
        raw_funding=fr,
        raw_oi=oi,
    )
    result = session.execute(insert(Derivative).values([row]).on_conflict_do_nothing())
    stored = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0
    logger.info(
        "Derivatives exchange=%s symbol=%s timeframe=point-in-time: fetched=1 stored=%d",
        source, symbol, stored
    )


def run_analyze():
    logger.info("Starting scheduled analyze run")
    try:
        out = analyze(0.05, 1000)
        logger.info(
            "[analyze] signal=%s conf=%s model=%s skipped=%s %s",
            out.get("signal"),
            out.get("confidence"),
            out.get("model"),
            out.get("skipped", False),
            str(out.get("problems") or "")[:150],
        )
    except Exception:
        logger.exception("[analyze] run failed")


def run_once():
    logger.info("Starting collector run for candles and derivatives")
    ex = getattr(ccxt, EXCHANGE)({"enableRateLimit": True})
    with Session(engine) as session:
        for tf in TIMEFRAMES:
            collect_candles(ex, session, SPOT, tf)
        collect_derivatives(ex, session, PERP)
        try:
            session.commit()
            logger.info("Committed collected candles and derivatives to database")
        except Exception:
            logger.exception("Failed to commit collected market data to database")
            session.rollback()
            raise


def safe_run():
    try:
        run_once()
    except Exception:
        logger.exception("Market data collection failed; scheduler will continue")


def run_label():
    logger.info("Starting scheduled label run")
    try:
        label_signals()
    except Exception:
        logger.exception("[label] run failed")


def _on_job_submitted(event):
    _job_starts[event.job_id] = time.monotonic()


def _on_job_executed(event):
    duration = time.monotonic() - _job_starts.pop(event.job_id, time.monotonic())
    logger.info("Scheduler job '%s' executed successfully in %.3fs", event.job_id, duration)


def _on_job_error(event):
    duration = time.monotonic() - _job_starts.pop(event.job_id, time.monotonic())
    logger.error(
        "Scheduler job '%s' failed after %.3fs with error: %s\n%s",
        event.job_id, duration, event.exception, event.traceback or ""
    )


def _on_job_missed(event):
    logger.warning("Scheduler job '%s' missed execution window", event.job_id)


if __name__ == "__main__":
    log_level = setup_logging()
    code_version = get_code_version()
    provider_order = [f"{n}/{m}" for n, _, m in ATTEMPTS]

    logger.info(
        "Starting BTC/USDT AI Signal System | code_version=%s | prompt_version=%s | log_level=%s | providers=%s",
        code_version, PROMPT_VERSION, log_level, provider_order
    )

    init_db()
    safe_run()
    try:
        collect_fng(limit=2)
        collect_news()
    except Exception:
        logger.exception("Initial Fear & Greed / news collection failed")

    sched = BlockingScheduler(timezone="UTC")
    sched.add_listener(_on_job_submitted, EVENT_JOB_SUBMITTED)
    sched.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
    sched.add_listener(_on_job_error, EVENT_JOB_ERROR)
    sched.add_listener(_on_job_missed, EVENT_JOB_MISSED)

    sched.add_job(safe_run, "cron", minute="*", second=5,
                  max_instances=1, coalesce=True, id="collect_market", name="collect_market")
    sched.add_job(lambda: collect_fng(limit=2), "cron", minute=10, id="collect_fng", name="collect_fng")
    sched.add_job(collect_news, "interval", minutes=3,
                  max_instances=1, coalesce=True, id="collect_news", name="collect_news")
    sched.add_job(run_analyze, "cron", minute="*/5", second=20,
                  max_instances=1, coalesce=True, id="run_analyze", name="run_analyze")
    sched.add_job(run_label, "cron", minute="*/5", second=50,
                  max_instances=1, coalesce=True, id="run_label", name="run_label")

    logger.info("Scheduled jobs table:")
    for job in sched.get_jobs():
        logger.info("  - Job: %-15s | Trigger: %s", job.id, job.trigger)

    logger.info("Scheduler ready and starting. Press Ctrl+C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested. Shutting down scheduler cleanly...")
        sched.shutdown(wait=False)
        logger.info("System shutdown complete.")
