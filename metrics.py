"""
DEPRECATED: This module is now a backwards-compatibility shim.
All business logic has been moved to services/metrics.py

Import from services instead:
    from services import compute_mastery, decay_factor, compute_readiness
"""

# Re-export from services for backwards compatibility
from services.metrics import compute_mastery, decay_factor, compute_readiness

__all__ = ["compute_mastery", "decay_factor", "compute_readiness"]
