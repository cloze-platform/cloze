"""The app's restricted database user, against a real PostgreSQL.

Skipped unless CLOZE_TEST_POSTGRES_URL points at a throwaway database whose
owner can create roles, like the RDS master user, e.g.
postgresql://owner:pw@localhost:5432/cloze_test
"""
import os
import uuid

import psycopg2
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from llm_chat.utils.db_roles import ensure_app_user

OWNER_URL = os.environ.get("CLOZE_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not OWNER_URL, reason="CLOZE_TEST_POSTGRES_URL not set")


@pytest.fixture
def owner():
    engine = create_engine(OWNER_URL)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE notes (id SERIAL PRIMARY KEY, body TEXT)")
        conn.exec_driver_sql("CREATE TABLE audit_log (id SERIAL PRIMARY KEY, action TEXT)")
    yield engine
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS notes, later, audit_log")
    engine.dispose()


@pytest.fixture
def app_url(owner):
    name = f"cloze_app_{uuid.uuid4().hex[:8]}"
    yield _url(name, "first-password")
    with owner.begin() as conn:
        # Since PostgreSQL 16, creating a role doesn't make you a member of it.
        conn.exec_driver_sql(f'GRANT "{name}" TO CURRENT_USER')
        conn.exec_driver_sql(f'DROP OWNED BY "{name}"')
        conn.exec_driver_sql(f'DROP ROLE "{name}"')


def _url(username, password):
    return make_url(OWNER_URL).set(username=username, password=password).render_as_string(hide_password=False)


def _run_as(url, *statements):
    conn = psycopg2.connect(url)
    try:
        with conn, conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
            return cur.fetchall() if cur.description else None
    finally:
        conn.close()


def test_app_user_reads_and_writes_rows(owner, app_url):
    ensure_app_user(owner, app_url)

    rows = _run_as(
        app_url,
        "INSERT INTO notes (body) VALUES ('hi')",
        "UPDATE notes SET body = 'hello'",
        "SELECT body FROM notes",
    )
    assert rows == [("hello",)]
    _run_as(app_url, "DELETE FROM notes")


@pytest.mark.parametrize("statement", [
    "CREATE TABLE sneaky (id INT)",
    "ALTER TABLE notes ADD COLUMN extra INT",
    "DROP TABLE notes",
    "TRUNCATE notes",
    "SELECT setval('notes_id_seq', 1000)",
])
def test_app_user_cannot_change_the_schema(owner, app_url, statement):
    ensure_app_user(owner, app_url)

    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        _run_as(app_url, statement)


def test_audit_log_is_insert_only(owner, app_url):
    ensure_app_user(owner, app_url)

    _run_as(app_url, "INSERT INTO audit_log (action) VALUES ('login')")
    assert _run_as(app_url, "SELECT action FROM audit_log") == [("login",)]
    for statement in ("UPDATE audit_log SET action = 'nothing'", "DELETE FROM audit_log"):
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            _run_as(app_url, statement)


def test_rerun_removes_privileges_granted_by_hand(owner, app_url):
    ensure_app_user(owner, app_url)
    with owner.begin() as conn:
        conn.exec_driver_sql(f'GRANT TRUNCATE ON notes TO "{make_url(app_url).username}"')

    ensure_app_user(owner, app_url)

    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        _run_as(app_url, "TRUNCATE notes")


def test_tables_created_later_are_covered(owner, app_url):
    ensure_app_user(owner, app_url)
    with owner.begin() as conn:  # as a migration would
        conn.exec_driver_sql("CREATE TABLE later (id SERIAL PRIMARY KEY, body TEXT)")

    _run_as(app_url, "INSERT INTO later (body) VALUES ('x')")


def test_rerun_updates_the_password(owner, app_url):
    ensure_app_user(owner, app_url)
    new_url = _url(make_url(app_url).username, "second-password")

    ensure_app_user(owner, new_url)

    assert _run_as(new_url, "SELECT 1") == [(1,)]
    with pytest.raises(psycopg2.OperationalError):
        psycopg2.connect(app_url)
