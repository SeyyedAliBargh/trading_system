# pip install pandas
import pandas as pd
from sqlalchemy import text

from db import engine

EXCHANGE = "okx"
SPOT = "BTC/USDT"
TIMEFRAMES = ["1m", "15m", "1h"]


def load_candles(timeframe, limit=200, symbol=SPOT):
    q = text(
        "select ts, open, high, low, close, volume from candles "
        "where exchange=:ex and symbol=:sym and timeframe=:tf "
        "order by ts desc limit :n"
    )
    df = pd.read_sql(q, engine, params={"ex": EXCHANGE, "sym": symbol, "tf": timeframe, "n": limit},
                     parse_dates=["ts"])
    return df.sort_values("ts").reset_index(drop=True)


def rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + avg_gain / avg_loss)


def ema(close, n):
    return close.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def compute_features(df):
    close = df["close"]
    last = len(df) - 1
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    atr14 = atr(df, 14)
    rel_vol = df["volume"] / df["volume"].rolling(20).mean()

    feats = {
        "ts": df["ts"].iloc[last],
        "close": round(close.iloc[last], 2),
        "rsi14": round(rsi(close, 14).iloc[last], 1),
        "ema20_dist_pct": round((close.iloc[last] / ema20.iloc[last] - 1) * 100, 3),
        "ema50_dist_pct": round((close.iloc[last] / ema50.iloc[last] - 1) * 100, 3),
        "atr14_pct": round(atr14.iloc[last] / close.iloc[last] * 100, 3),
        "rel_volume": round(rel_vol.iloc[last], 2),
    }
    return {
        k: str(v) if k == "ts" else (None if pd.isna(v) else float(v))
        for k, v in feats.items()
    }

if __name__ == "__main__":
    for tf in TIMEFRAMES:
        df = load_candles(tf)
        print(tf, len(df), "candles")
        print(compute_features(df))