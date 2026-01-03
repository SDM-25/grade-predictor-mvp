"""
DEPRECATED: This module is now a backwards-compatibility shim.
All business logic has been moved to services/dashboard.py

Import from services instead:
    from services import (
        get_all_courses, get_all_upcoming_assessments,
        get_course_topic_count, get_course_assessment_count,
        get_last_timed_attempt_date, compute_course_snapshot,
        generate_recommended_tasks, get_at_risk_courses,
    )
"""

# Re-export from services for backwards compatibility
from services.dashboard import (
    get_all_courses,
    get_all_upcoming_assessments,
    get_course_assessment_count,
    get_course_topic_count,
    get_last_timed_attempt_date,
    compute_course_snapshot,
    generate_recommended_tasks,
    get_at_risk_courses,
)

__all__ = [
    "get_all_courses",
    "get_all_upcoming_assessments",
    "get_course_assessment_count",
    "get_course_topic_count",
    "get_last_timed_attempt_date",
    "compute_course_snapshot",
    "generate_recommended_tasks",
    "get_at_risk_courses",
]
