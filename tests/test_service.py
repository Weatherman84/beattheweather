from datetime import date, datetime, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from weatherman.db import Base, Forecast
from weatherman.service import _upsert_batch


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
