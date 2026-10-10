from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, PrimaryKeyConstraint, String, create_engine, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DB_URL = "sqlite:///trade.db"
engine = create_engine(DB_URL)


class Base(DeclarativeBase):
    pass


class Candle(Base):
    __tablename__ = "candles"
    exchange: Mapped[str] = mapped_column(String)
    symbol: Mapped[str] = mapped_column(String)
    timeframe: Mapped[str] = mapped_column(String)
    ts: Mapped[datetime] = mapped_column(DateTime)  # UTC
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    __table_args__ = (PrimaryKeyConstraint("exchange", "symbol", "timeframe", "ts"),)


class Derivative(Base):
    __tablename__ = "derivatives"
    exchange: Mapped[str] = mapped_column(String)
    symbol: Mapped[str] = mapped_column(String)
    ts: Mapped[datetime] = mapped_column(DateTime)  # زمان جمع‌آوری، گرد شده به دقیقه (UTC)
    funding_rate: Mapped[float | None] = mapped_column(Float)
    next_funding_ts: Mapped[datetime | None] = mapped_column(DateTime)
    oi_contracts: Mapped[float | None] = mapped_column(Float)  # openInterestAmount
    oi_base: Mapped[float | None] = mapped_column(Float)       # baseVolume (برحسب BTC)
    raw_funding: Mapped[dict | None] = mapped_column(JSON)
    raw_oi: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (PrimaryKeyConstraint("exchange", "symbol", "ts"),)

class FearGreed(Base):
    __tablename__ = "fear_greed"
    ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)  # شروع روز، UTC
    value: Mapped[int] = mapped_column(Integer)                       # ۰ تا ۱۰۰
    classification: Mapped[str] = mapped_column(String)               # مثلاً "Fear"
    raw: Mapped[dict] = mapped_column(JSON)

class News(Base):
    __tablename__ = "news"

    url: Mapped[str] = mapped_column(String, primary_key=True)  # بدون query string
    source: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[Optional[str]] = mapped_column(String)
    published_at: Mapped[datetime] = mapped_column(DateTime)  # UTC
    fetched_at: Mapped[datetime] = mapped_column(DateTime)    # UTC

class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    close: Mapped[Optional[float]] = mapped_column(Float)
    input_json: Mapped[Optional[dict]] = mapped_column(JSON)
    raw_output: Mapped[Optional[str]] = mapped_column(Text)
    signal: Mapped[Optional[str]] = mapped_column(String)  # BUY/SELL/HOLD یا None
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer)
    prompt_version: Mapped[str] = mapped_column(String)
    model: Mapped[Optional[str]] = mapped_column(String)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    problems: Mapped[Optional[list]] = mapped_column(JSON)
    # برچسب‌ها، مرحله ۴ پرشان می‌کند
    price_5m: Mapped[Optional[float]] = mapped_column(Float)
    price_15m: Mapped[Optional[float]] = mapped_column(Float)
    price_30m: Mapped[Optional[float]] = mapped_column(Float)

    
def init_db():
    Base.metadata.create_all(engine)


def ms_to_dt(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)


