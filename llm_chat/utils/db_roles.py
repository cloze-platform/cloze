"""The restricted database user the running app connects as (PostgreSQL only).

Setup and migrations run as the database owner. The app connects as a user
that can read and write rows but can't change the schema, so a SQL injection
bug can't drop or alter tables.
"""

from psycopg2 import sql
from psycopg2.extensions import encrypt_password
from sqlalchemy.engine import make_url

# The app only adds to these, so its user can't edit or delete their rows.
APPEND_ONLY_TABLES = ("audit_log",)


def ensure_app_user(engine, app_database_url):
    """Create or update the login role in app_database_url and set its access:
    rows in every public table, including ones the owner creates later (i.e.
    migrations), with APPEND_ONLY_TABLES insert-only. Run as the owner."""
    url = make_url(app_database_url)
    role = sql.Identifier(url.username)

    conn = engine.raw_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (url.username,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        # Hashed client-side so the plaintext never reaches the server or its logs.
        hashed = encrypt_password(url.password, url.username, cur, "scram-sha-256")
        cur.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(hashed)))

        cur.execute("SELECT current_database()")
        database = sql.Identifier(cur.fetchone()[0])
        for statement in (
            # Start from nothing, so a re-run also removes anything granted by hand.
            "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}",
            "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {role}",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {role}",
            "GRANT CONNECT ON DATABASE {db} TO {role}",
            "GRANT USAGE ON SCHEMA public TO {role}",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}",
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}",
        ):
            cur.execute(sql.SQL(statement).format(db=database, role=role))

        for table in APPEND_ONLY_TABLES:
            cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
            if cur.fetchone()[0]:
                cur.execute(sql.SQL("REVOKE UPDATE, DELETE ON {} FROM {}").format(sql.Identifier(table), role))
        conn.commit()
    finally:
        conn.close()
