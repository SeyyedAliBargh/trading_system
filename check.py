from sqlalchemy import text
from db import engine

with engine.connect() as conn:
    rows = conn.execute(text(
        "select ts, funding_rate, oi_base from derivatives order by ts desc limit 5"
    )).all()
    for r in rows:
        print(r)


with engine.connect() as conn:
    rows = conn.execute(text(
        "select ts, value, classification from fear_greed order by ts desc limit 3"
    )).all()
    for r in rows:
        print(r)