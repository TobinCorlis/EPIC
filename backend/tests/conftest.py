import os
from pathlib import Path

TEST_DB = Path(__file__).parent / "test_suite_epic.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

import pytest

from app.core.database import Base, engine


@pytest.fixture(scope="session", autouse=True)
def database_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
