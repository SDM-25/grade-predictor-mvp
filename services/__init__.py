"""
Services layer - pure Python business logic with NO Streamlit dependencies.

This layer contains:
- core.py: CRUD operations and API-ready functions
- metrics.py: Mastery and readiness computation
- dashboard.py: Course snapshots, task recommendations, at-risk detection
- recommendations.py: Study recommendations generator

All functions accept explicit parameters and return plain dicts/lists.
Ready for Next.js / FastAPI migration.
"""

# Core API functions (CRUD + analytics)
from services.core import (
    # Course CRUD
    create_course,
    list_courses,
    get_course,
    update_course,
    delete_course,
    # Assessment CRUD
    create_assessment,
    list_assessments,
    update_assessment,
    delete_assessment,
    # Topic CRUD
    create_topic,
    list_topics,
    update_topic,
    delete_topic,
    # Activity logging
    add_study_session,
    add_exercise,
    add_timed_attempt,
    # Analytics
    compute_course_readiness,
    generate_week_plan,
)

# Metrics functions
from services.metrics import (
    compute_mastery,
    decay_factor,
    compute_readiness,
)

# Dashboard functions
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

# Recommendations
from services.recommendations import generate_recommendations

__all__ = [
    # Core - Course CRUD
    "create_course",
    "list_courses",
    "get_course",
    "update_course",
    "delete_course",
    # Core - Assessment CRUD
    "create_assessment",
    "list_assessments",
    "update_assessment",
    "delete_assessment",
    # Core - Topic CRUD
    "create_topic",
    "list_topics",
    "update_topic",
    "delete_topic",
    # Core - Activity logging
    "add_study_session",
    "add_exercise",
    "add_timed_attempt",
    # Core - Analytics
    "compute_course_readiness",
    "generate_week_plan",
    # Metrics
    "compute_mastery",
    "decay_factor",
    "compute_readiness",
    # Dashboard
    "get_all_courses",
    "get_all_upcoming_assessments",
    "get_course_topic_count",
    "get_course_assessment_count",
    "get_last_timed_attempt_date",
    "compute_course_snapshot",
    "generate_recommended_tasks",
    "get_at_risk_courses",
    # Recommendations
    "generate_recommendations",
]
