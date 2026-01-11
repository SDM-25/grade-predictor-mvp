"""
Migration runner with schema validation.

Provides:
- Migration tracking via _migrations table
- Auto-apply pending migrations at startup
- Schema validation to catch missing columns BEFORE app runs
- Safe auto-repair for old/legacy databases
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Expected schema definition - single source of truth
# Format: {table_name: [column_names]}
# This prevents "missing column" bugs by validating at startup
EXPECTED_SCHEMA: Dict[str, List[str]] = {
    "users": ["id", "email", "username", "password_hash", "created_at", "last_login_at"],
    "courses": ["id", "user_id", "course_name", "total_marks", "target_marks"],
    "exams": ["id", "user_id", "course_id", "exam_name", "exam_date", "marks", "actual_marks", "is_retake"],
    "topics": ["id", "user_id", "course_id", "topic_name", "weight_points", "notes"],
    "study_sessions": ["id", "topic_id", "session_date", "duration_mins", "quality", "notes"],
    "exercises": ["id", "topic_id", "exercise_date", "total_questions", "correct_answers", "source", "notes"],
    "scheduled_lectures": ["id", "user_id", "course_id", "lecture_date", "lecture_time", "topics_planned", "attended", "notes"],
    "timed_attempts": ["id", "user_id", "course_id", "attempt_date", "source", "minutes", "score_pct", "topics", "notes"],
    "assessments": ["id", "user_id", "course_id", "assessment_name", "assessment_type", "marks", "actual_marks", "progress_pct", "due_date", "is_timed", "notes"],
    "assignment_work": ["id", "user_id", "assessment_id", "work_date", "duration_mins", "work_type", "description", "progress_added"],
    "sessions": ["id", "user_id", "session_id", "created_at", "last_seen_at"],
    "events": ["id", "user_id", "event_name", "event_time", "metadata"],
    "auth_tokens": ["id", "user_id", "token_hash", "created_at", "expires_at", "last_used_at", "user_agent", "revoked_at"],
}

# SQL to create each table if missing (safe CREATE TABLE IF NOT EXISTS)
# Used by repair_schema to handle old databases that never had certain tables
TABLE_CREATE_SQL: Dict[str, Tuple[str, str]] = {
    # (sqlite_sql, postgres_sql)
    "users": (
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE,
            password_hash TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login_at TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE,
            password_hash TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login_at TIMESTAMP
        )"""
    ),
    "courses": (
        """CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            course_name TEXT NOT NULL,
            total_marks INTEGER NOT NULL DEFAULT 120,
            target_marks INTEGER NOT NULL DEFAULT 90,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )""",
        """CREATE TABLE IF NOT EXISTS courses (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            course_name TEXT NOT NULL,
            total_marks INTEGER NOT NULL DEFAULT 120,
            target_marks INTEGER NOT NULL DEFAULT 90
        )"""
    ),
    "exams": (
        """CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            course_id INTEGER NOT NULL,
            exam_name TEXT NOT NULL,
            exam_date DATE NOT NULL,
            marks INTEGER NOT NULL DEFAULT 100,
            actual_marks INTEGER DEFAULT NULL,
            is_retake INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )""",
        """CREATE TABLE IF NOT EXISTS exams (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            exam_name TEXT NOT NULL,
            exam_date DATE NOT NULL,
            marks INTEGER NOT NULL DEFAULT 100,
            actual_marks INTEGER DEFAULT NULL,
            is_retake INTEGER NOT NULL DEFAULT 0
        )"""
    ),
    "topics": (
        """CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            course_id INTEGER NOT NULL,
            topic_name TEXT NOT NULL,
            weight_points REAL NOT NULL DEFAULT 0,
            notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )""",
        """CREATE TABLE IF NOT EXISTS topics (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            topic_name TEXT NOT NULL,
            weight_points REAL NOT NULL DEFAULT 0,
            notes TEXT
        )"""
    ),
    "study_sessions": (
        """CREATE TABLE IF NOT EXISTS study_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            session_date DATE NOT NULL,
            duration_mins INTEGER NOT NULL DEFAULT 30,
            quality INTEGER NOT NULL DEFAULT 3,
            notes TEXT,
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        )""",
        """CREATE TABLE IF NOT EXISTS study_sessions (
            id SERIAL PRIMARY KEY,
            topic_id INTEGER NOT NULL REFERENCES topics(id),
            session_date DATE NOT NULL,
            duration_mins INTEGER NOT NULL DEFAULT 30,
            quality INTEGER NOT NULL DEFAULT 3,
            notes TEXT
        )"""
    ),
    "exercises": (
        """CREATE TABLE IF NOT EXISTS exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            exercise_date DATE NOT NULL,
            total_questions INTEGER NOT NULL,
            correct_answers INTEGER NOT NULL,
            source TEXT,
            notes TEXT,
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        )""",
        """CREATE TABLE IF NOT EXISTS exercises (
            id SERIAL PRIMARY KEY,
            topic_id INTEGER NOT NULL REFERENCES topics(id),
            exercise_date DATE NOT NULL,
            total_questions INTEGER NOT NULL,
            correct_answers INTEGER NOT NULL,
            source TEXT,
            notes TEXT
        )"""
    ),
    "scheduled_lectures": (
        """CREATE TABLE IF NOT EXISTS scheduled_lectures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            course_id INTEGER NOT NULL,
            lecture_date DATE NOT NULL,
            lecture_time TEXT,
            topics_planned TEXT,
            attended INTEGER DEFAULT NULL,
            notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )""",
        """CREATE TABLE IF NOT EXISTS scheduled_lectures (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            lecture_date DATE NOT NULL,
            lecture_time TEXT,
            topics_planned TEXT,
            attended INTEGER DEFAULT NULL,
            notes TEXT
        )"""
    ),
    "timed_attempts": (
        """CREATE TABLE IF NOT EXISTS timed_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            course_id INTEGER NOT NULL,
            attempt_date DATE NOT NULL,
            source TEXT,
            minutes INTEGER NOT NULL,
            score_pct REAL NOT NULL,
            topics TEXT,
            notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )""",
        """CREATE TABLE IF NOT EXISTS timed_attempts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            attempt_date DATE NOT NULL,
            source TEXT,
            minutes INTEGER NOT NULL,
            score_pct REAL NOT NULL,
            topics TEXT,
            notes TEXT
        )"""
    ),
    "assessments": (
        """CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            course_id INTEGER NOT NULL,
            assessment_name TEXT NOT NULL,
            assessment_type TEXT NOT NULL,
            marks INTEGER NOT NULL,
            actual_marks INTEGER DEFAULT NULL,
            progress_pct INTEGER DEFAULT 0,
            due_date DATE,
            is_timed INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )""",
        """CREATE TABLE IF NOT EXISTS assessments (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            assessment_name TEXT NOT NULL,
            assessment_type TEXT NOT NULL,
            marks INTEGER NOT NULL,
            actual_marks INTEGER DEFAULT NULL,
            progress_pct INTEGER DEFAULT 0,
            due_date DATE,
            is_timed INTEGER NOT NULL DEFAULT 1,
            notes TEXT
        )"""
    ),
    "assignment_work": (
        """CREATE TABLE IF NOT EXISTS assignment_work (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            assessment_id INTEGER NOT NULL,
            work_date DATE NOT NULL,
            duration_mins INTEGER NOT NULL DEFAULT 30,
            work_type TEXT NOT NULL DEFAULT 'research',
            description TEXT,
            progress_added INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (assessment_id) REFERENCES assessments(id)
        )""",
        """CREATE TABLE IF NOT EXISTS assignment_work (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            assessment_id INTEGER NOT NULL REFERENCES assessments(id),
            work_date DATE NOT NULL,
            duration_mins INTEGER NOT NULL DEFAULT 30,
            work_type TEXT NOT NULL DEFAULT 'research',
            description TEXT,
            progress_added INTEGER DEFAULT 0
        )"""
    ),
    "sessions": (
        """CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )""",
        """CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            session_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    ),
    "events": (
        """CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_name TEXT NOT NULL,
            event_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )""",
        """CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            event_name TEXT NOT NULL,
            event_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        )"""
    ),
    "auth_tokens": (
        """CREATE TABLE IF NOT EXISTS auth_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            last_used_at TIMESTAMP,
            user_agent TEXT,
            revoked_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )""",
        """CREATE TABLE IF NOT EXISTS auth_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            token_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            last_used_at TIMESTAMP,
            user_agent TEXT,
            revoked_at TIMESTAMP
        )"""
    ),
}


class SchemaError(Exception):
    """Raised when schema validation fails."""
    pass


class MigrationError(Exception):
    """Raised when a migration fails to apply."""
    pass


# ============ MIGRATIONS REGISTRY ============
# Migrations are defined here as (name, sql_sqlite, sql_postgres) tuples
# Each migration runs once and is tracked in _migrations table

MIGRATIONS: List[Tuple[str, str, str]] = [
    # Migration 001: Create migrations tracking table
    (
        "001_create_migrations_table",
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    ),
    # Migration 002: Create users table
    (
        "002_create_users",
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE,
            password_hash TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login_at TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE,
            password_hash TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login_at TIMESTAMP
        );
        """
    ),
    # Migration 003: Create courses table
    (
        "003_create_courses",
        """
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_name TEXT NOT NULL,
            total_marks INTEGER NOT NULL DEFAULT 120,
            target_marks INTEGER NOT NULL DEFAULT 90,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS courses (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            course_name TEXT NOT NULL,
            total_marks INTEGER NOT NULL DEFAULT 120,
            target_marks INTEGER NOT NULL DEFAULT 90
        );
        """
    ),
    # Migration 004: Create exams table
    (
        "004_create_exams",
        """
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            exam_name TEXT NOT NULL,
            exam_date DATE NOT NULL,
            marks INTEGER NOT NULL DEFAULT 100,
            actual_marks INTEGER DEFAULT NULL,
            is_retake INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS exams (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            exam_name TEXT NOT NULL,
            exam_date DATE NOT NULL,
            marks INTEGER NOT NULL DEFAULT 100,
            actual_marks INTEGER DEFAULT NULL,
            is_retake INTEGER NOT NULL DEFAULT 0
        );
        """
    ),
    # Migration 005: Create topics table
    (
        "005_create_topics",
        """
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            topic_name TEXT NOT NULL,
            weight_points REAL NOT NULL DEFAULT 0,
            notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS topics (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            topic_name TEXT NOT NULL,
            weight_points REAL NOT NULL DEFAULT 0,
            notes TEXT
        );
        """
    ),
    # Migration 006: Create study_sessions table
    (
        "006_create_study_sessions",
        """
        CREATE TABLE IF NOT EXISTS study_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            session_date DATE NOT NULL,
            duration_mins INTEGER NOT NULL DEFAULT 30,
            quality INTEGER NOT NULL DEFAULT 3,
            notes TEXT,
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS study_sessions (
            id SERIAL PRIMARY KEY,
            topic_id INTEGER NOT NULL REFERENCES topics(id),
            session_date DATE NOT NULL,
            duration_mins INTEGER NOT NULL DEFAULT 30,
            quality INTEGER NOT NULL DEFAULT 3,
            notes TEXT
        );
        """
    ),
    # Migration 007: Create exercises table
    (
        "007_create_exercises",
        """
        CREATE TABLE IF NOT EXISTS exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            exercise_date DATE NOT NULL,
            total_questions INTEGER NOT NULL,
            correct_answers INTEGER NOT NULL,
            source TEXT,
            notes TEXT,
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS exercises (
            id SERIAL PRIMARY KEY,
            topic_id INTEGER NOT NULL REFERENCES topics(id),
            exercise_date DATE NOT NULL,
            total_questions INTEGER NOT NULL,
            correct_answers INTEGER NOT NULL,
            source TEXT,
            notes TEXT
        );
        """
    ),
    # Migration 008: Create scheduled_lectures table
    (
        "008_create_scheduled_lectures",
        """
        CREATE TABLE IF NOT EXISTS scheduled_lectures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            lecture_date DATE NOT NULL,
            lecture_time TEXT,
            topics_planned TEXT,
            attended INTEGER DEFAULT NULL,
            notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS scheduled_lectures (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            lecture_date DATE NOT NULL,
            lecture_time TEXT,
            topics_planned TEXT,
            attended INTEGER DEFAULT NULL,
            notes TEXT
        );
        """
    ),
    # Migration 009: Create timed_attempts table
    (
        "009_create_timed_attempts",
        """
        CREATE TABLE IF NOT EXISTS timed_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            course_id INTEGER NOT NULL,
            attempt_date DATE NOT NULL,
            source TEXT,
            minutes INTEGER NOT NULL,
            score_pct REAL NOT NULL,
            topics TEXT,
            notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS timed_attempts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            attempt_date DATE NOT NULL,
            source TEXT,
            minutes INTEGER NOT NULL,
            score_pct REAL NOT NULL,
            topics TEXT,
            notes TEXT
        );
        """
    ),
    # Migration 010: Create assessments table
    (
        "010_create_assessments",
        """
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            assessment_name TEXT NOT NULL,
            assessment_type TEXT NOT NULL,
            marks INTEGER NOT NULL,
            actual_marks INTEGER DEFAULT NULL,
            progress_pct INTEGER DEFAULT 0,
            due_date DATE,
            is_timed INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS assessments (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            assessment_name TEXT NOT NULL,
            assessment_type TEXT NOT NULL,
            marks INTEGER NOT NULL,
            actual_marks INTEGER DEFAULT NULL,
            progress_pct INTEGER DEFAULT 0,
            due_date DATE,
            is_timed INTEGER NOT NULL DEFAULT 1,
            notes TEXT
        );
        """
    ),
    # Migration 011: Create assignment_work table
    (
        "011_create_assignment_work",
        """
        CREATE TABLE IF NOT EXISTS assignment_work (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            assessment_id INTEGER NOT NULL,
            work_date DATE NOT NULL,
            duration_mins INTEGER NOT NULL DEFAULT 30,
            work_type TEXT NOT NULL DEFAULT 'research',
            description TEXT,
            progress_added INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (assessment_id) REFERENCES assessments(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS assignment_work (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            assessment_id INTEGER NOT NULL REFERENCES assessments(id),
            work_date DATE NOT NULL,
            duration_mins INTEGER NOT NULL DEFAULT 30,
            work_type TEXT NOT NULL DEFAULT 'research',
            description TEXT,
            progress_added INTEGER DEFAULT 0
        );
        """
    ),
    # Migration 012: Create sessions table
    (
        "012_create_sessions",
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            session_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    ),
    # Migration 013: Create events table
    (
        "013_create_events",
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_name TEXT NOT NULL,
            event_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            event_name TEXT NOT NULL,
            event_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        );
        """
    ),
    # Migration 014: Create auth_tokens table
    (
        "014_create_auth_tokens",
        """
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            last_used_at TIMESTAMP,
            user_agent TEXT,
            revoked_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_auth_tokens_hash ON auth_tokens(token_hash);
        """,
        """
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            token_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            last_used_at TIMESTAMP,
            user_agent TEXT,
            revoked_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_auth_tokens_hash ON auth_tokens(token_hash) WHERE revoked_at IS NULL;
        """
    ),
    # Migration 015: Add missing columns to users table (upgrade path)
    (
        "015_users_add_auth_columns",
        """
        -- SQLite: Add columns if they don't exist (handled by migration check)
        SELECT 1;
        """,
        """
        -- Postgres: Add columns if they don't exist
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='username') THEN
                ALTER TABLE users ADD COLUMN username TEXT UNIQUE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='password_hash') THEN
                ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT '';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='last_login_at') THEN
                ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP;
            END IF;
        END $$;
        """
    ),
    # Migration 016: Add user_id to legacy tables (upgrade path)
    (
        "016_add_user_id_to_legacy_tables",
        """
        -- SQLite: Add user_id if missing (handled via column_exists checks in init_db)
        SELECT 1;
        """,
        """
        -- Postgres: Add user_id to tables if missing
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='courses' AND column_name='user_id') THEN
                ALTER TABLE courses ADD COLUMN user_id INTEGER REFERENCES users(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='exams' AND column_name='user_id') THEN
                ALTER TABLE exams ADD COLUMN user_id INTEGER REFERENCES users(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='topics' AND column_name='user_id') THEN
                ALTER TABLE topics ADD COLUMN user_id INTEGER REFERENCES users(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='scheduled_lectures' AND column_name='user_id') THEN
                ALTER TABLE scheduled_lectures ADD COLUMN user_id INTEGER REFERENCES users(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='timed_attempts' AND column_name='user_id') THEN
                ALTER TABLE timed_attempts ADD COLUMN user_id INTEGER REFERENCES users(id);
            END IF;
        END $$;
        """
    ),
    # Migration 017: Add actual_marks and progress_pct to assessments
    (
        "017_assessments_add_tracking_columns",
        """
        SELECT 1;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='assessments' AND column_name='actual_marks') THEN
                ALTER TABLE assessments ADD COLUMN actual_marks INTEGER DEFAULT NULL;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='assessments' AND column_name='progress_pct') THEN
                ALTER TABLE assessments ADD COLUMN progress_pct INTEGER DEFAULT 0;
            END IF;
        END $$;
        """
    ),
]


def _get_db_connection():
    """Get database connection using db module's get_conn."""
    # Import here to avoid circular imports
    import db
    return db.get_conn()


def _is_postgres():
    """Check if using PostgreSQL."""
    import db
    return db.is_postgres()


def _table_exists(table: str) -> bool:
    """Check if a table exists."""
    import db
    return db.table_exists(table)


def _column_exists(table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    import db
    return db.column_exists(table, column)


def _add_column_if_missing(table: str, column: str, column_def: str) -> bool:
    """
    Add a column to a table if it doesn't exist (SQLite-safe).
    Returns True if column was added, False if it already existed.
    """
    if _column_exists(table, column):
        return False

    if not _table_exists(table):
        return False

    with _get_db_connection() as conn:
        cur = conn.cursor()
        try:
            if _is_postgres():
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")
            else:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")
            conn.commit()
            return True
        except Exception as e:
            # Column might already exist (race condition) or other error
            conn.rollback()
            return False


def _create_table_if_missing(table: str) -> bool:
    """
    Create a table if it doesn't exist using TABLE_CREATE_SQL.
    Returns True if table was created, False if it already existed.
    """
    if _table_exists(table):
        return False

    if table not in TABLE_CREATE_SQL:
        return False

    sqlite_sql, postgres_sql = TABLE_CREATE_SQL[table]
    sql = postgres_sql if _is_postgres() else sqlite_sql

    with _get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(sql)
            conn.commit()
            return True
        except Exception as e:
            print(f"[migrations] Failed to create table {table}: {e}", file=sys.stderr)
            conn.rollback()
            return False


def repair_schema(verbose: bool = False) -> Dict[str, List[str]]:
    """
    Attempt to repair schema by creating missing tables and adding missing columns.
    This is a safety net for old databases or when migrations didn't properly apply.

    Safe operations only:
    - CREATE TABLE IF NOT EXISTS for missing tables
    - ALTER TABLE ADD COLUMN for missing columns

    Returns dict of {table: [columns_added_or_"TABLE_CREATED"]}
    """
    # Column definitions for repair (column_name: sql_type_with_default)
    COLUMN_DEFS = {
        "users": {
            "username": "TEXT",  # Removed UNIQUE constraint for ALTER TABLE compatibility
            "password_hash": "TEXT DEFAULT ''",
            "last_login_at": "TIMESTAMP",
        },
        "courses": {
            "user_id": "INTEGER",
            "total_marks": "INTEGER DEFAULT 120",
            "target_marks": "INTEGER DEFAULT 90",
        },
        "exams": {
            "user_id": "INTEGER",
            "actual_marks": "INTEGER",
            "is_retake": "INTEGER DEFAULT 0",
        },
        "topics": {
            "user_id": "INTEGER",
            "notes": "TEXT",
        },
        "study_sessions": {
            "notes": "TEXT",
        },
        "exercises": {
            "source": "TEXT",
            "notes": "TEXT",
        },
        "scheduled_lectures": {
            "user_id": "INTEGER",
            "notes": "TEXT",
        },
        "timed_attempts": {
            "user_id": "INTEGER",
            "notes": "TEXT",
        },
        "assessments": {
            "user_id": "INTEGER",
            "actual_marks": "INTEGER",
            "progress_pct": "INTEGER DEFAULT 0",
            "notes": "TEXT",
        },
        "assignment_work": {
            "user_id": "INTEGER",
            "description": "TEXT",
        },
        "sessions": {
            "user_id": "INTEGER",
        },
        "events": {
            "user_id": "INTEGER",
            "metadata": "TEXT",
        },
        "auth_tokens": {
            "user_agent": "TEXT",
            "revoked_at": "TIMESTAMP",
        },
    }

    repaired: Dict[str, List[str]] = {}

    # PHASE 1: Create any missing tables
    # Tables must be created in order due to foreign key dependencies
    table_order = [
        "users", "courses", "exams", "topics", "study_sessions", "exercises",
        "scheduled_lectures", "timed_attempts", "assessments", "assignment_work",
        "sessions", "events", "auth_tokens"
    ]

    for table in table_order:
        if table not in EXPECTED_SCHEMA:
            continue
        if not _table_exists(table):
            if verbose:
                print(f"[migrations] Repairing: Creating table {table}", file=sys.stderr)
            if _create_table_if_missing(table):
                repaired[table] = ["TABLE_CREATED"]
                if verbose:
                    print(f"[migrations] Created table: {table}", file=sys.stderr)

    # PHASE 2: Add missing columns to existing tables
    for table, expected_columns in EXPECTED_SCHEMA.items():
        if not _table_exists(table):
            # Table still doesn't exist (creation failed or no SQL defined)
            continue

        added = repaired.get(table, [])
        # Skip column check if we just created the table (it has all columns)
        if "TABLE_CREATED" in added:
            continue

        for col in expected_columns:
            if not _column_exists(table, col):
                # Get column definition
                col_def = COLUMN_DEFS.get(table, {}).get(col)
                if col_def:
                    if verbose:
                        print(f"[migrations] Repairing: Adding {table}.{col}", file=sys.stderr)
                    if _add_column_if_missing(table, col, col_def):
                        added.append(col)

        if added and table not in repaired:
            repaired[table] = added

    return repaired


def _ensure_migrations_table():
    """Create _migrations table if it doesn't exist."""
    with _get_db_connection() as conn:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        conn.commit()


def get_applied_migrations() -> List[str]:
    """Get list of already-applied migration names."""
    _ensure_migrations_table()

    with _get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM _migrations ORDER BY id")
        rows = cur.fetchall()
        return [row[0] for row in rows]


def get_pending_migrations() -> List[Tuple[str, str, str]]:
    """Get list of migrations that haven't been applied yet."""
    applied = set(get_applied_migrations())
    return [m for m in MIGRATIONS if m[0] not in applied]


def _mark_migration_applied(name: str, conn):
    """Record that a migration has been applied."""
    cur = conn.cursor()
    if _is_postgres():
        cur.execute(
            "INSERT INTO _migrations(name) VALUES(%s) ON CONFLICT (name) DO NOTHING",
            (name,)
        )
    else:
        cur.execute(
            "INSERT OR IGNORE INTO _migrations(name) VALUES(?)",
            (name,)
        )


def run_migrations(verbose: bool = True, auto_repair: bool = True) -> List[str]:
    """
    Apply all pending migrations in order.

    Args:
        verbose: Print progress messages
        auto_repair: If True, attempt to add missing columns after migrations

    Returns list of applied migration names.
    """
    _ensure_migrations_table()
    applied = []
    is_pg = _is_postgres()

    for name, sql_sqlite, sql_postgres in get_pending_migrations():
        sql = sql_postgres if is_pg else sql_sqlite

        if verbose:
            print(f"[migrations] Applying: {name}")

        try:
            with _get_db_connection() as conn:
                cur = conn.cursor()
                # Execute migration SQL (may contain multiple statements)
                for stmt in sql.strip().split(';'):
                    stmt = stmt.strip()
                    if stmt and not stmt.startswith('--'):
                        # Skip placeholder statements
                        if stmt.upper() == 'SELECT 1':
                            continue
                        cur.execute(stmt)

                _mark_migration_applied(name, conn)
                conn.commit()
                applied.append(name)

        except Exception as e:
            raise MigrationError(f"Migration {name} failed: {e}")

    if verbose and applied:
        print(f"[migrations] Applied {len(applied)} migration(s)")
    elif verbose:
        print("[migrations] Schema up to date")

    # Auto-repair: Add any missing columns that migrations didn't create
    # This handles SQLite migrations that were placeholder SELECT 1 statements
    if auto_repair:
        repaired = repair_schema(verbose=verbose)
        if repaired and verbose:
            total_cols = sum(len(cols) for cols in repaired.values())
            print(f"[migrations] Auto-repaired {total_cols} missing column(s)")

    return applied


def validate_schema(raise_on_error: bool = True, auto_repair: bool = True) -> Dict[str, List[str]]:
    """
    Validate that all expected tables and columns exist.

    This is the KEY protection against "missing column" bugs.
    Should be called at startup AFTER migrations.

    Args:
        raise_on_error: If True, raises SchemaError on first missing item
        auto_repair: If True, attempt to repair before raising error

    Returns:
        Dict of {table: [missing_columns]} (empty if valid)

    Raises:
        SchemaError: If raise_on_error=True and schema is invalid after repair
    """
    issues: Dict[str, List[str]] = {}

    # Log to stderr so it shows in Streamlit Cloud logs
    print("[migrations] Validating schema...", file=sys.stderr)

    for table, expected_columns in EXPECTED_SCHEMA.items():
        if not _table_exists(table):
            issues[table] = ["TABLE_MISSING"]
            print(f"[migrations] ISSUE: Table '{table}' is missing", file=sys.stderr)
            continue

        missing = []
        for col in expected_columns:
            if not _column_exists(table, col):
                missing.append(col)

        if missing:
            issues[table] = missing
            print(f"[migrations] ISSUE: Table '{table}' missing columns: {missing}", file=sys.stderr)

    # If there are issues and auto_repair is enabled, try to fix them
    if issues and auto_repair:
        print(f"[migrations] Found {len(issues)} schema issue(s), attempting auto-repair...", file=sys.stderr)
        repaired = repair_schema(verbose=True)

        if repaired:
            print(f"[migrations] Auto-repair applied changes: {repaired}", file=sys.stderr)

        # Re-check after repair
        issues_after = {}
        for table, expected_columns in EXPECTED_SCHEMA.items():
            if not _table_exists(table):
                issues_after[table] = ["TABLE_MISSING"]
                continue

            missing = []
            for col in expected_columns:
                if not _column_exists(table, col):
                    missing.append(col)

            if missing:
                issues_after[table] = missing

        # Log what was fixed vs what remains
        if issues_after:
            print(f"[migrations] Issues remaining after repair: {issues_after}", file=sys.stderr)
        else:
            print("[migrations] All schema issues resolved by auto-repair", file=sys.stderr)

        issues = issues_after

    # Raise error if still have issues
    if issues and raise_on_error:
        # Build helpful error message - also log to stderr
        error_parts = ["Schema validation failed after auto-repair attempt:"]
        for table, cols in issues.items():
            if cols == ["TABLE_MISSING"]:
                error_parts.append(f"  - Missing table: {table}")
            else:
                error_parts.append(f"  - Table '{table}' missing columns: {cols}")

        error_parts.append("")
        error_parts.append("To fix manually:")
        error_parts.append("  1. Delete the database file and restart (loses all data)")
        error_parts.append("  2. Or run: python -c 'from migrations.runner import repair_schema; repair_schema(verbose=True)'")

        error_message = "\n".join(error_parts)

        # Log to stderr BEFORE raising so it appears in Streamlit Cloud logs
        print(f"[migrations] FATAL: {error_message}", file=sys.stderr)

        raise SchemaError(error_message)

    if not issues:
        print("[migrations] Schema validation passed", file=sys.stderr)

    return issues


def init_db_with_migrations(validate: bool = True, verbose: bool = False):
    """
    Initialize database with migrations and optional validation.

    This replaces the old init_db() function.

    Args:
        validate: If True, validate schema after migrations
        verbose: If True, print migration progress
    """
    # Run pending migrations
    run_migrations(verbose=verbose)

    # Validate schema to catch issues early
    if validate:
        validate_schema(raise_on_error=True)


# CLI interface for running migrations directly
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "validate":
        print("[migrations] Validating schema...")
        issues = validate_schema(raise_on_error=False)
        if issues:
            print(f"[migrations] Schema issues found: {issues}")
            sys.exit(1)
        else:
            print("[migrations] Schema valid")
    else:
        print("[migrations] Running migrations...")
        applied = run_migrations(verbose=True)
        print(f"[migrations] Done. Applied: {applied}")
