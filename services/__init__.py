"""
Services layer - pure Python business logic with NO Streamlit dependencies.

This layer contains:
- metrics.py: Mastery and readiness computation
- dashboard.py: Course snapshots, task recommendations, at-risk detection
- recommendations.py: Study recommendations generator

All functions accept explicit parameters and return plain dicts/lists.
Ready for Next.js API migration.
"""

from services.metrics import compute_mastery, decay_factor, compute_readiness
from services.dashboard import (
    get_all_courses,
    get_all_upcoming_assessments,
    get_course_topic_count,
    get_course_assessment_count,
    get_last_timed_attempt_date,
    compute_course_snapshot,
    generate_recommended_tasks,
    get_at_risk_courses,
)
from services.recommendations import generate_recommendations

__all__ = [
    # metrics
    "compute_mastery",
    "decay_factor",
    "compute_readiness",
    # dashboard
    "get_all_courses",
    "get_all_upcoming_assessments",
    "get_course_topic_count",
    "get_course_assessment_count",
    "get_last_timed_attempt_date",
    "compute_course_snapshot",
    "generate_recommended_tasks",
    "get_at_risk_courses",
    # recommendations
    "generate_recommendations",
]
