from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
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
    horizon: Mapped[str] = mapped_column(String(20), default="Live", index=True)


class HourlyForecast(Base):
    __tablename__ = "hourly_forecasts"
    __table_args__ = (UniqueConstraint("airport", "model", "run_at", "valid_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airport: Mapped[str] = mapped_column(String(4), index=True)
    model: Mapped[str] = mapped_column(String(80), index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    temp_c: Mapped[float] = mapped_column(Float)
    dewpoint_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    cloud_cover: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_kph: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    radiation_wm2: Mapped[float | None] = mapped_column(Float, nullable=True)
    temp_850hpa_c: Mapped[float | None] = mapped_column(Float, nullable=True)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("airport", "observed_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airport: Mapped[str] = mapped_column(String(4), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    temp_c: Mapped[float] = mapped_column(Float)
    dewpoint_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_kph: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw: Mapped[str | None] = mapped_column(String(500), nullable=True)


class TafReport(Base):
    __tablename__ = "taf_reports"
    __table_args__ = (UniqueConstraint("airport", "issue_time", "raw_taf"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airport: Mapped[str] = mapped_column(String(4), index=True)
    issue_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    bulletin_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_taf: Mapped[str] = mapped_column(Text)
    is_amended: Mapped[bool] = mapped_column(Boolean, default=False)
    is_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    max_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_temp_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    min_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_temp_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    periods_json: Mapped[str] = mapped_column(Text, default="[]")
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    source: Mapped[str] = mapped_column(String(50), default="aviationweather.gov")


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


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (UniqueConstraint("market_id", "captured_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airport: Mapped[str] = mapped_column(String(4), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    event_slug: Mapped[str] = mapped_column(String(250), index=True)
    market_id: Mapped[str] = mapped_column(String(100), index=True)
    market_slug: Mapped[str] = mapped_column(String(300))
    token_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bucket_label: Mapped[str] = mapped_column(String(80))
    bucket_low_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    bucket_high_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    yes_price: Mapped[float] = mapped_column(Float)
    best_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    yes_won: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resolution_source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class SignalSnapshot(Base):
    __tablename__ = "signal_snapshots"
    __table_args__ = (UniqueConstraint("market_id", "captured_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airport: Mapped[str] = mapped_column(String(4), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    event_slug: Mapped[str] = mapped_column(String(250), index=True)
    market_id: Mapped[str] = mapped_column(String(100), index=True)
    bucket_label: Mapped[str] = mapped_column(String(80))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timing: Mapped[str] = mapped_column(String(30), index=True)
    model_probability: Mapped[float] = mapped_column(Float)
    market_probability: Mapped[float] = mapped_column(Float)
    buy_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal: Mapped[str] = mapped_column(String(30), index=True)
    day_phase: Mapped[str] = mapped_column(String(20))
    model_count: Mapped[int] = mapped_column(Integer)


class ForecastSnapshot(Base):
    """Immutable point forecasts for each step of the forecast ladder."""

    __tablename__ = "forecast_snapshots"
    __table_args__ = (
        UniqueConstraint("airport", "target_date", "captured_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airport: Mapped[str] = mapped_column(String(4), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timing: Mapped[str] = mapped_column(String(30), index=True)
    raw_model_mean_c: Mapped[float] = mapped_column(Float)
    bias_corrected_c: Mapped[float] = mapped_column(Float)
    metar_conditioned_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_forecast_c: Mapped[float] = mapped_column(Float)
    raw_spread_c: Mapped[float] = mapped_column(Float)
    bias_corrected_spread_c: Mapped[float] = mapped_column(Float)
    metar_conditioned_spread_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_spread_c: Mapped[float] = mapped_column(Float)
    observed_max_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_metar_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expected_peak_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hours_to_peak: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_phase: Mapped[str] = mapped_column(String(20), index=True)
    model_count: Mapped[int] = mapped_column(Integer)
    taf_adjustment_c: Mapped[float] = mapped_column(Float, default=0.0)
    taf_conflict: Mapped[bool] = mapped_column(Boolean, default=False)


def engine():
    if settings.database_url.startswith("sqlite:///"):
        path = ROOT / settings.database_url.removeprefix("sqlite:///")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(f"sqlite:///{path}")
    return create_engine(settings.database_url)


ENGINE = engine()
Session = sessionmaker(ENGINE, expire_on_commit=False)


def refresh_database_connections() -> None:
    """Drop pooled handles so a replaced SQLite snapshot is opened afresh.

    Streamlit can keep SQLAlchemy's pooled connection alive after GitHub deploys a
    newer database file. Disposing the pool is safe between requests and avoids an
    app reboot merely to see a newly committed METAR snapshot.
    """
    ENGINE.dispose()


def init_db() -> None:
    Base.metadata.create_all(ENGINE)
    if ENGINE.dialect.name == "sqlite":
        with ENGINE.begin() as connection:
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(forecasts)"))}
            if "horizon" not in columns:
                connection.execute(
                    text("ALTER TABLE forecasts ADD COLUMN horizon VARCHAR(20) DEFAULT 'Legacy'")
                )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_forecasts_horizon ON forecasts (horizon)")
            )
            observation_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(observations)"))
            }
            if "wind_direction" not in observation_columns:
                connection.execute(
                    text("ALTER TABLE observations ADD COLUMN wind_direction FLOAT")
                )
