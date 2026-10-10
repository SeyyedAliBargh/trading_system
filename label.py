from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, bindparam, select, text
from sqlalchemy.orm import Session

from db import Signal, engine
from features import EXCHANGE, SPOT

HORIZONS = {"price_5m": 5, "price_15m": 15, "price_30m": 30}
LOOKBACK_H = 48

_Q = text(
    "select close from candles "
    "where exchange=:ex and symbol=:sym and timeframe='1m' and ts=:t"
).bindparams(bindparam("t", type_=DateTime))


def label_signals():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = now - timedelta(hours=LOOKBACK_H)
    done = 0
    with Session(engine) as s:
        rows = s.scalars(
            select(Signal).where(
                Signal.ts >= since,
                Signal.price_5m.is_(None) | Signal.price_15m.is_(None) | Signal.price_30m.is_(None),
            )
        ).all()
        for sig in rows:
            try:
                t0 = datetime.fromisoformat(
                    sig.input_json["features"]["1m"]["ts"]
                ).replace(tzinfo=None)
            except Exception:
                continue
            for col, minutes in HORIZONS.items():
                if getattr(sig, col) is not None:
                    continue
                target = t0 + timedelta(minutes=minutes)
                if target + timedelta(minutes=1) > now:  # هنوز نرسیده
                    continue
                px = s.execute(_Q, {"ex": EXCHANGE, "sym": SPOT, "t": target}).scalar()
                if px is not None:
                    setattr(sig, col, float(px))
                    done += 1
        s.commit()
    print(f"[label] filled {done}")
    return done


if __name__ == "__main__":
    label_signals()