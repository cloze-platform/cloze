"""The restricted database user the running app connects as (PostgreSQL only).

Setup and migrations run as the database owner. The app connects as a user
that can read and write rows but can't change the schema, so a SQL injection
bug can't drop or alter tables.
"""

from psycopg2 import sql
from sqlalchemy.engine import make_url


def ensure_app_user(engine, app_database_url):
    """Create or update the login role in app_database_url, and give it row
    access to every table and sequence in the public schema, including ones
    created later by the owner (i.e. by migrations). Run as the owner."""
    url = make_url(app_database_url)
    role = sql.Identifier(url.username)

    conn = engine.raw_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (url.username,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(url.password)))

        cur.execute("SELECT current_database()")
        database = sql.Identifier(cur.fetchone()[0])
        for statement in (
            "GRANT CONNECT ON DATABASE {db} TO {role}",
            "GRANT USAGE ON SCHEMA public TO {role}",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}",
            "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {role}",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {role}",
        ):
            cur.execute(sql.SQL(statement).format(db=database, role=role))
        conn.commit()
    finally:
        conn.close()
