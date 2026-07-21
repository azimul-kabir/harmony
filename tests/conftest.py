import os
from pathlib import Path

import pytest


TEST_DATABASE = Path("/private/tmp/harmony-pytest.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE}"


def pytest_sessionstart(session):
    from app.database.base import Base
    from app.database.database import engine
    from app.database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def isolate_database():
    """Give every test a clean database, including durable queued jobs."""
    from app.database.base import Base
    from app.database.database import engine
    from app.database import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def pytest_sessionfinish(session, exitstatus):
    from app.database.database import engine

    engine.dispose()
    TEST_DATABASE.unlink(missing_ok=True)
