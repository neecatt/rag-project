import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings, reset_settings_cache
from app.db.session import create_database_schema, reset_database_state
from app.main import create_app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    database_path = tmp_path / "test.db"
    uploads_path = tmp_path / "uploads"
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("APP_AUTO_CREATE_TABLES", "true")
    monkeypatch.setenv("APP_UPLOADS_DIR", str(uploads_path))

    reset_settings_cache()
    reset_database_state()

    app = create_app()
    create_database_schema()

    with TestClient(app) as test_client:
        yield test_client

    reset_database_state()
    reset_settings_cache()


@pytest.fixture()
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    database_path = tmp_path / "settings.db"
    uploads_path = tmp_path / "uploads"
    monkeypatch.setenv("APP_NAME", "Backend Test App")
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    monkeypatch.setenv("APP_UPLOADS_DIR", str(uploads_path))
    reset_settings_cache()
    yield get_settings()
    reset_settings_cache()
