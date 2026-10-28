"""Idempotent schema migration script.

Run this AFTER pulling new code but BEFORE starting the app.
It safely adds missing tables and columns without touching existing data.

Usage:
    python migrate_schema.py              # dry-run (shows what would change)
    python migrate_schema.py --apply      # apply changes

Works with both SQLite and PostgreSQL.
"""

import os
import sys
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
project_root = Path(__file__).parent
load_dotenv(project_root / '.env')

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///llm_chat.db')


# ── Column additions to existing tables ──────────────────────────
# Format: (table_name, column_name, column_sql)
COLUMN_ADDITIONS = [
    ('system_prompts', 'domain_prompt_id', 'VARCHAR(50)'),
    ('users', 'created_by', 'INTEGER'),
    ('users', 'failed_login_attempts', 'INTEGER DEFAULT 0'),
    ('users', 'locked_until', 'REAL'),
    ('provider_feature_flags', 'allowed_prompts', 'TEXT'),
    ('chat_windows', 'flow_name', 'VARCHAR(200)'),
    ('chat_windows', 'phase_label', 'VARCHAR(200)'),
    ('provider_feature_flags', 'is_clinical_use', 'BOOLEAN'),
    ('provider_feature_flags', 'monitoring_disclosure', 'TEXT'),
    ('provider_feature_flags', 'persona_override', 'TEXT'),
    # CLOZE-Guard v0
    ('provider_feature_flags', 'guard_enabled', 'BOOLEAN'),
    ('provider_feature_flags', 'guard_keywords', 'TEXT'),
    ('provider_feature_flags', 'guard_notify_email', 'TEXT'),
    ('provider_feature_flags', 'access_hours_enabled', 'BOOLEAN'),
    ('provider_feature_flags', 'access_hours_start', 'VARCHAR(5)'),
    ('provider_feature_flags', 'access_hours_end', 'VARCHAR(5)'),
    ('provider_feature_flags', 'access_hours_timezone', 'VARCHAR(64)'),
    ('provider_feature_flags', 'access_hours_days', 'TEXT'),
    # Report system v2: FK linkage window→flow (legacy rows stay NULL; the
    # scope resolver falls back to flow_name matching for them)
    ('chat_windows', 'flow_id', 'INTEGER'),
    # Enrollment lifecycle: withdrawal is a soft delete so historical data and
    # the report-v2 'enrollment' scope stay resolvable. Existing rows get
    # status NULL, which the model reads as active (see FlowEnrollment).
    ('flow_enrollments', 'status', 'VARCHAR(20)'),
    ('flow_enrollments', 'withdrawn_at', 'REAL'),
    # FK linkage window→phase, for backfilling chats into already-generated
    # windows on always-available flows.
    ('chat_windows', 'phase_id', 'INTEGER'),
]


def get_sqlite_path():
    """Resolve the SQLite file path from DATABASE_URL."""
    if DATABASE_URL.startswith('sqlite:///'):
        db_path = DATABASE_URL.replace('sqlite:///', '')
        if not os.path.isabs(db_path):
            # Relative paths are relative to the instance/ directory
            db_path = os.path.join(project_root, 'instance', db_path)
        return db_path
    return None


def get_connection():
    """Get a database connection."""
    sqlite_path = get_sqlite_path()
    if sqlite_path:
        if not os.path.exists(sqlite_path):
            print(f"ERROR: Database file not found at {sqlite_path}")
            sys.exit(1)
        return sqlite3.connect(sqlite_path), 'sqlite'
    else:
        try:
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL)
            conn.autocommit = False
            return conn, 'postgresql'
        except ImportError:
            print("ERROR: psycopg2 not installed. Install it for PostgreSQL support.")
            sys.exit(1)


def table_exists(cursor, table_name, db_type):
    if db_type == 'sqlite':
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
    else:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=%s",
            (table_name,)
        )
    return cursor.fetchone() is not None


def column_exists(cursor, table_name, column_name, db_type):
    if db_type == 'sqlite':
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        return column_name in columns
    else:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s AND column_name=%s",
            (table_name, column_name)
        )
        return cursor.fetchone() is not None


def run_migration(apply=False):
    conn, db_type = get_connection()
    cursor = conn.cursor()
    changes = []

    print(f"Database: {db_type}")
    if db_type == 'sqlite':
        print(f"Path: {get_sqlite_path()}")
    print()

    # ── Check column additions on existing tables ────────────
    for table_name, col_name, col_type in COLUMN_ADDITIONS:
        if not table_exists(cursor, table_name, db_type):
            print(f"  SKIP  {table_name}.{col_name} — table doesn't exist yet (db.create_all will handle it)")
            continue
        if column_exists(cursor, table_name, col_name, db_type):
            print(f"  OK    {table_name}.{col_name} — already exists")
        else:
            sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"
            changes.append(sql)
            print(f"  ADD   {table_name}.{col_name} ({col_type})")

    # ── Check for new tables (will be created by db.create_all) ──
    new_tables = ['safety_plans', 'audit_log', 'escalation_events', 'provider_feature_flags',
                   'study_flows', 'flow_phases', 'flow_chats', 'flow_enrollments']
    print()
    for t in new_tables:
        if table_exists(cursor, t, db_type):
            print(f"  OK    table '{t}' — already exists")
        else:
            print(f"  NEW   table '{t}' — will be created by --apply")

    # ── Apply or report ──────────────────────────────────────
    print()
    if not changes:
        print("No ALTER TABLE changes needed. All existing tables are up to date.")
        print("New tables (if any) are created by --apply.")
    elif not apply:
        print(f"{len(changes)} change(s) needed. Run with --apply to execute:")
        for sql in changes:
            print(f"  {sql}")
    else:
        print(f"Applying {len(changes)} change(s)...")
        for sql in changes:
            print(f"  Executing: {sql}")
            cursor.execute(sql)
        conn.commit()
        print("Done. All changes applied successfully.")

    cursor.close()
    conn.close()

    # ── Create any missing tables via SQLAlchemy ────────────
    if apply:
        print("\nRunning db.create_all() for any new tables...")
        try:
            from llm_chat import create_app
            from llm_chat.extensions import db
            app = create_app()
            with app.app_context():
                db.create_all()
            print("Done. All tables up to date.")
        except Exception as e:
            sys.exit(f"db.create_all() failed: {e}")


if __name__ == '__main__':
    apply = '--apply' in sys.argv
    if not apply:
        print("=== DRY RUN (pass --apply to execute) ===\n")
    else:
        print("=== APPLYING MIGRATIONS ===\n")
    run_migration(apply=apply)
