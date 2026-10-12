import logging
import requests
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from db import FearGreed, engine, init_db, ms_to_dt
from log_config import setup_logging

logger = logging.getLogger(__name__)

URL = "https://api.alternative.me/fng/"


def collect_fng(limit=30):
    logger.info("Fetching Fear & Greed data: limit=%d", limit)
    try:
        r = requests.get(URL, params={"limit": limit, "format": "json"}, timeout=15)
        r.raise_for_status()
        items = r.json().get("data", [])
    except Exception:
        logger.exception("Fear & Greed fetch failed from %s", URL)
        raise

    rows = [
        dict(ts=ms_to_dt(int(i["timestamp"]) * 1000),  # timestamp is in seconds
             value=int(i["value"]),
             classification=i["value_classification"],
             raw=i)
        for i in items
    ]
    stored = 0
    if rows:
        with Session(engine) as session:
            try:
                result = session.execute(insert(FearGreed).values(rows).on_conflict_do_nothing())
                session.commit()
                stored = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0
            except Exception:
                logger.exception("Failed to insert/commit Fear & Greed rows to database")
                session.rollback()
                raise
    logger.info("Fear & Greed: fetched=%d stored=%d", len(rows), stored)
    return stored


if __name__ == "__main__":
    setup_logging(console_only=True)
    init_db()
    print("new rows:", collect_fng(limit=30))
