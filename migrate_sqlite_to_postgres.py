#!/usr/bin/env python3
"""
One-time migration script to copy data from SQLite to Postgres.

This script:
1. Reads all data from the local SQLite database (grade_predictor.db)
2. Inserts rows into the Postgres database specified in .streamlit/secrets.toml
3. Skips duplicates safely using INSERT ... ON CONFLICT DO NOTHING
4. Prints counts of migrated rows per table

Requirements:
- .streamlit/secrets.toml must be configured with Postgres credentials
- psycopg2-binary must be installed (pip install psycopg2-binary)
- Local SQLite database file must exist at grade_predictor.db

Usage:
    python migrate_sqlite_to_postgres.py
"""

import sqlite3
from pathlib import Path
import sys

# Try to import required modules
try:
    import psycopg2
    from psycopg2.extras import execute_batch
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

try:
    import streamlit as st
except ImportError:
    print("ERROR: streamlit not installed. Run: pip install streamlit")
    sys.exit(1)

# ============ CONFIGURATION ============

SQLITE_PATH = "grade_predictor.db"
TABLES_TO_MIGRATE = [
    "users",
    "courses",
    "topics",
    "exams",
    "study_sessions",
    "exercises",
    "scheduled_lectures",
    "timed_attempts",
    "assessments",
    "assignment_work",
    "sessions",
    "events"
]

# ============ HELPER FUNCTIONS ============

def get_postgres_config():
    """Get Postgres config from Streamlit secrets."""
    try:
        return {
            "host": st.secrets["DB_HOST"],
            "database": st.secrets["DB_NAME"],
            "user": st.secrets["DB_USER"],
            "password": st.secrets["DB_PASSWORD"],
            "port": st.secrets.get("DB_PORT", 5432),
        }
    except (KeyError, FileNotFoundError) as e:
        print(f"ERROR: Missing Postgres configuration in secrets.toml: {e}")
        print("Please configure DB_HOST, DB_NAME, DB_USER, DB_PASSWORD in .streamlit/secrets.toml")
        sys.exit(1)

def connect_sqlite():
    """Connect to local SQLite database."""
    db_path = Path(SQLITE_PATH)
    if not db_path.exists():
        print(f"ERROR: SQLite database not found at {SQLITE_PATH}")
        print("Please ensure the database file exists before running migration.")
        sys.exit(1)

    return sqlite3.connect(SQLITE_PATH)

def connect_postgres():
    """Connect to Postgres database."""
    config = get_postgres_config()
    try:
        conn = psycopg2.connect(**config)
        return conn
    except psycopg2.Error as e:
        print(f"ERROR: Failed to connect to Postgres: {e}")
        print(f"Config: {config['host']}:{config['port']}/{config['database']}")
        sys.exit(1)

def table_exists_sqlite(conn, table_name):
    """Check if table exists in SQLite."""
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cur.fetchone() is not None

def get_table_columns(conn, table_name):
    """Get column names for a table (SQLite)."""
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cur.fetchall()]
    return columns

def migrate_table(sqlite_conn, pg_conn, table_name):
    """
    Migrate data from SQLite table to Postgres table.
    Uses INSERT ... ON CONFLICT DO NOTHING to skip duplicates.
    Returns count of rows inserted.
    """
    # Check if table exists in SQLite
    if not table_exists_sqlite(sqlite_conn, table_name):
        print(f"  ⚠ Table '{table_name}' not found in SQLite, skipping")
        return 0

    # Get all columns from SQLite table
    columns = get_table_columns(sqlite_conn, table_name)
    if not columns:
        print(f"  ⚠ Table '{table_name}' has no columns, skipping")
        return 0

    # Read all data from SQLite
    sqlite_cur = sqlite_conn.cursor()
    sqlite_cur.execute(f"SELECT * FROM {table_name}")
    rows = sqlite_cur.fetchall()

    if not rows:
        print(f"  ℹ Table '{table_name}' is empty, skipping")
        return 0

    # Prepare INSERT statement for Postgres
    # Use ON CONFLICT DO NOTHING to skip duplicates
    columns_str = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))

    # Handle different conflict resolution based on table
    if "id" in columns:
        conflict_clause = "ON CONFLICT (id) DO NOTHING"
    elif table_name == "users" and "email" in columns:
        conflict_clause = "ON CONFLICT (email) DO NOTHING"
    else:
        conflict_clause = "ON CONFLICT DO NOTHING"

    insert_query = f"""
        INSERT INTO {table_name} ({columns_str})
        VALUES ({placeholders})
        {conflict_clause}
    """

    # Insert data in batches
    pg_cur = pg_conn.cursor()
    try:
        execute_batch(pg_cur, insert_query, rows, page_size=100)
        pg_conn.commit()

        # Get count of rows inserted (approximate, since ON CONFLICT skips duplicates)
        inserted = pg_cur.rowcount if pg_cur.rowcount != -1 else len(rows)
        print(f"  ✓ Migrated {inserted}/{len(rows)} rows to '{table_name}'")
        return inserted

    except psycopg2.Error as e:
        pg_conn.rollback()
        print(f"  ✗ ERROR migrating '{table_name}': {e}")
        return 0

def reset_sequences(pg_conn, table_name):
    """
    Reset Postgres sequences for auto-increment columns after migration.
    This ensures new inserts don't conflict with migrated data.
    """
    pg_cur = pg_conn.cursor()
    try:
        # Find the max id in the table
        pg_cur.execute(f"SELECT MAX(id) FROM {table_name}")
        max_id = pg_cur.fetchone()[0]

        if max_id is not None:
            # Reset the sequence to max_id + 1
            sequence_name = f"{table_name}_id_seq"
            pg_cur.execute(f"SELECT setval('{sequence_name}', %s, true)", (max_id,))
            pg_conn.commit()
            print(f"  ✓ Reset sequence '{sequence_name}' to {max_id}")

    except psycopg2.Error as e:
        # Sequence might not exist for this table, ignore
        pg_conn.rollback()

# ============ MAIN MIGRATION ============

def main():
    """Run the migration."""
    print("=" * 60)
    print("SQLite to Postgres Migration")
    print("=" * 60)
    print()

    # Connect to databases
    print("Connecting to databases...")
    sqlite_conn = connect_sqlite()
    pg_conn = connect_postgres()
    print(f"  ✓ Connected to SQLite: {SQLITE_PATH}")
    print(f"  ✓ Connected to Postgres: {st.secrets['DB_HOST']}")
    print()

    # Migrate each table
    print("Migrating tables...")
    print()
    total_migrated = 0

    for table in TABLES_TO_MIGRATE:
        count = migrate_table(sqlite_conn, pg_conn, table)
        total_migrated += count

        # Reset sequence if rows were inserted
        if count > 0 and table not in ["sessions", "events"]:
            reset_sequences(pg_conn, table)

    print()
    print("=" * 60)
    print(f"Migration complete! Total rows migrated: {total_migrated}")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Verify data in Postgres database")
    print("2. Deploy app to Streamlit Cloud with secrets configured")
    print("3. Test the app thoroughly before decommissioning SQLite")
    print()

    # Close connections
    sqlite_conn.close()
    pg_conn.close()

if __name__ == "__main__":
    main()
