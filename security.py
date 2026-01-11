"""
Security module for Exam Readiness Predictor.
Provides input validation, sanitization, and rate limiting helpers.
"""

import re
import html
import time
from datetime import datetime, timedelta
from typing import Optional, Any, Set
from functools import wraps

# ============ TABLE NAME ALLOWLIST ============
# Only these table names are allowed in dynamic SQL queries
ALLOWED_TABLES: Set[str] = frozenset({
    "courses",
    "topics",
    "exams",
    "scheduled_lectures",
    "timed_attempts",
    "assessments",
    "assignment_work",
    "study_sessions",
    "exercises",
    "users",
    "sessions",
    "auth_tokens",
    "events",
})

# Allowed column names for dynamic queries
ALLOWED_COLUMNS: Set[str] = frozenset({
    "id", "user_id", "course_id", "topic_id", "exam_id", "assessment_id",
    "course_name", "topic_name", "exam_name", "assessment_name",
    "total_marks", "marks", "target_marks", "actual_marks", "weight_points",
    "exam_date", "due_date", "created_at", "updated_at", "last_seen_at",
    "is_retake", "is_timed", "notes", "assessment_type",
    "email", "username", "password_hash", "session_id",
    "event_type", "event_data", "timestamp",
})


def validate_table_name(table: str) -> str:
    """
    Validate table name against allowlist.
    Raises ValueError if table name is not allowed.

    Args:
        table: Table name to validate

    Returns:
        The validated table name (unchanged if valid)

    Raises:
        ValueError: If table name is not in allowlist
    """
    if not table or not isinstance(table, str):
        raise ValueError("Table name must be a non-empty string")

    table_clean = table.strip().lower()

    if table_clean not in ALLOWED_TABLES:
        raise ValueError(f"Invalid table name: {table}")

    return table_clean


def validate_column_name(column: str) -> str:
    """
    Validate column name against allowlist.
    Raises ValueError if column name is not allowed.
    """
    if not column or not isinstance(column, str):
        raise ValueError("Column name must be a non-empty string")

    column_clean = column.strip().lower()

    if column_clean not in ALLOWED_COLUMNS:
        raise ValueError(f"Invalid column name: {column}")

    return column_clean


def validate_identifier(name: str, identifier_type: str = "identifier") -> str:
    """
    Validate a SQL identifier (table/column name) using strict pattern.
    Only allows alphanumeric characters and underscores.

    Args:
        name: The identifier to validate
        identifier_type: Type for error message (e.g., "table", "column")

    Returns:
        The validated identifier

    Raises:
        ValueError: If identifier contains invalid characters
    """
    if not name or not isinstance(name, str):
        raise ValueError(f"{identifier_type} must be a non-empty string")

    # Only allow alphanumeric and underscore, must start with letter
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', name):
        raise ValueError(f"Invalid {identifier_type}: {name}")

    return name


# ============ INPUT SANITIZATION ============

def sanitize_string(value: str, max_length: int = 1000, allow_newlines: bool = False) -> str:
    """
    Sanitize a string input by stripping whitespace and limiting length.

    Args:
        value: String to sanitize
        max_length: Maximum allowed length (default 1000)
        allow_newlines: If False, replace newlines with spaces

    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        return ""

    result = value.strip()

    if not allow_newlines:
        result = re.sub(r'[\r\n]+', ' ', result)

    # Limit length
    if len(result) > max_length:
        result = result[:max_length]

    return result


def sanitize_html(value: str) -> str:
    """
    Escape HTML special characters to prevent XSS.
    Use when displaying user input in HTML context.
    """
    if not isinstance(value, str):
        return ""
    return html.escape(value)


def validate_email(email: str) -> bool:
    """
    Validate email format.

    Args:
        email: Email address to validate

    Returns:
        True if valid email format, False otherwise
    """
    if not email or not isinstance(email, str):
        return False

    # Basic email pattern - not exhaustive but catches most issues
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))


def validate_numeric_range(value: Any, min_val: Optional[float] = None,
                          max_val: Optional[float] = None,
                          allow_none: bool = False) -> bool:
    """
    Validate that a numeric value is within expected range.

    Args:
        value: Value to validate
        min_val: Minimum allowed value (inclusive)
        max_val: Maximum allowed value (inclusive)
        allow_none: If True, None values are valid

    Returns:
        True if valid, False otherwise
    """
    if value is None:
        return allow_none

    try:
        num = float(value)
    except (TypeError, ValueError):
        return False

    if min_val is not None and num < min_val:
        return False
    if max_val is not None and num > max_val:
        return False

    return True


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent path traversal attacks.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename with only safe characters
    """
    if not filename or not isinstance(filename, str):
        return "unnamed"

    # Remove path separators and null bytes
    filename = filename.replace('/', '_').replace('\\', '_').replace('\0', '')

    # Remove leading dots (hidden files, path traversal)
    filename = filename.lstrip('.')

    # Only keep alphanumeric, dots, hyphens, underscores
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)

    # Limit length
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:250] + ('.' + ext if ext else '')

    return filename or "unnamed"


# ============ RATE LIMITING ============

class RateLimiter:
    """
    Simple in-memory rate limiter for protecting against abuse.
    Uses sliding window algorithm.

    Note: This is per-process. For production with multiple workers,
    use Redis-based rate limiting.
    """

    def __init__(self):
        self._requests: dict = {}  # key -> list of timestamps

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """
        Check if a request is allowed under rate limit.

        Args:
            key: Identifier for rate limit bucket (e.g., user_id, IP)
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds

        Returns:
            True if request is allowed, False if rate limited
        """
        now = time.time()
        cutoff = now - window_seconds

        # Get existing requests for this key
        if key not in self._requests:
            self._requests[key] = []

        # Remove old requests outside window
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]

        # Check if under limit
        if len(self._requests[key]) >= max_requests:
            return False

        # Record this request
        self._requests[key].append(now)
        return True

    def get_retry_after(self, key: str, window_seconds: int) -> int:
        """
        Get seconds until rate limit resets for a key.

        Returns:
            Seconds until oldest request expires from window
        """
        if key not in self._requests or not self._requests[key]:
            return 0

        oldest = min(self._requests[key])
        retry_after = int(oldest + window_seconds - time.time())
        return max(0, retry_after)

    def cleanup(self, max_age_seconds: int = 3600):
        """Remove stale entries older than max_age_seconds."""
        cutoff = time.time() - max_age_seconds
        keys_to_remove = []

        for key, timestamps in self._requests.items():
            # Remove old timestamps
            self._requests[key] = [t for t in timestamps if t > cutoff]
            # Mark empty keys for removal
            if not self._requests[key]:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._requests[key]


# Global rate limiter instance
_rate_limiter = RateLimiter()


def check_rate_limit(key: str, max_requests: int = 60, window_seconds: int = 60) -> bool:
    """
    Check if request is allowed under rate limit.
    Convenience wrapper around global RateLimiter.

    Default: 60 requests per 60 seconds (1 req/sec average)
    """
    return _rate_limiter.is_allowed(key, max_requests, window_seconds)


def get_rate_limit_retry_after(key: str, window_seconds: int = 60) -> int:
    """Get seconds until rate limit resets."""
    return _rate_limiter.get_retry_after(key, window_seconds)


# ============ SESSION SECURITY ============

def generate_secure_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random token.

    Args:
        length: Number of bytes (output will be ~1.3x longer as base64)

    Returns:
        URL-safe base64 encoded token
    """
    import secrets
    return secrets.token_urlsafe(length)


def hash_token(token: str) -> str:
    """
    Hash a token for secure storage.
    Uses SHA-256 - suitable for tokens with sufficient entropy.
    """
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


# ============ FILE UPLOAD SECURITY ============

# Maximum file sizes in bytes
MAX_PDF_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_TOTAL_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB total per request

# Allowed MIME types
ALLOWED_PDF_TYPES = {'application/pdf'}
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}


def validate_file_size(file_content: bytes, max_size: int = MAX_PDF_SIZE) -> bool:
    """
    Validate file size is within limit.

    Args:
        file_content: File content as bytes
        max_size: Maximum allowed size in bytes

    Returns:
        True if within limit, False otherwise
    """
    return len(file_content) <= max_size


def validate_pdf_header(file_content: bytes) -> bool:
    """
    Validate file has PDF magic bytes.
    Basic check - does not guarantee file is safe.
    """
    return file_content[:4] == b'%PDF'


# ============ SQL INJECTION PREVENTION ============

def escape_like_pattern(pattern: str) -> str:
    """
    Escape special characters in LIKE patterns.
    Use this when incorporating user input into LIKE clauses.

    Args:
        pattern: User-provided search pattern

    Returns:
        Escaped pattern safe for use in LIKE clause
    """
    # Escape SQL LIKE special characters
    pattern = pattern.replace('\\', '\\\\')  # Escape backslash first
    pattern = pattern.replace('%', '\\%')
    pattern = pattern.replace('_', '\\_')
    return pattern


def safe_like_contains(value: str) -> str:
    """
    Create a safe LIKE pattern for 'contains' search.

    Args:
        value: User search term

    Returns:
        Escaped pattern with wildcards: %escaped_value%
    """
    return f"%{escape_like_pattern(value)}%"
