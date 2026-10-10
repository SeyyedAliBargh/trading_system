import pandas as pd
from sqlalchemy import text

from db import engine
from features import EXCHANGE, load_candles

SWAP = "BTC/USDT:USDT"  # با خروجی کوئری پایین چک کن


def load_derivs(limit=120, symbol=SWAP):
    q = text(
        "select ts, funding_rate, next_funding_ts, oi_base from derivatives "
        "where exchange=:ex and symbol=:sym order by ts desc limit :n"
    )
    df = pd.read_sql(q, engine, params={"ex": EXCHANGE, "sym": symbol, "n": limit},
                     parse_dates=["ts", "next_funding_ts"])
    return df.sort_values("ts").reset_index(drop=True)


def _oi_chg(df, minutes):
    last = df.iloc[-1]
    past = df[df["ts"] <= last["ts"] - pd.Timedelta(minutes=minutes)]
    if past.empty:
        return None
    base = past.iloc[-1]["oi_base"]
    if pd.isna(base) or base == 0 or pd.isna(last["oi_base"]):
        return None
    return round((last["oi_base"] / base - 1) * 100, 3)


def derivative_features():
    df = load_derivs()
    if df.empty:
        return None
    last = df.iloc[-1]
    c = load_candles("1m", limit=30)
    price_chg = (round((c["close"].iloc[-1] / c["close"].iloc[-16] - 1) * 100, 3)
                 if len(c) >= 16 else None)
    nxt = last["next_funding_ts"]
    feats = {
        "ts": str(last["ts"]),
        "funding_rate": last["funding_rate"],
        "mins_to_funding": None if pd.isna(nxt) else round((nxt - last["ts"]).total_seconds() / 60),
        "oi_btc": last["oi_base"],
        "oi_chg_5m_pct": _oi_chg(df, 5),
        "oi_chg_15m_pct": _oi_chg(df, 15),
        "oi_chg_60m_pct": _oi_chg(df, 60),
        "price_chg_15m_pct": price_chg,  # تا رابطه‌ی OI و قیمت دیده شود
    }
    return {k: v if k == "ts" else (None if pd.isna(v) else float(v))
            for k, v in feats.items()}


if __name__ == "__main__":
    print(derivative_features())