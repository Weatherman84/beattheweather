from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from weatherman.db import Base, Forecast, SignalSnapshot
from weatherman.service import _record_signal_snapshots, _upsert_batch


def test_failed_batch_does_not_poison_following_database_work():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    with session_factory() as session:
        bad_rows = [
            {"model": "valid", "temperature": 20.0},
            {"model": "invalid", "temperature": None},
        ]
        stored = _upsert_batch(
            session,
            Forecast,
            bad_rows,
            lambda item: {
                "airport": "LEMD",
                "model": item["model"],
                "run_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
                "target_date": date(2026, 7, 20),
            },
            lambda item: {
                "max_temp_c": item["temperature"],
                "source": "test",
                "horizon": "Live",
            },
            "deliberately invalid batch",
        )
        assert stored == 0

        stored = _upsert_batch(
            session,
            Forecast,
            [{"model": "next", "temperature": 21.0}],
            lambda item: {
                "airport": "LEMD",
                "model": item["model"],
                "run_at": datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
                "target_date": date(2026, 7, 20),
            },
            lambda item: {
                "max_temp_c": item["temperature"],
                "source": "test",
                "horizon": "Live",
            },
            "valid batch",
        )
        session.commit()
        assert stored == 1
        assert session.scalar(select(func.count()).select_from(Forecast)) == 1


def test_collection_journals_model_probability_and_real_ask():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    captured_at = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    target = date(2026, 7, 21)
    with session_factory() as session:
        session.add(
            Forecast(
                airport="LEMD",
                model="ECMWF",
                run_at=captured_at - timedelta(minutes=10),
                target_date=target,
                max_temp_c=35,
                source="open-meteo",
                horizon="Live",
            )
        )
        session.flush()
        stored = _record_signal_snapshots(
            session,
            "LEMD",
            {"timezone": "Europe/Madrid"},
            [
                {
                    "target_date": target,
                    "event_slug": "test-event",
                    "market_id": "market-35",
                    "bucket_label": "35°C",
                    "bucket_low_c": 35,
                    "bucket_high_c": 35,
                    "yes_price": 0.18,
                    "best_ask": 0.20,
                    "closed": False,
                    "yes_won": None,
                    "captured_at": captured_at,
                }
            ],
        )
        session.commit()
        signal = session.scalar(select(SignalSnapshot))
        assert stored == 1
        assert signal is not None
        assert signal.buy_price == 0.20
        assert signal.model_probability > signal.buy_price
        assert signal.signal == "Possible edge"
        assert signal.timing == "D-1 or earlier"
