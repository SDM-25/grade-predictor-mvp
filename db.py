"""
Database module with Postgres (Supabase) support and SQLite fallback.
Includes authentication helpers with bcrypt password hashing.

Usage:
    from db import get_conn, execute, read_sql, init_db, is_postgres
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
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

# FIX: Use absolute path so database persists across reloads
# Database file lives in the same directory as this module
APP_DIR = Path(__file__).resolve().parent
SQLITE_PATH = str(APP_DIR / "grade_predictor.db")

def _get_postgres_config():
    """Get Postgres config from Streamlit secrets."""
    if not HAS_STREAMLIT:
        return None
    try:
        return {
            "host": st.secrets["DB_HOST"],
            "database": st.secrets["DB_NAME"],
            "user": st.secrets["DB_USER"],
            "password": st.secrets["DB_PASSWORD"],
            "port": st.secrets.get("DB_PORT", 5432),
        }
    except (KeyError, FileNotFoundError):
        return None

def is_postgres() -> bool:
    """Check if we're using Postgres (secrets available)."""
    return HAS_PSYCOPG2 and _get_postgres_config() is not None

# ============ CONNECTION HELPERS ============

@contextmanager
def get_conn():
    """
    Get a database connection (Postgres or SQLite).
    Use as context manager: with get_conn() as conn: ...
    """
    if is_postgres():
        config = _get_postgres_config()
        conn = psycopg2.connect(**config)
        try:
            yield conn
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
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
    if is_postgres():
        config = _get_postgres_config()
        return psycopg2.connect(**config)
    else:
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
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
        with get_conn() as conn:
            cur = conn.execute(f"PRAGMA table_info({table})")
            columns = [r[1] for r in cur.fetchall()]
            return column in columns

# ============ INIT DB ============

def init_db():
    """
    Initialize database schema with Postgres/SQLite compatibility.
    Handles migrations safely.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        
        if is_postgres():
            # ============ POSTGRES SCHEMA ============
            
            # Users table with auth fields
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
                # Migration: add missing auth columns
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
            
            # Exams table
            if not table_exists("exams"):
                cur.execute("""
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
                """)
            else:
                if not column_exists("exams", "user_id"):
                    cur.execute("ALTER TABLE exams ADD COLUMN user_id INTEGER REFERENCES users(id)")
                if not column_exists("exams", "marks"):
                    cur.execute("ALTER TABLE exams ADD COLUMN marks INTEGER DEFAULT 100")
                if not column_exists("exams", "actual_marks"):
                    cur.execute("ALTER TABLE exams ADD COLUMN actual_marks INTEGER DEFAULT NULL")
            
            # Topics table
            if not table_exists("topics"):
                cur.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    course_id INTEGER NOT NULL REFERENCES courses(id),
                    topic_name TEXT NOT NULL,
                    weight_points REAL NOT NULL DEFAULT 0,
                    notes TEXT
                );
                """)
            elif not column_exists("topics", "user_id"):
                cur.execute("ALTER TABLE topics ADD COLUMN user_id INTEGER REFERENCES users(id)")
            
            # Study sessions table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS study_sessions (
                id SERIAL PRIMARY KEY,
                topic_id INTEGER NOT NULL REFERENCES topics(id),
                session_date DATE NOT NULL,
                duration_mins INTEGER NOT NULL DEFAULT 30,
                quality INTEGER NOT NULL DEFAULT 3,
                notes TEXT
            );
            """)
            
            # Exercises table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS exercises (
                id SERIAL PRIMARY KEY,
                topic_id INTEGER NOT NULL REFERENCES topics(id),
                exercise_date DATE NOT NULL,
                total_questions INTEGER NOT NULL,
                correct_answers INTEGER NOT NULL,
                source TEXT,
                notes TEXT
            );
            """)
            
            # Scheduled lectures table
            if not table_exists("scheduled_lectures"):
                cur.execute("""
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
                """)
            elif not column_exists("scheduled_lectures", "user_id"):
                cur.execute("ALTER TABLE scheduled_lectures ADD COLUMN user_id INTEGER REFERENCES users(id)")
            
            # Timed attempts table (for past paper practice)
            if not table_exists("timed_attempts"):
                cur.execute("""
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
                """)
            elif not column_exists("timed_attempts", "user_id"):
                cur.execute("ALTER TABLE timed_attempts ADD COLUMN user_id INTEGER REFERENCES users(id)")
            
            # Assessments table (multi-assessment support)
            if not table_exists("assessments"):
                cur.execute("""
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
                """)
            else:
                if not column_exists("assessments", "actual_marks"):
                    cur.execute("ALTER TABLE assessments ADD COLUMN actual_marks INTEGER DEFAULT NULL")
                if not column_exists("assessments", "progress_pct"):
                    cur.execute("ALTER TABLE assessments ADD COLUMN progress_pct INTEGER DEFAULT 0")
            
            # Assignment work sessions table (track work done on assignments)
            cur.execute("""
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
            """)
            
            # Sessions table (for live user tracking)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                session_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """)
            
            # Events table (for analytics)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                event_name TEXT NOT NULL,
                event_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            );
            """)
        
        else:
            # ============ SQLITE SCHEMA ============
            
            # Users table with auth fields
            if not table_exists("users"):
                cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    username TEXT UNIQUE,
                    password_hash TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login_at TIMESTAMP
                );
                """)
            else:
                # Migration: add missing auth columns
                if not column_exists("users", "username"):
                    cur.execute("ALTER TABLE users ADD COLUMN username TEXT")
                if not column_exists("users", "password_hash"):
                    cur.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")
                if not column_exists("users", "last_login_at"):
                    cur.execute("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP")
            
            # Courses table
            if table_exists("courses"):
                if not column_exists("courses", "user_id"):
                    cur.execute("ALTER TABLE courses ADD COLUMN user_id INTEGER REFERENCES users(id)")
            else:
                cur.execute("""
                CREATE TABLE IF NOT EXISTS courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    course_name TEXT NOT NULL,
                    total_marks INTEGER NOT NULL DEFAULT 120,
                    target_marks INTEGER NOT NULL DEFAULT 90,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                """)
            
            # Exams table
            if table_exists("exams"):
                if not column_exists("exams", "user_id"):
                    cur.execute("ALTER TABLE exams ADD COLUMN user_id INTEGER REFERENCES users(id)")
                if not column_exists("exams", "marks"):
                    cur.execute("ALTER TABLE exams ADD COLUMN marks INTEGER DEFAULT 100")
                if not column_exists("exams", "actual_marks"):
                    cur.execute("ALTER TABLE exams ADD COLUMN actual_marks INTEGER DEFAULT NULL")
            else:
                cur.execute("""
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
                """)
            
            # Topics table
            if table_exists("topics"):
                if not column_exists("topics", "user_id"):
                    cur.execute("ALTER TABLE topics ADD COLUMN user_id INTEGER REFERENCES users(id)")
            else:
                cur.execute("""
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
                """)
            
            # Study sessions table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER NOT NULL,
                session_date DATE NOT NULL,
                duration_mins INTEGER NOT NULL DEFAULT 30,
                quality INTEGER NOT NULL DEFAULT 3,
                notes TEXT,
                FOREIGN KEY (topic_id) REFERENCES topics(id)
            );
            """)
            
            # Exercises table
            cur.execute("""
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
            """)
            
            # Scheduled lectures table
            if table_exists("scheduled_lectures"):
                if not column_exists("scheduled_lectures", "user_id"):
                    cur.execute("ALTER TABLE scheduled_lectures ADD COLUMN user_id INTEGER REFERENCES users(id)")
            else:
                cur.execute("""
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
                """)
            
            # Timed attempts table (for past paper practice)
            if table_exists("timed_attempts"):
                if not column_exists("timed_attempts", "user_id"):
                    cur.execute("ALTER TABLE timed_attempts ADD COLUMN user_id INTEGER REFERENCES users(id)")
            else:
                cur.execute("""
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
                """)
            
            # Assessments table (multi-assessment support)
            if table_exists("assessments"):
                if not column_exists("assessments", "actual_marks"):
                    cur.execute("ALTER TABLE assessments ADD COLUMN actual_marks INTEGER DEFAULT NULL")
                if not column_exists("assessments", "progress_pct"):
                    cur.execute("ALTER TABLE assessments ADD COLUMN progress_pct INTEGER DEFAULT 0")
            else:
                cur.execute("""
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
                """)
            
            # Assignment work sessions table (track work done on assignments)
            cur.execute("""
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
            """)
            
            # Sessions table (for live user tracking)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """)
            
            # Events table (for analytics)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event_name TEXT NOT NULL,
                event_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """)
        
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

        # Check username match
        if username != admin_username:
            return False

        # Mode A: bcrypt hash (preferred, more secure)
        if admin_password_hash:
            return verify_password(password, admin_password_hash)

        # Mode B: plaintext password (fallback for dev/testing)
        elif admin_password_plain:
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
    tables_to_check = ["courses", "topics", "exams", "scheduled_lectures", "timed_attempts", "assessments"]
    for table in tables_to_check:
        if table_exists(table) and column_exists(table, "user_id"):
            row = fetchone(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL")
            if row and row[0] > 0:
                return True
    return False

def get_legacy_data_counts() -> dict:
    """Get counts of legacy data (NULL user_id) per table."""
    counts = {}
    tables_to_check = ["courses", "topics", "exams", "scheduled_lectures", "timed_attempts", "assessments"]
    for table in tables_to_check:
        if table_exists(table) and column_exists(table, "user_id"):
            row = fetchone(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL")
            counts[table] = row[0] if row else 0
    return counts

def claim_legacy_data(user_id: int) -> dict:
    """
    Assign all legacy data (NULL user_id) to the specified user.
    Returns counts of claimed rows per table.
    """
    claimed = {}
    
    # First claim courses
    if table_exists("courses") and column_exists("courses", "user_id"):
        execute("UPDATE courses SET user_id=? WHERE user_id IS NULL", (user_id,))
        row = fetchone("SELECT changes()")  # SQLite specific
        claimed["courses"] = row[0] if row else 0
    
    # Get claimed course IDs to update related tables
    course_rows = fetchall("SELECT id FROM courses WHERE user_id=?", (user_id,))
    course_ids = [r[0] for r in course_rows] if course_rows else []
    
    # Claim topics for these courses
    if table_exists("topics") and column_exists("topics", "user_id") and course_ids:
        placeholders = ",".join("?" * len(course_ids))
        execute(f"UPDATE topics SET user_id=? WHERE user_id IS NULL AND course_id IN ({placeholders})", 
                (user_id, *course_ids))
        claimed["topics"] = len(fetchall(f"SELECT id FROM topics WHERE user_id=? AND course_id IN ({placeholders})", 
                                         (user_id, *course_ids))) if course_ids else 0
    
    # Claim exams
    if table_exists("exams") and column_exists("exams", "user_id") and course_ids:
        placeholders = ",".join("?" * len(course_ids))
        execute(f"UPDATE exams SET user_id=? WHERE user_id IS NULL AND course_id IN ({placeholders})", 
                (user_id, *course_ids))
        claimed["exams"] = len(fetchall(f"SELECT id FROM exams WHERE user_id=? AND course_id IN ({placeholders})", 
                                        (user_id, *course_ids))) if course_ids else 0
    
    # Claim scheduled_lectures
    if table_exists("scheduled_lectures") and column_exists("scheduled_lectures", "user_id") and course_ids:
        placeholders = ",".join("?" * len(course_ids))
        execute(f"UPDATE scheduled_lectures SET user_id=? WHERE user_id IS NULL AND course_id IN ({placeholders})", 
                (user_id, *course_ids))
        claimed["scheduled_lectures"] = len(fetchall(
            f"SELECT id FROM scheduled_lectures WHERE user_id=? AND course_id IN ({placeholders})", 
            (user_id, *course_ids))) if course_ids else 0
    
    # Claim timed_attempts
    if table_exists("timed_attempts") and column_exists("timed_attempts", "user_id") and course_ids:
        placeholders = ",".join("?" * len(course_ids))
        execute(f"UPDATE timed_attempts SET user_id=? WHERE user_id IS NULL AND course_id IN ({placeholders})", 
                (user_id, *course_ids))
        claimed["timed_attempts"] = len(fetchall(
            f"SELECT id FROM timed_attempts WHERE user_id=? AND course_id IN ({placeholders})", 
            (user_id, *course_ids))) if course_ids else 0
    
    # Claim assessments
    if table_exists("assessments") and column_exists("assessments", "user_id") and course_ids:
        placeholders = ",".join("?" * len(course_ids))
        execute(f"UPDATE assessments SET user_id=? WHERE user_id IS NULL AND course_id IN ({placeholders})", 
                (user_id, *course_ids))
        claimed["assessments"] = len(fetchall(
            f"SELECT id FROM assessments WHERE user_id=? AND course_id IN ({placeholders})", 
            (user_id, *course_ids))) if course_ids else 0
    
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

