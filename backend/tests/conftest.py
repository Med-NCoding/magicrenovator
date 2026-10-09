from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Generator
import pytest
from fastapi.testclient import TestClient

os.environ["APP_ENV"] = "test"
os.environ["GATEWAY_MODE"] = "mock"
os.environ["DATABASE_URL"] = "postgresql://localhost/renopreview_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["ASSET_BUCKET"] = "/Users/medhanshnegi/.gemini/antigravity/scratch/renopreview/.test_private_assets"

from app.dependencies import apply_migrations, get_db_conn, get_redis_client
from app.gateways.mock import MOCK_STATE
from app.main import app
from app.settings import get_settings, reset_settings_cache


@pytest.fixture(autouse=True)
def clean_test_environment() -> Generator[None, None, None]:
    settings = reset_settings_cache()
    asset_dir = Path(settings.ASSET_BUCKET)
    if asset_dir.exists():
        shutil.rmtree(asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)

    apply_migrations(settings)
    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE TABLE
                    outbox,
                    job_events,
                    exports,
                    presentations,
                    credit_ledger,
                    reviews,
                    provider_attempts,
                    generations,
                    quotes,
                    brief_revisions,
                    assets,
                    rooms,
                    projects,
                    credential_references,
                    sessions
                RESTART IDENTITY CASCADE
                """
            )
    r = get_redis_client(settings)
    r.flushdb()
    MOCK_STATE.reset()
    yield


def create_authenticated_client() -> tuple[TestClient, str]:
    client = TestClient(app)
    res = client.post("/api/session")
    assert res.status_code == 200
    csrf = res.json()["csrf_token"]
    client.headers.update({"X-CSRF-Token": csrf})
    return client, csrf
