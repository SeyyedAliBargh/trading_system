import requests
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from db import FearGreed, engine, init_db, ms_to_dt

URL = "https://api.alternative.me/fng/"


def collect_fng(limit=30):
    r = requests.get(URL, params={"limit": limit, "format": "json"}, timeout=15)
    r.raise_for_status()
    items = r.json()["data"]
    rows = [
        dict(ts=ms_to_dt(int(i["timestamp"]) * 1000),  # timestamp این API ثانیه‌ست
             value=int(i["value"]),
             classification=i["value_classification"],
             raw=i)
        for i in items
    ]
    with Session(engine) as session:
        result = session.execute(insert(FearGreed).values(rows).on_conflict_do_nothing())
        session.commit()
    return result.rowcount


if __name__ == "__main__":
    init_db()
    print("new rows:", collect_fng(limit=30))