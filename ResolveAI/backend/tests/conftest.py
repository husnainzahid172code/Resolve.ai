import os
import shutil
import tempfile

# Isolate every test session: temp data dir, offline planner, local demo data.
_TMP = tempfile.mkdtemp(prefix="resolveai_test_")
os.environ.update({
    "DATA_DIR": _TMP,
    "LLM_PROVIDER": "offline",
    "DATA_SOURCE": "local_demo",
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "test-pass",
    "AUTH_SECRET": "test-secret",
    "EMAIL_MODE": "demo_outbox",
    "LLM_OVERLOAD_WAIT_SECONDS": "0",
    "COMPARISON_DELAY_SECONDS": "0",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.database.db import init_db  # noqa: E402
from app.services import data_source as ds_mod  # noqa: E402
from app.services.case_service import CaseService, set_case_service  # noqa: E402

init_db()


@pytest.fixture(autouse=True)
def _reset_outage():
    ds = ds_mod.get_data_source()
    ds.simulate_outage = False
    yield
    ds.simulate_outage = False


@pytest.fixture()
def service():
    svc = CaseService()  # real SQLite checkpointer in the temp dir
    set_case_service(svc)
    yield svc
    set_case_service(None)


@pytest.fixture()
def client(service):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "test-pass"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def png_bytes():
    from app.baseline.comparison import sample_png

    return sample_png()


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
