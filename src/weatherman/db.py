from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .settings import ROOT, settings


class Base(DeclarativeBase):
    pass


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (UniqueConstraint("airport", "model", "run_at", "target_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airport: Mapped[str] = mapped_column(String(4), index=True)
    model: Mapped[str] = mapped_column(String(80), index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    max_temp_c: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40), default="forecast")


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("airport", "observed_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airport: Mapped[str] = mapped_column(String(4), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    temp_c: Mapped[float] = mapped_column(Float)
    dewpoint_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_kph: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw: Mapped[str | None] = mapped_column(String(500), nullable=True)


class DailyActual(Base):
    __tablename__ = "daily_actuals"
    __table_args__ = (UniqueConstraint("airport", "target_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airport: Mapped[str] = mapped_column(String(4), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    max_temp_c: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40), default="open-meteo")


class MarketPrice(Base):
    __tablename__ = "market_prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airport: Mapped[str] = mapped_column(String(4), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    bucket_c: Mapped[int] = mapped_column(Integer)
    yes_price: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def engine():
    if settings.database_url.startswith("sqlite:///"):
        path = ROOT / settings.database_url.removeprefix("sqlite:///")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(f"sqlite:///{path}")
    return create_engine(settings.database_url)


ENGINE = engine()
Session = sessionmaker(ENGINE, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(ENGINE)
