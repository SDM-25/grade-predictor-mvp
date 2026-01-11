"""
Database migrations system for SQLite and PostgreSQL compatibility.

This module provides:
- A migrations table to track applied migrations
- Auto-apply migrations at startup
- Schema validation to catch missing columns early
- Environment variable-based DB URL for portability

Usage:
    from migrations import run_migrations, validate_schema

    # Apply all pending migrations
    run_migrations()

    # Validate schema matches expected structure
    validate_schema()  # Raises SchemaError if invalid
"""

from .runner import (
    run_migrations,
    get_applied_migrations,
    get_pending_migrations,
    validate_schema,
    repair_schema,
    SchemaError,
    MigrationError,
    EXPECTED_SCHEMA,
)
