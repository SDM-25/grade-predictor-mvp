"""
Database module with Postgres (Supabase) support and SQLite fallback.
Includes authentication helpers with bcrypt password hashing.

Supports database configuration via:
1. DATABASE_URL environment variable (recommended for prod)
   - postgresql://user:pass@host:port/dbname
   - sqlite:///path/to/file.db  (or sqlite:///./relative.db)
2. Streamlit secrets (DB_HOST, DB_NAME, etc.) - legacy support
3. Default SQLite file (grade_predictor.db) - local development

Usage:
    from db import get_conn, execute, read_sql, init_db, is_postgres

    # Initialize with migrations and schema validation
    init_db()  # Runs migrations, validates schema
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
from urllib.parse import urlparse, parse_qs
import pandas as pd

# Try to import bcrypt for password hashing
try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

# Try to import Streamlit secrets and psycopg2
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

# ============ CONNECTION CONFIG ============

# Database file lives in the same directory as this module
APP_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = str(APP_DIR / "grade_predictor.db")

# Cache for parsed DATABASE_URL
_db_config_cache: Optional[Dict] = None


def _parse_database_url(url: str) -> Optional[Dict]:
    """
    Parse DATABASE_URL into connection config.

    Supports:
    - postgresql://user:pass@host:port/dbname
    - postgres://user:pass@host:port/dbname (alias)
    - sqlite:///path/to/file.db
    - sqlite:///./relative/path.db

    Returns dict with 'type' ('postgres' or 'sqlite') and connection params.
    """
    if not url:
        return None

    parsed = urlparse(url)

    # PostgreSQL
    if parsed.scheme in ('postgresql', 'postgres'):
        if not HAS_PSYCOPG2:
            return None
        return {
            'type': 'postgres',
            'host': parsed.hostname or 'localhost',
            'port': parsed.port or 5432,
            'database': parsed.path.lstrip('/') or 'postgres',
            'user': parsed.username or 'postgres',
            'password': parsed.password or '',
        }

    # SQLite
    elif parsed.scheme == 'sqlite':
        # sqlite:///path means absolute /path
        # sqlite:///./path means relative ./path
        path = parsed.path

        # On Windows, urlparse puts the path in netloc for sqlite:///./file.db
        if not path and parsed.netloc:
            path = parsed.netloc + parsed.path

        # Remove leading slashes (sqlite:/// -> ///)
        while path.startswith('/'):
            path = path[1:]

        # Handle ./ and ../ relative paths
        if path.startswith('./') or path.startswith('.\\'):
            path = path[2:]
        elif path.startswith('../') or path.startswith('..\\'):
            pass  # Keep relative path for resolution

        # Resolve relative paths from APP_DIR
        if not os.path.isabs(path):
            path = str(APP_DIR / path)

        return {
            'type': 'sqlite',
            'path': path,
        }

    return None


def _get_db_config() -> Dict:
    """
    Get database configuration from environment or secrets.

    Priority:
    1. DATABASE_URL environment variable
    2. Streamlit secrets (DB_HOST, etc.)
    3. Default SQLite file

    Returns dict with 'type' and connection params.
    """
    global _db_config_cache

    # Check cache first (config doesn't change during runtime)
    if _db_config_cache is not None:
        return _db_config_cache

    # Priority 1: DATABASE_URL environment variable
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        config = _parse_database_url(database_url)
        if config:
            _db_config_cache = config
            return config

    # Priority 2: Streamlit secrets (legacy support)
    if HAS_STREAMLIT and HAS_PSYCOPG2:
        try:
            config = {
                'type': 'postgres',
                'host': st.secrets["DB_HOST"],
                'database': st.secrets["DB_NAME"],
                'user': st.secrets["DB_USER"],
                'password': st.secrets["DB_PASSWORD"],
                'port': st.secrets.get("DB_PORT", 5432),
            }
            _db_config_cache = config
            return config
        except (KeyError, FileNotFoundError):
            pass

    # Priority 3: Default SQLite
    _db_config_cache = {
        'type': 'sqlite',
        'path': DEFAULT_SQLITE_PATH,
    }
    return _db_config_cache


def get_database_url() -> str:
    """
    Get the current database URL (for display/debugging).
    Masks password in postgres URLs.
    """
    config = _get_db_config()
    if config['type'] == 'postgres':
        return f"postgresql://{config['user']}:***@{config['host']}:{config['port']}/{config['database']}"
    else:
        return f"sqlite:///{config['path']}"


# Keep SQLITE_PATH for backward compatibility (used by migrate_sqlite_to_postgres.py)
SQLITE_PATH = DEFAULT_SQLITE_PATH


def _get_postgres_config():
    """Get Postgres config from current config. Legacy compatibility."""
    config = _get_db_config()
    if config['type'] != 'postgres':
        return None
    return {
        'host': config['host'],
        'database': config['database'],
        'user': config['user'],
        'password': config['password'],
        'port': config['port'],
    }


def is_postgres() -> bool:
    """Check if we're using Postgres."""
    return _get_db_config()['type'] == 'postgres'

# ============ CONNECTION HELPERS ============

@contextmanager
def get_conn():
    """
    Get a database connection (Postgres or SQLite).
    Use as context manager: with get_conn() as conn: ...
    """
    config = _get_db_config()
    if config['type'] == 'postgres':
        conn = psycopg2.connect(
            host=config['host'],
            port=config['port'],
            database=config['database'],
            user=config['user'],
            password=config['password'],
        )
        try:
            yield conn
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(config['path'], check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            conn.close()


def get_conn_raw():
    """
    Get a raw connection (not context manager).
    Caller must close the connection.
    """
    config = _get_db_config()
    if config['type'] == 'postgres':
        return psycopg2.connect(
            host=config['host'],
            port=config['port'],
            database=config['database'],
            user=config['user'],
            password=config['password'],
        )
    else:
        conn = sqlite3.connect(config['path'], check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

# ============ QUERY HELPERS ============

def execute(query: str, params: tuple = None, commit: bool = True):
    """
    Execute a query with optional parameters.
    Returns the cursor (useful for lastrowid).
    """
    with get_conn() as conn:
        cur = conn.cursor()
        if params:
            # Convert SQLite ? placeholders to Postgres %s if needed
            if is_postgres():
                query = query.replace("?", "%s")
            cur.execute(query, params)
        else:
            cur.execute(query)
        if commit:
            conn.commit()
        return cur

def execute_returning(query: str, params: tuple = None) -> int:
    """
    Execute an INSERT query and return the inserted ID.
    Handles both SQLite (lastrowid) and Postgres (RETURNING id).
    """
    with get_conn() as conn:
        cur = conn.cursor()
        if is_postgres():
            # Add RETURNING id if not present
            query = query.replace("?", "%s")
            if "RETURNING" not in query.upper():
                query = query.rstrip(";").rstrip(")") + ") RETURNING id"
            cur.execute(query, params)
            result = cur.fetchone()
            conn.commit()
            return result[0] if result else None
        else:
            cur.execute(query, params)
            conn.commit()
            return cur.lastrowid

def read_sql(query: str, params: tuple = None) -> pd.DataFrame:
    """
    Execute a SELECT query and return a pandas DataFrame.
    """
    if is_postgres():
        query = query.replace("?", "%s")
    
    conn = get_conn_raw()
    try:
        df = pd.read_sql_query(query, conn, params=params)
        return df
    finally:
        conn.close()

def fetchone(query: str, params: tuple = None):
    """
    Execute a query and return one row.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        if is_postgres():
            query = query.replace("?", "%s")
        cur.execute(query, params if params else ())
        return cur.fetchone()

def fetchall(query: str, params: tuple = None):
    """
    Execute a query and return all rows.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        if is_postgres():
            query = query.replace("?", "%s")
        cur.execute(query, params if params else ())
        return cur.fetchall()

# ============ SCHEMA HELPERS ============

def table_exists(table: str) -> bool:
    """Check if a table exists."""
    if is_postgres():
        row = fetchone(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
            (table,)
        )
        return row[0] if row else False
    else:
        row = fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        return row is not None

def column_exists(table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    if is_postgres():
        row = fetchone(
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = %s AND column_name = %s
            )""",
            (table, column)
        )
        return row[0] if row else False
    else:
        from security import validate_table_name
        # Validate table name to prevent SQL injection in PRAGMA
        try:
            validated_table = validate_table_name(table)
        except ValueError:
            return False
        with get_conn() as conn:
            cur = conn.execute(f"PRAGMA table_info({validated_table})")
            columns = [r[1] for r in cur.fetchall()]
            return column in columns

# ============ INIT DB ============

def init_db(validate: bool = True, verbose: bool = False):
    """
    Initialize database schema using migrations system.

    This function:
    1. Runs all pending migrations in order (with auto-repair for SQLite)
    2. Validates schema matches expected structure (prevents missing column bugs)
    3. Auto-repairs missing columns before failing

    Args:
        validate: If True (default), validate schema after migrations.
                  Raises SchemaError if any expected table/column is missing.
        verbose: If True, print migration progress.

    Raises:
        SchemaError: If validate=True and schema is invalid after repair attempts.

    Usage:
        # Standard initialization (recommended)
        init_db()

        # Skip validation (for testing)
        init_db(validate=False)

        # Verbose mode for debugging
        init_db(verbose=True)
    """
    from migrations import run_migrations, validate_schema, repair_schema, SchemaError

    try:
        # Run all pending migrations (includes auto-repair)
        applied = run_migrations(verbose=verbose, auto_repair=True)

        # Validate schema to catch missing columns BEFORE app runs
        # validate_schema also attempts auto-repair before failing
        if validate:
            validate_schema(raise_on_error=True, auto_repair=True)

        if verbose:
            print(f"[db] Initialized. Using: {get_database_url()}")

    except SchemaError as e:
        # Log the full error for debugging
        import sys
        print(f"[db] FATAL: Schema error during init_db()", file=sys.stderr)
        print(f"[db] Database: {get_database_url()}", file=sys.stderr)
        print(f"[db] Error: {e}", file=sys.stderr)
        raise  # Re-raise the original error with its helpful message

    except Exception as e:
        # Unexpected error - wrap with context
        import sys
        print(f"[db] FATAL: Unexpected error during init_db(): {e}", file=sys.stderr)
        raise


def init_db_legacy():
    """
    Legacy init_db implementation (inline schema creation).
    DEPRECATED: Use init_db() which uses the migrations system.

    This function is kept for backward compatibility but will be removed
    in a future version. It handles schema creation without migrations tracking.
    """
    with get_conn() as conn:
        cur = conn.cursor()

        if is_postgres():
            # Users table
            if not table_exists("users"):
                cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    username TEXT UNIQUE,
                    password_hash TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login_at TIMESTAMP
                );
                """)
            else:
                if not column_exists("users", "username"):
                    cur.execute("ALTER TABLE users ADD COLUMN username TEXT UNIQUE")
                if not column_exists("users", "password_hash"):
                    cur.execute("ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")
                if not column_exists("users", "last_login_at"):
                    cur.execute("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP")

            # Courses table
            if not table_exists("courses"):
                cur.execute("""
                CREATE TABLE IF NOT EXISTS courses (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    course_name TEXT NOT NULL,
                    total_marks INTEGER NOT NULL DEFAULT 120,
                    target_marks INTEGER NOT NULL DEFAULT 90
                );
                """)
            elif not column_exists("courses", "user_id"):
                cur.execute("ALTER TABLE courses ADD COLUMN user_id INTEGER REFERENCES users(id)")

            # Core tables (idempotent)
            cur.execute("""CREATE TABLE IF NOT EXISTS exams (
                id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                course_id INTEGER NOT NULL REFERENCES courses(id), exam_name TEXT NOT NULL,
                exam_date DATE NOT NULL, marks INTEGER DEFAULT 100, actual_marks INTEGER,
                is_retake INTEGER DEFAULT 0);""")
            cur.execute("""CREATE TABLE IF NOT EXISTS topics (
                id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                course_id INTEGER NOT NULL REFERENCES courses(id), topic_name TEXT NOT NULL,
                weight_points REAL DEFAULT 0, notes TEXT);""")
            cur.execute("""CREATE TABLE IF NOT EXISTS study_sessions (
                id SERIAL PRIMARY KEY, topic_id INTEGER NOT NULL REFERENCES topics(id),
                session_date DATE NOT NULL, duration_mins INTEGER DEFAULT 30,
                quality INTEGER DEFAULT 3, notes TEXT);""")
            cur.execute("""CREATE TABLE IF NOT EXISTS exercises (
                id SERIAL PRIMARY KEY, topic_id INTEGER NOT NULL REFERENCES topics(id),
                exercise_date DATE NOT NULL, total_questions INTEGER NOT NULL,
                correct_answers INTEGER NOT NULL, source TEXT, notes TEXT);""")
            cur.execute("""CREATE TABLE IF NOT EXISTS scheduled_lectures (
                id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                course_id INTEGER NOT NULL REFERENCES courses(id), lecture_date DATE NOT NULL,
                lecture_time TEXT, topics_planned TEXT, attended INTEGER, notes TEXT);""")
            cur.execute("""CREATE TABLE IF NOT EXISTS timed_attempts (
                id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                course_id INTEGER NOT NULL REFERENCES courses(id), attempt_date DATE NOT NULL,
                source TEXT, minutes INTEGER NOT NULL, score_pct REAL NOT NULL,
                topics TEXT, notes TEXT);""")
            cur.execute("""CREATE TABLE IF NOT EXISTS assessments (
                id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                course_id INTEGER NOT NULL REFERENCES courses(id), assessment_name TEXT NOT NULL,
                assessment_type TEXT NOT NULL, marks INTEGER NOT NULL, actual_marks INTEGER,
                progress_pct INTEGER DEFAULT 0, due_date DATE, is_timed INTEGER DEFAULT 1, notes TEXT);""")
            cur.execute("""CREATE TABLE IF NOT EXISTS assignment_work (
                id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                assessment_id INTEGER NOT NULL REFERENCES assessments(id), work_date DATE NOT NULL,
                duration_mins INTEGER DEFAULT 30, work_type TEXT DEFAULT 'research',
                description TEXT, progress_added INTEGER DEFAULT 0);""")
            cur.execute("""CREATE TABLE IF NOT EXISTS sessions (
                id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                session_id TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);""")
            cur.execute("""CREATE TABLE IF NOT EXISTS events (
                id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                event_name TEXT NOT NULL, event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT);""")
            cur.execute("""CREATE TABLE IF NOT EXISTS auth_tokens (
                id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                token_hash TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL, last_used_at TIMESTAMP,
                user_agent TEXT, revoked_at TIMESTAMP);""")
            cur.execute("""CREATE INDEX IF NOT EXISTS idx_auth_tokens_hash
                ON auth_tokens(token_hash) WHERE revoked_at IS NULL;""")

        else:
            # SQLite schema (simplified)
            if not table_exists("users"):
                cur.execute("""CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
                    username TEXT UNIQUE, password_hash TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_login_at TIMESTAMP);""")
            else:
                if not column_exists("users", "username"):
                    cur.execute("ALTER TABLE users ADD COLUMN username TEXT")
                if not column_exists("users", "password_hash"):
                    cur.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")
                if not column_exists("users", "last_login_at"):
                    cur.execute("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP")

            # Core tables
            cur.execute("""CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                course_name TEXT NOT NULL, total_marks INTEGER DEFAULT 120,
                target_marks INTEGER DEFAULT 90, FOREIGN KEY (user_id) REFERENCES users(id));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                course_id INTEGER NOT NULL, exam_name TEXT NOT NULL, exam_date DATE NOT NULL,
                marks INTEGER DEFAULT 100, actual_marks INTEGER, is_retake INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id), FOREIGN KEY (course_id) REFERENCES courses(id));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                course_id INTEGER NOT NULL, topic_name TEXT NOT NULL,
                weight_points REAL DEFAULT 0, notes TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id), FOREIGN KEY (course_id) REFERENCES courses(id));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, topic_id INTEGER NOT NULL,
                session_date DATE NOT NULL, duration_mins INTEGER DEFAULT 30,
                quality INTEGER DEFAULT 3, notes TEXT, FOREIGN KEY (topic_id) REFERENCES topics(id));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT, topic_id INTEGER NOT NULL,
                exercise_date DATE NOT NULL, total_questions INTEGER NOT NULL,
                correct_answers INTEGER NOT NULL, source TEXT, notes TEXT,
                FOREIGN KEY (topic_id) REFERENCES topics(id));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS scheduled_lectures (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                course_id INTEGER NOT NULL, lecture_date DATE NOT NULL,
                lecture_time TEXT, topics_planned TEXT, attended INTEGER, notes TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id), FOREIGN KEY (course_id) REFERENCES courses(id));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS timed_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                course_id INTEGER NOT NULL, attempt_date DATE NOT NULL,
                source TEXT, minutes INTEGER NOT NULL, score_pct REAL NOT NULL,
                topics TEXT, notes TEXT, FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (course_id) REFERENCES courses(id));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                course_id INTEGER NOT NULL, assessment_name TEXT NOT NULL,
                assessment_type TEXT NOT NULL, marks INTEGER NOT NULL, actual_marks INTEGER,
                progress_pct INTEGER DEFAULT 0, due_date DATE, is_timed INTEGER DEFAULT 1, notes TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id), FOREIGN KEY (course_id) REFERENCES courses(id));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS assignment_work (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                assessment_id INTEGER NOT NULL, work_date DATE NOT NULL,
                duration_mins INTEGER DEFAULT 30, work_type TEXT DEFAULT 'research',
                description TEXT, progress_added INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id), FOREIGN KEY (assessment_id) REFERENCES assessments(id));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                session_id TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                event_name TEXT NOT NULL, event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT, FOREIGN KEY (user_id) REFERENCES users(id));""")
            cur.execute("""CREATE TABLE IF NOT EXISTS auth_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL, last_used_at TIMESTAMP,
                user_agent TEXT, revoked_at TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id));""")
            cur.execute("""CREATE INDEX IF NOT EXISTS idx_auth_tokens_hash ON auth_tokens(token_hash);""")

        conn.commit()

# ============ PASSWORD HELPERS (bcrypt) ============

def hash_password(plain: str) -> str:
    """Hash a password using bcrypt. Returns the hash as a string."""
    if not HAS_BCRYPT:
        raise ImportError("bcrypt is required for password hashing. Install with: pip install bcrypt")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against a bcrypt hash. Returns True if match."""
    if not HAS_BCRYPT:
        return False
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

# ============ AUTH TOKEN HELPERS (persistent login) ============

def generate_token() -> str:
    """Generate a secure random token for persistent login."""
    import secrets
    return secrets.token_urlsafe(32)

def hash_token(raw_token: str) -> str:
    """Hash a token using SHA-256. Returns hex digest."""
    import hashlib
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

def store_token(user_id: int, raw_token: str, expires_at: datetime, user_agent: str = None) -> int:
    """
    Store an auth token (hashed) in the database.
    Returns the token ID.
    """
    token_hash = hash_token(raw_token)
    token_id = execute_returning(
        """INSERT INTO auth_tokens(user_id, token_hash, expires_at, user_agent)
           VALUES(?,?,?,?)""",
        (user_id, token_hash, expires_at.isoformat(), user_agent)
    )
    return token_id

def validate_token(raw_token: str) -> dict:
    """
    Validate an auth token and return user info if valid.
    Returns dict with user_id, email, or None if invalid/expired/revoked.
    Also updates last_used_at timestamp if valid.
    """
    if not raw_token:
        return None

    token_hash = hash_token(raw_token)
    now = datetime.now().isoformat()

    # Find token and check if valid (not revoked, not expired)
    row = fetchone(
        """SELECT at.id, at.user_id, at.expires_at, u.email
           FROM auth_tokens at
           JOIN users u ON at.user_id = u.id
           WHERE at.token_hash = ?
             AND at.revoked_at IS NULL
             AND at.expires_at > ?""",
        (token_hash, now)
    )

    if not row:
        return None

    token_id = row[0]
    user_id = row[1]
    email = row[3]

    # Update last_used_at
    execute(
        "UPDATE auth_tokens SET last_used_at = ? WHERE id = ?",
        (now, token_id)
    )

    return {
        "user_id": user_id,
        "email": email,
        "token_id": token_id
    }

def revoke_token(raw_token: str) -> bool:
    """
    Revoke an auth token (soft delete by setting revoked_at).
    Returns True if token was found and revoked, False otherwise.
    """
    if not raw_token:
        return False

    token_hash = hash_token(raw_token)
    now = datetime.now().isoformat()

    # Mark as revoked
    execute(
        "UPDATE auth_tokens SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
        (now, token_hash)
    )

    # Check if any rows were affected
    row = fetchone("SELECT changes()" if not is_postgres() else "SELECT 1")
    return (row[0] if row else 0) > 0

def revoke_all_user_tokens(user_id: int) -> int:
    """
    Revoke all auth tokens for a user.
    Returns count of tokens revoked.
    """
    now = datetime.now().isoformat()

    execute(
        "UPDATE auth_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (now, user_id)
    )

    # Get count of revoked tokens
    if is_postgres():
        # Postgres doesn't have changes(), use a count query
        row = fetchone(
            "SELECT COUNT(*) FROM auth_tokens WHERE user_id = ? AND revoked_at = ?",
            (user_id, now)
        )
    else:
        row = fetchone("SELECT changes()")

    return row[0] if row else 0

def cleanup_expired_tokens(days_old: int = 90) -> int:
    """
    Delete expired and old revoked tokens from the database.
    Returns count of tokens deleted.
    """
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days_old)).isoformat()

    # Delete tokens that are either expired or revoked and old
    execute(
        """DELETE FROM auth_tokens
           WHERE expires_at < ? OR (revoked_at IS NOT NULL AND revoked_at < ?)""",
        (cutoff, cutoff)
    )

    # Get count of deleted tokens
    if is_postgres():
        # Can't get deleted count easily in Postgres, return 0
        return 0
    else:
        row = fetchone("SELECT changes()")
        return row[0] if row else 0

# ============ USER HELPERS ============

def get_or_create_user(email: str) -> int:
    """Get existing user by email or create new one (legacy, no password)."""
    email = email.lower().strip()
    row = fetchone("SELECT id FROM users WHERE email=?", (email,))
    if row:
        return row[0]
    else:
        # Provide empty password_hash for backward compatibility
        # Users created this way should set a password later
        return execute_returning("INSERT INTO users(email, password_hash) VALUES(?,?)", (email, ""))

def create_user(email: str, username: str, plain_password: str) -> int:
    """
    Create a new user with email, optional username, and hashed password.
    Returns the new user's ID.
    Raises ValueError if email or username already exists.
    """
    email = email.lower().strip()
    
    # Check if email already exists
    existing = fetchone("SELECT id FROM users WHERE email=?", (email,))
    if existing:
        raise ValueError("Email already registered.")
    
    # Check if username already exists (if provided)
    if username:
        username = username.strip()
        existing_username = fetchone("SELECT id FROM users WHERE username=?", (username,))
        if existing_username:
            raise ValueError("Username already taken.")
    
    # Hash password and create user
    password_hash = hash_password(plain_password)
    user_id = execute_returning(
        "INSERT INTO users(email, username, password_hash) VALUES(?,?,?)",
        (email, username if username else None, password_hash)
    )
    return user_id

def get_user_by_email(email: str) -> dict:
    """
    Get user by email. Returns dict with user info or None if not found.
    """
    email = email.lower().strip()
    row = fetchone(
        "SELECT id, email, username, password_hash, created_at, last_login_at FROM users WHERE email=?",
        (email,)
    )
    if row:
        return {
            "id": row[0],
            "email": row[1],
            "username": row[2],
            "password_hash": row[3],
            "created_at": row[4],
            "last_login_at": row[5]
        }
    return None

def update_last_login(user_id: int) -> None:
    """Update the last_login_at timestamp for a user."""
    now = datetime.now().isoformat()
    execute("UPDATE users SET last_login_at=? WHERE id=?", (now, user_id))

# ============ SESSION TRACKING ============

def upsert_session(user_id: int, session_id: str) -> None:
    """
    Create or update a session record.
    Updates last_seen_at on each app refresh.
    """
    now = datetime.now().isoformat()
    
    # Check if session exists
    existing = fetchone(
        "SELECT id FROM sessions WHERE user_id=? AND session_id=?",
        (user_id, session_id)
    )
    
    if existing:
        # Update last_seen_at
        execute(
            "UPDATE sessions SET last_seen_at=? WHERE user_id=? AND session_id=?",
            (now, user_id, session_id)
        )
    else:
        # Create new session
        execute_returning(
            "INSERT INTO sessions(user_id, session_id, last_seen_at) VALUES(?,?,?)",
            (user_id, session_id, now)
        )

def end_session(user_id: int, session_id: str) -> None:
    """Delete a session record (on logout)."""
    execute("DELETE FROM sessions WHERE user_id=? AND session_id=?", (user_id, session_id))

def get_live_users_count(minutes: int = 10) -> int:
    """
    Get count of distinct users active in the last N minutes.
    'Live' is defined as last_seen_at within the specified minutes.
    """
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    row = fetchone(
        "SELECT COUNT(DISTINCT user_id) FROM sessions WHERE last_seen_at >= ?",
        (cutoff,)
    )
    return row[0] if row else 0

def cleanup_old_sessions(hours: int = 24) -> int:
    """
    Delete sessions older than the specified hours.
    Returns count of deleted sessions.
    """
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    execute("DELETE FROM sessions WHERE last_seen_at < ?", (cutoff,))
    row = fetchone("SELECT changes()")
    return row[0] if row else 0

# ============ EVENT LOGGING ============

def log_event(user_id: int, event_name: str, metadata: str = None) -> None:
    """Log an event for analytics."""
    execute_returning(
        "INSERT INTO events(user_id, event_name, metadata) VALUES(?,?,?)",
        (user_id, event_name, metadata)
    )

def get_event_count(event_name: str, days: int = None) -> int:
    """Get count of events, optionally filtered by days."""
    from datetime import timedelta
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        row = fetchone(
            "SELECT COUNT(*) FROM events WHERE event_name=? AND event_time >= ?",
            (event_name, cutoff)
        )
    else:
        row = fetchone("SELECT COUNT(*) FROM events WHERE event_name=?", (event_name,))
    return row[0] if row else 0

def get_unique_users_for_event(event_name: str, days: int = None) -> int:
    """Get count of unique users who triggered an event."""
    from datetime import timedelta
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        row = fetchone(
            "SELECT COUNT(DISTINCT user_id) FROM events WHERE event_name=? AND event_time >= ?",
            (event_name, cutoff)
        )
    else:
        row = fetchone("SELECT COUNT(DISTINCT user_id) FROM events WHERE event_name=?", (event_name,))
    return row[0] if row else 0

# ============ ADMIN HELPERS ============

def verify_admin(username: str, password: str) -> bool:
    """Verify admin credentials against Streamlit secrets.

    Supports two authentication modes:
    1. ADMIN_USERNAME + ADMIN_PASSWORD_HASH (bcrypt hash, recommended)
    2. ADMIN_USERNAME + ADMIN_PASSWORD (plaintext, for dev/testing)
    """
    if not HAS_STREAMLIT:
        return False
    try:
        admin_username = st.secrets.get("ADMIN_USERNAME", None)
        admin_password_hash = st.secrets.get("ADMIN_PASSWORD_HASH", None)
        admin_password_plain = st.secrets.get("ADMIN_PASSWORD", None)

        # Must have username configured
        if not admin_username:
            return False

        # Strip whitespace from entered values and secret values
        username = username.strip() if username else ""
        password = password.strip() if password else ""
        admin_username = admin_username.strip() if admin_username else ""

        # Check username match
        if username != admin_username:
            return False

        # Mode A: bcrypt hash (preferred, more secure)
        if admin_password_hash:
            # Note: bcrypt hash comparison doesn't need strip as hash won't have whitespace
            return verify_password(password, admin_password_hash)

        # Mode B: plaintext password (fallback for dev/testing)
        elif admin_password_plain:
            admin_password_plain = admin_password_plain.strip() if admin_password_plain else ""
            return password == admin_password_plain

        # No password configured
        else:
            return False

    except (KeyError, FileNotFoundError):
        return False

def get_total_users() -> int:
    """Get total number of registered users."""
    row = fetchone("SELECT COUNT(*) FROM users")
    return row[0] if row else 0

def get_users_created_since(days: int) -> int:
    """Get count of users created in the last N days."""
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    row = fetchone("SELECT COUNT(*) FROM users WHERE created_at >= ?", (cutoff,))
    return row[0] if row else 0

def get_admin_stats() -> dict:
    """Get comprehensive admin statistics."""
    return {
        "live_users": get_live_users_count(10),
        "total_users": get_total_users(),
        "users_day": get_users_created_since(1),
        "users_week": get_users_created_since(7),
        "users_month": get_users_created_since(30),
        "course_creators_day": get_unique_users_for_event("course_created", 1),
        "course_creators_week": get_unique_users_for_event("course_created", 7),
        "course_creators_month": get_unique_users_for_event("course_created", 30),
        "total_courses_created": get_event_count("course_created"),
    }

# ============ LEGACY DATA HELPERS ============

def has_legacy_data() -> bool:
    """Check if there is any data with NULL user_id (legacy data)."""
    from security import validate_table_name
    tables_to_check = ["courses", "topics", "exams", "scheduled_lectures", "timed_attempts", "assessments"]
    for table in tables_to_check:
        # Validate table name against allowlist before using in query
        try:
            validated_table = validate_table_name(table)
        except ValueError:
            continue  # Skip invalid table names
        if table_exists(validated_table) and column_exists(validated_table, "user_id"):
            row = fetchone(f"SELECT COUNT(*) FROM {validated_table} WHERE user_id IS NULL")
            if row and row[0] > 0:
                return True
    return False

def get_legacy_data_counts() -> dict:
    """Get counts of legacy data (NULL user_id) per table."""
    from security import validate_table_name
    counts = {}
    tables_to_check = ["courses", "topics", "exams", "scheduled_lectures", "timed_attempts", "assessments"]
    for table in tables_to_check:
        # Validate table name against allowlist before using in query
        try:
            validated_table = validate_table_name(table)
        except ValueError:
            continue  # Skip invalid table names
        if table_exists(validated_table) and column_exists(validated_table, "user_id"):
            row = fetchone(f"SELECT COUNT(*) FROM {validated_table} WHERE user_id IS NULL")
            counts[validated_table] = row[0] if row else 0
    return counts

def claim_legacy_data(user_id: int) -> dict:
    """
    Assign all legacy data (NULL user_id) to the specified user.
    Returns counts of claimed rows per table.

    SECURITY: This function is disabled for safety. Legacy data migration
    should be done via admin scripts, not user-triggered actions.
    """
    # SECURITY: Disable legacy data claiming to prevent data theft
    # If you need to migrate legacy data, use a controlled admin script
    # that verifies ownership through other means (e.g., email verification)
    return {"error": "Legacy data claiming is disabled for security reasons"}


def _admin_claim_legacy_data(user_id: int) -> dict:
    """
    ADMIN ONLY: Assign all legacy data (NULL user_id) to the specified user.
    This function should only be called from admin scripts, never from user actions.

    Returns counts of claimed rows per table.
    """
    claimed = {}

    # First claim courses - only those with NULL user_id
    if table_exists("courses") and column_exists("courses", "user_id"):
        execute("UPDATE courses SET user_id=? WHERE user_id IS NULL", (user_id,))
        row = fetchone("SELECT changes()")  # SQLite specific
        claimed["courses"] = row[0] if row else 0

    # Get claimed course IDs to update related tables
    course_rows = fetchall("SELECT id FROM courses WHERE user_id=?", (user_id,))
    course_ids = [r[0] for r in course_rows] if course_rows else []

    if not course_ids:
        return claimed

    # Build parameterized IN clause safely
    placeholders = ",".join("?" * len(course_ids))

    # Claim topics for these courses
    if table_exists("topics") and column_exists("topics", "user_id"):
        execute(f"UPDATE topics SET user_id=? WHERE user_id IS NULL AND course_id IN ({placeholders})",
                (user_id, *course_ids))
        claimed["topics"] = len(fetchall(f"SELECT id FROM topics WHERE user_id=? AND course_id IN ({placeholders})",
                                         (user_id, *course_ids)))

    # Claim exams
    if table_exists("exams") and column_exists("exams", "user_id"):
        execute(f"UPDATE exams SET user_id=? WHERE user_id IS NULL AND course_id IN ({placeholders})",
                (user_id, *course_ids))
        claimed["exams"] = len(fetchall(f"SELECT id FROM exams WHERE user_id=? AND course_id IN ({placeholders})",
                                        (user_id, *course_ids)))

    # Claim scheduled_lectures
    if table_exists("scheduled_lectures") and column_exists("scheduled_lectures", "user_id"):
        execute(f"UPDATE scheduled_lectures SET user_id=? WHERE user_id IS NULL AND course_id IN ({placeholders})",
                (user_id, *course_ids))
        claimed["scheduled_lectures"] = len(fetchall(
            f"SELECT id FROM scheduled_lectures WHERE user_id=? AND course_id IN ({placeholders})",
            (user_id, *course_ids)))

    # Claim timed_attempts
    if table_exists("timed_attempts") and column_exists("timed_attempts", "user_id"):
        execute(f"UPDATE timed_attempts SET user_id=? WHERE user_id IS NULL AND course_id IN ({placeholders})",
                (user_id, *course_ids))
        claimed["timed_attempts"] = len(fetchall(
            f"SELECT id FROM timed_attempts WHERE user_id=? AND course_id IN ({placeholders})",
            (user_id, *course_ids)))

    # Claim assessments
    if table_exists("assessments") and column_exists("assessments", "user_id"):
        execute(f"UPDATE assessments SET user_id=? WHERE user_id IS NULL AND course_id IN ({placeholders})",
                (user_id, *course_ids))
        claimed["assessments"] = len(fetchall(
            f"SELECT id FROM assessments WHERE user_id=? AND course_id IN ({placeholders})",
            (user_id, *course_ids)))

    return claimed

def get_or_create_course(user_id: int, course_name: str) -> int:
    """Get existing course for user or create new one. Logs event on creation."""
    row = fetchone("SELECT id FROM courses WHERE user_id=? AND course_name=?", (user_id, course_name))
    if row:
        return row[0]
    else:
        course_id = execute_returning("INSERT INTO courses(user_id, course_name) VALUES(?,?)", (user_id, course_name))
        # Log course creation event for analytics
        log_event(user_id, "course_created", f'{{"course_name": "{course_name}", "course_id": {course_id}}}')
        return course_id

# ============ ASSESSMENT HELPERS ============

def get_course_total_marks(user_id: int, course_id: int) -> int:
    """Get total marks for a course by summing all assessment marks."""
    row = fetchone(
        "SELECT COALESCE(SUM(marks), 0) FROM assessments WHERE user_id=? AND course_id=?",
        (user_id, course_id)
    )
    return int(row[0]) if row and row[0] else 0

def get_next_due_date(user_id: int, course_id: int, today) -> tuple:
    """
    Get the next upcoming assessment due date for a course.
    Returns (due_date, assessment_name, is_timed) or (None, None, None) if none found.
    """
    from datetime import date as date_type
    if isinstance(today, str):
        from datetime import datetime
        today = datetime.strptime(today[:10], "%Y-%m-%d").date()
    
    row = fetchone(
        """SELECT due_date, assessment_name, is_timed 
           FROM assessments 
           WHERE user_id=? AND course_id=? AND due_date >= ?
           ORDER BY due_date ASC LIMIT 1""",
        (user_id, course_id, str(today))
    )
    if row and row[0]:
        from datetime import datetime
        import pandas as pd
        due = pd.to_datetime(row[0]).date()
        return due, row[1], bool(row[2])
    return None, None, None

def ensure_default_assessment(user_id: int, course_id: int) -> bool:
    """
    Ensure at least one assessment exists for a course.
    If none exist, create a default 'Final Exam' with 120 marks.
    Uses existing exam_date from exams table if available.
    Returns True if a default was created, False otherwise.
    """
    # Check if any assessments exist
    row = fetchone(
        "SELECT COUNT(*) FROM assessments WHERE user_id=? AND course_id=?",
        (user_id, course_id)
    )
    if row and row[0] > 0:
        return False  # Assessments already exist
    
    # Try to get existing exam date from exams table (backward compatibility)
    exam_row = fetchone(
        "SELECT exam_date, exam_name, is_retake FROM exams WHERE user_id=? AND course_id=? ORDER BY exam_date LIMIT 1",
        (user_id, course_id)
    )
    
    # Get course total_marks as default (if stored in courses table)
    course_row = fetchone(
        "SELECT total_marks FROM courses WHERE id=? AND user_id=?",
        (course_id, user_id)
    )
    default_marks = int(course_row[0]) if course_row and course_row[0] else 120
    
    if exam_row:
        # Migrate from old exam to new assessment
        execute_returning(
            """INSERT INTO assessments(user_id, course_id, assessment_name, assessment_type, marks, due_date, is_timed, notes)
               VALUES(?,?,?,?,?,?,?,?)""",
            (user_id, course_id, exam_row[1] or "Final Exam", "Exam", default_marks, exam_row[0], 1, "Auto-migrated from exams")
        )
    else:
        # Create a new default assessment
        execute_returning(
            """INSERT INTO assessments(user_id, course_id, assessment_name, assessment_type, marks, due_date, is_timed, notes)
               VALUES(?,?,?,?,?,?,?,?)""",
            (user_id, course_id, "Final Exam", "Exam", default_marks, None, 1, "Default assessment")
        )
    
    return True

def get_assessments(user_id: int, course_id: int):
    """Get all assessments for a course as a list of tuples."""
    return fetchall(
        """SELECT id, assessment_name, assessment_type, marks, due_date, is_timed, notes 
           FROM assessments WHERE user_id=? AND course_id=? ORDER BY due_date, id""",
        (user_id, course_id)
    )

