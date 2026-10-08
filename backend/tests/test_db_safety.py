"""The destructive Postgres test mode must refuse anything but an opted-in local tfe_test DB."""

from __future__ import annotations

import pytest

from tests.db_safety import OPT_IN_ENV, UnsafeTestDatabase, validate_test_database_url

OK_ENV = {OPT_IN_ENV: "1"}


@pytest.mark.parametrize("url", [
    "postgresql://postgres:pw@localhost:5432/tfe_test",
    "postgresql://postgres:pw@127.0.0.1:55432/tfe_test",
    "postgresql://postgres:pw@[::1]:5432/tfe_test_ci",
    "postgresql+psycopg://postgres:pw@127.0.0.1/tfe_test?sslmode=disable",
])
def test_allowed(url):
    validate_test_database_url(url, OK_ENV)


@pytest.mark.parametrize("url", [
    "postgresql://postgres:pw@db.abcdefghijklmnopqrst.supabase.co:5432/tfe_test",
    "postgresql://postgres.abcdefghijklmnopqrst:pw@aws-0-eu.pooler.supabase.com:6543/tfe_test",
    "postgresql://postgres:pw@10.0.0.5:5432/tfe_test",
    "postgresql://postgres:pw@postgres:5432/tfe_test",
    "postgresql://postgres:pw@localhost:5432/postgres",
    "postgresql://postgres:pw@localhost:5432/tfe_testing",
    "postgresql://postgres:pw@localhost:5432/app_tfe_test",
    "postgresql://postgres:pw@localhost:5432/tfe_test?host=db.example.com",
    "postgresql://postgres:pw@localhost:5432/tfe_test?dbname=postgres",
    "postgresql://postgres:pw@localhost,remote:5432/tfe_test",
    "postgresql://localhost/tfe_test?options=-c%20x%3Dsupabase",
    "mysql://root@localhost/tfe_test",
    "postgresql:///tfe_test",
])
def test_refused(url):
    with pytest.raises(UnsafeTestDatabase):
        validate_test_database_url(url, OK_ENV)


@pytest.mark.parametrize("env", [{}, {OPT_IN_ENV: "true"}, {OPT_IN_ENV: "yes"}, {OPT_IN_ENV: "0"}])
def test_opt_in_flag_is_exact(env):
    with pytest.raises(UnsafeTestDatabase, match=OPT_IN_ENV):
        validate_test_database_url("postgresql://postgres:pw@localhost:5432/tfe_test", env)
