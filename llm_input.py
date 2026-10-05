import json
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import Derivative, FearGreed, engine
from features import EXCHANGE, TIMEFRAMES, compute_features, load_candles
from news import get_recent_news

PERP = "BTC/USDT:USDT"
N_CANDLES = 20
TF_MIN = {"1m": 1, "15m": 15, "1h": 60}
MAX_DERIV_AGE_MIN = 3
MAX_FNG_AGE_H = 36


def _candle_rows(df, n=N_CANDLES):
    tail = df.tail(n)
    return [
        [r.ts.strftime("%Y-%m-%d %H:%M"), r.open, r.high, r.low, r.close, round(r.volume, 2)]
        for r in tail.itertuples()
    ]


def _latest_derivatives(session):
    row = session.execute(
        select(Derivative)
        .where(Derivative.exchange == EXCHANGE, Derivative.symbol == PERP)
        .order_by(Derivative.ts.desc()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "ts": row.ts.isoformat(),
        "age_min": round((now - row.ts).total_seconds() / 60, 1),
        "funding_rate": row.funding_rate,
        "next_funding_ts": row.next_funding_ts.isoformat() if row.next_funding_ts else None,
        "oi_base_btc": row.oi_base,
    }


def _latest_fng(session):
    row = session.execute(
        select(FearGreed).order_by(FearGreed.ts.desc()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {"ts": row.ts.isoformat(), "age_h": round((now - row.ts).total_seconds() / 3600, 1),
            "value": row.value, "classification": row.classification}


def check_fresh(dfs, deriv, fng):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    problems = []
    for tf, df in dfs.items():
        tail = df.tail(N_CANDLES)
        if len(tail) < N_CANDLES:
            problems.append(f"{tf}: only {len(tail)} candles")
            continue
        lag = (now - tail["ts"].iloc[-1]).total_seconds() / 60
        if lag > 2 * TF_MIN[tf] + 2:
            problems.append(f"{tf}: last candle {lag:.0f} min old")
        if (tail["ts"].diff().dropna() != pd.Timedelta(minutes=TF_MIN[tf])).any():
            problems.append(f"{tf}: gap in last {N_CANDLES} candles")
    if deriv is None or deriv["age_min"] > MAX_DERIV_AGE_MIN:
        problems.append(f"derivatives stale: {deriv and deriv['age_min']} min")
    if fng is None or fng["age_h"] > MAX_FNG_AGE_H:
        problems.append("fear_greed stale or missing")
    return problems


def build_llm_input(btc_amount, usdt_cash):
    candles, features, dfs = {}, {}, {}
    for tf in TIMEFRAMES:
        df = load_candles(tf)
        dfs[tf] = df
        candles[tf] = _candle_rows(df)
        features[tf] = compute_features(df)

    with Session(engine) as session:
        deriv = _latest_derivatives(session)
        fng = _latest_fng(session)

    problems = check_fresh(dfs, deriv, fng)

    data = {
        "now_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "symbol": "BTC/USDT",
        "candle_columns": ["ts", "open", "high", "low", "close", "volume"],
        "candles": candles,
        "features": features,
        "derivatives": deriv,
        "fear_greed": fng,
        "news": get_recent_news(minutes=60),
        "portfolio": {"btc": btc_amount, "usdt": usdt_cash},
    }
    return data, problems


if __name__ == "__main__":
    data, problems = build_llm_input(btc_amount=0.05, usdt_cash=1000)
    print("problems:", problems)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("chars:", len(json.dumps(data, ensure_ascii=False)))