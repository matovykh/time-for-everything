"""The QA destructive-PostgreSQL guard must fail closed before any connection."""

import pytest

from conftest import _check_pg_url

OK = "postgresql://postgres:pw@127.0.0.1:55439/tfe_qa"


@pytest.fixture
def optin(monkeypatch):
    monkeypatch.setenv("QA_ALLOW_DESTRUCTIVE_TEST_DB", "1")
    for k in ("PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
        monkeypatch.delenv(k, raising=False)


def test_accepts_loopback_tfe_qa(optin):
    _check_pg_url(OK)
    _check_pg_url("postgresql://postgres:pw@localhost:5432/tfe_qa_ci")


def test_requires_exact_optin(monkeypatch):
    for v in (None, "true", "yes", "01"):
        if v is None:
            monkeypatch.delenv("QA_ALLOW_DESTRUCTIVE_TEST_DB", raising=False)
        else:
            monkeypatch.setenv("QA_ALLOW_DESTRUCTIVE_TEST_DB", v)
        with pytest.raises(pytest.UsageError):
            _check_pg_url(OK)


@pytest.mark.parametrize("url", [
    "postgresql://postgres:pw@db.abc.supabase.co:5432/tfe_qa",
    "postgresql://postgres:pw@127.0.0.1:5432/postgres",
    "postgresql://postgres:pw@127.0.0.1:5432/tfe_qa_prod-copy",
    "postgresql://postgres:pw@127.0.0.1:5432/tfe_qa?host=db.abc.supabase.co",
    "postgresql://postgres:pw@127.0.0.1:5432/tfe_qa?hostaddr=10.0.0.5",
    "postgresql://postgres:pw@127.0.0.1:5432/tfe_qa?dbname=postgres",
    "postgresql://postgres:pw@127.0.0.1:5432/tfe_qa?service=prod",
    "postgresql://postgres:pw@127.0.0.1:5432/tfe_qa?port=6543",
    "postgresql://postgres:pw@127.0.0.1:5432/tfe_qa?options=-csearch_path%3Dprod",
    "postgresql://postgres:pw@127.0.0.1:5432,db.abc.supabase.co:5432/tfe_qa",
    "mysql://root@127.0.0.1/tfe_qa",
])
def test_rejects_non_disposable_targets(optin, url):
    with pytest.raises(pytest.UsageError):
        _check_pg_url(url)


def test_rejects_libpq_env_overrides(optin, monkeypatch):
    monkeypatch.setenv("PGHOST", "db.abc.supabase.co")
    with pytest.raises(pytest.UsageError):
        _check_pg_url(OK)
