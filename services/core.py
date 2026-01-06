"""
Core API service functions for the Exam Readiness Predictor.

These functions are designed to be:
- Pure Python (NO Streamlit dependencies)
- Explicit inputs (no session_state)
- JSON-serializable outputs (dict/list/str/float/bool)
- Ready for FastAPI migration

Usage:
    from services.core import create_course, list_courses, compute_course_readiness
"""

from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Union
import sys
import os

# Add parent directory to path for db import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import (
    execute, execute_returning, read_sql, fetchone, fetchall,
    get_conn, is_postgres, log_event
)


# ============================================================================
# COURSE CRUD
# ============================================================================

def create_course(
    user_id: int,
    name: str,
    total_marks: int = 120,
    target_marks: int = 90
) -> Dict[str, Any]:
    """
    Create a new course for a user.

    Args:
        user_id: The user's ID
        name: Course name (e.g., "Microeconomics")
        total_marks: Maximum possible marks (default 120)
        target_marks: Target marks to achieve (default 90)

    Returns:
        Dict with course_id, name, total_marks, target_marks, created: bool
    """
    # Check if course already exists
    existing = fetchone(
        "SELECT id FROM courses WHERE user_id=? AND course_name=?",
        (user_id, name.strip())
    )
    if existing:
        return {
            "course_id": existing[0],
            "name": name.strip(),
            "total_marks": total_marks,
            "target_marks": target_marks,
            "created": False
        }

    course_id = execute_returning(
        "INSERT INTO courses(user_id, course_name, total_marks, target_marks) VALUES(?,?,?,?)",
        (user_id, name.strip(), total_marks, target_marks)
    )

    # Log event for analytics
    log_event(user_id, "course_created", f'{{"course_name": "{name.strip()}", "course_id": {course_id}}}')

    return {
        "course_id": course_id,
        "name": name.strip(),
        "total_marks": total_marks,
        "target_marks": target_marks,
        "created": True
    }


def list_courses(user_id: int) -> List[Dict[str, Any]]:
    """
    List all courses for a user.

    Args:
        user_id: The user's ID

    Returns:
        List of course dicts with id, name, total_marks, target_marks
    """
    rows = fetchall(
        "SELECT id, course_name, total_marks, target_marks FROM courses WHERE user_id=? ORDER BY id",
        (user_id,)
    )
    return [
        {
            "id": r[0],
            "name": r[1],
            "total_marks": r[2] or 120,
            "target_marks": r[3] or 90
        }
        for r in (rows or [])
    ]


def get_course(user_id: int, course_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a single course by ID.

    Args:
        user_id: The user's ID
        course_id: The course ID

    Returns:
        Course dict or None if not found
    """
    row = fetchone(
        "SELECT id, course_name, total_marks, target_marks FROM courses WHERE id=? AND user_id=?",
        (course_id, user_id)
    )
    if not row:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "total_marks": row[2] or 120,
        "target_marks": row[3] or 90
    }


def update_course(
    user_id: int,
    course_id: int,
    name: Optional[str] = None,
    total_marks: Optional[int] = None,
    target_marks: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    Update a course's settings.

    Args:
        user_id: The user's ID
        course_id: The course ID
        name: New course name (optional)
        total_marks: New total marks (optional)
        target_marks: New target marks (optional)

    Returns:
        Updated course dict or None if not found
    """
    # Verify ownership
    existing = get_course(user_id, course_id)
    if not existing:
        return None

    updates = []
    params = []

    if name is not None:
        updates.append("course_name=?")
        params.append(name.strip())
    if total_marks is not None:
        updates.append("total_marks=?")
        params.append(total_marks)
    if target_marks is not None:
        updates.append("target_marks=?")
        params.append(target_marks)

    if updates:
        params.extend([course_id, user_id])
        execute(
            f"UPDATE courses SET {', '.join(updates)} WHERE id=? AND user_id=?",
            tuple(params)
        )

    return get_course(user_id, course_id)


def delete_course(user_id: int, course_id: int) -> Dict[str, Any]:
    """
    Delete a course and all related data (cascade).

    Args:
        user_id: The user's ID
        course_id: The course ID

    Returns:
        Dict with deleted: bool, deleted_counts: dict of table -> count
    """
    # Verify ownership
    existing = get_course(user_id, course_id)
    if not existing:
        return {"deleted": False, "error": "Course not found"}

    deleted_counts = {}

    # Get topic IDs for cascade delete
    topic_rows = fetchall(
        "SELECT id FROM topics WHERE user_id=? AND course_id=?",
        (user_id, course_id)
    )
    topic_ids = [r[0] for r in (topic_rows or [])]

    with get_conn() as conn:
        cur = conn.cursor()
        placeholder = "%s" if is_postgres() else "?"

        # Delete study sessions and exercises for topics
        if topic_ids:
            placeholders = ",".join([placeholder] * len(topic_ids))
            cur.execute(f"DELETE FROM study_sessions WHERE topic_id IN ({placeholders})", topic_ids)
            cur.execute(f"DELETE FROM exercises WHERE topic_id IN ({placeholders})", topic_ids)

        # Delete topics
        cur.execute(
            f"DELETE FROM topics WHERE user_id={placeholder} AND course_id={placeholder}",
            (user_id, course_id)
        )
        deleted_counts["topics"] = len(topic_ids)

        # Delete assessments
        cur.execute(
            f"DELETE FROM assessments WHERE user_id={placeholder} AND course_id={placeholder}",
            (user_id, course_id)
        )

        # Delete lectures
        cur.execute(
            f"DELETE FROM scheduled_lectures WHERE user_id={placeholder} AND course_id={placeholder}",
            (user_id, course_id)
        )

        # Delete timed attempts
        cur.execute(
            f"DELETE FROM timed_attempts WHERE user_id={placeholder} AND course_id={placeholder}",
            (user_id, course_id)
        )

        # Delete exams (legacy)
        cur.execute(
            f"DELETE FROM exams WHERE user_id={placeholder} AND course_id={placeholder}",
            (user_id, course_id)
        )

        # Delete course
        cur.execute(
            f"DELETE FROM courses WHERE id={placeholder} AND user_id={placeholder}",
            (course_id, user_id)
        )

        conn.commit()

    return {"deleted": True, "deleted_counts": deleted_counts}


# ============================================================================
# ASSESSMENT CRUD
# ============================================================================

def create_assessment(
    user_id: int,
    course_id: int,
    name: str,
    assessment_type: str,
    marks: int,
    due_date: Optional[str] = None,
    is_timed: bool = True,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new assessment for a course.

    Args:
        user_id: The user's ID
        course_id: The course ID
        name: Assessment name (e.g., "Midterm Exam")
        assessment_type: Type (e.g., "Exam", "Assignment", "Quiz")
        marks: Maximum marks for this assessment
        due_date: Due date as ISO string (YYYY-MM-DD) or None
        is_timed: Whether this is a timed assessment (affects readiness calc)
        notes: Optional notes

    Returns:
        Dict with assessment details
    """
    assessment_id = execute_returning(
        """INSERT INTO assessments(user_id, course_id, assessment_name, assessment_type, marks, due_date, is_timed, notes)
           VALUES(?,?,?,?,?,?,?,?)""",
        (user_id, course_id, name.strip(), assessment_type, marks, due_date, 1 if is_timed else 0, notes)
    )

    return {
        "id": assessment_id,
        "course_id": course_id,
        "name": name.strip(),
        "type": assessment_type,
        "marks": marks,
        "due_date": due_date,
        "is_timed": is_timed,
        "actual_marks": None,
        "progress_pct": 0,
        "notes": notes
    }


def list_assessments(user_id: int, course_id: int) -> List[Dict[str, Any]]:
    """
    List all assessments for a course.

    Args:
        user_id: The user's ID
        course_id: The course ID

    Returns:
        List of assessment dicts
    """
    rows = fetchall(
        """SELECT id, assessment_name, assessment_type, marks, actual_marks, progress_pct, due_date, is_timed, notes
           FROM assessments WHERE user_id=? AND course_id=? ORDER BY due_date, id""",
        (user_id, course_id)
    )
    return [
        {
            "id": r[0],
            "name": r[1],
            "type": r[2],
            "marks": r[3],
            "actual_marks": r[4],
            "progress_pct": r[5] or 0,
            "due_date": str(r[6]) if r[6] else None,
            "is_timed": bool(r[7]),
            "notes": r[8]
        }
        for r in (rows or [])
    ]


def update_assessment(
    user_id: int,
    assessment_id: int,
    name: Optional[str] = None,
    assessment_type: Optional[str] = None,
    marks: Optional[int] = None,
    actual_marks: Optional[int] = None,
    progress_pct: Optional[int] = None,
    due_date: Optional[str] = None,
    is_timed: Optional[bool] = None,
    notes: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Update an assessment.

    Returns:
        Updated assessment dict or None if not found
    """
    # Verify ownership
    existing = fetchone(
        "SELECT id FROM assessments WHERE id=? AND user_id=?",
        (assessment_id, user_id)
    )
    if not existing:
        return None

    updates = []
    params = []

    if name is not None:
        updates.append("assessment_name=?")
        params.append(name.strip())
    if assessment_type is not None:
        updates.append("assessment_type=?")
        params.append(assessment_type)
    if marks is not None:
        updates.append("marks=?")
        params.append(marks)
    if actual_marks is not None:
        updates.append("actual_marks=?")
        params.append(actual_marks)
    if progress_pct is not None:
        updates.append("progress_pct=?")
        params.append(progress_pct)
    if due_date is not None:
        updates.append("due_date=?")
        params.append(due_date)
    if is_timed is not None:
        updates.append("is_timed=?")
        params.append(1 if is_timed else 0)
    if notes is not None:
        updates.append("notes=?")
        params.append(notes)

    if updates:
        params.extend([assessment_id, user_id])
        execute(
            f"UPDATE assessments SET {', '.join(updates)} WHERE id=? AND user_id=?",
            tuple(params)
        )

    # Return updated assessment
    row = fetchone(
        """SELECT id, course_id, assessment_name, assessment_type, marks, actual_marks, progress_pct, due_date, is_timed, notes
           FROM assessments WHERE id=? AND user_id=?""",
        (assessment_id, user_id)
    )
    if row:
        return {
            "id": row[0],
            "course_id": row[1],
            "name": row[2],
            "type": row[3],
            "marks": row[4],
            "actual_marks": row[5],
            "progress_pct": row[6] or 0,
            "due_date": str(row[7]) if row[7] else None,
            "is_timed": bool(row[8]),
            "notes": row[9]
        }
    return None


def delete_assessment(user_id: int, assessment_id: int) -> bool:
    """
    Delete an assessment.

    Returns:
        True if deleted, False if not found
    """
    existing = fetchone(
        "SELECT id FROM assessments WHERE id=? AND user_id=?",
        (assessment_id, user_id)
    )
    if not existing:
        return False

    execute("DELETE FROM assessments WHERE id=? AND user_id=?", (assessment_id, user_id))
    return True


# ============================================================================
# TOPIC CRUD
# ============================================================================

def create_topic(
    user_id: int,
    course_id: int,
    name: str,
    weight_points: float = 10.0,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new topic for a course.

    Args:
        user_id: The user's ID
        course_id: The course ID
        name: Topic name
        weight_points: Weight/points for this topic (default 10)
        notes: Optional notes

    Returns:
        Dict with topic details
    """
    topic_id = execute_returning(
        "INSERT INTO topics(user_id, course_id, topic_name, weight_points, notes) VALUES(?,?,?,?,?)",
        (user_id, course_id, name.strip(), weight_points, notes)
    )

    return {
        "id": topic_id,
        "course_id": course_id,
        "name": name.strip(),
        "weight_points": weight_points,
        "notes": notes
    }


def list_topics(
    user_id: int,
    course_id: int,
    include_mastery: bool = False
) -> List[Dict[str, Any]]:
    """
    List all topics for a course.

    Args:
        user_id: The user's ID
        course_id: The course ID
        include_mastery: If True, compute mastery for each topic

    Returns:
        List of topic dicts (optionally with mastery data)
    """
    rows = fetchall(
        "SELECT id, topic_name, weight_points, notes FROM topics WHERE user_id=? AND course_id=? ORDER BY id",
        (user_id, course_id)
    )

    topics = []
    for r in (rows or []):
        topic = {
            "id": r[0],
            "name": r[1],
            "weight_points": r[2] or 0,
            "notes": r[3]
        }

        if include_mastery:
            from services.metrics import compute_mastery
            today = date.today()
            m, last_act, ex_cnt, st_cnt, lec_cnt, timed_sig, timed_cnt = compute_mastery(r[0], today, False)
            topic.update({
                "mastery": round(m, 2),
                "last_activity": str(last_act) if last_act else None,
                "exercise_count": ex_cnt,
                "study_session_count": st_cnt,
                "lecture_count": lec_cnt
            })

        topics.append(topic)

    return topics


def update_topic(
    user_id: int,
    topic_id: int,
    name: Optional[str] = None,
    weight_points: Optional[float] = None,
    notes: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Update a topic.

    Returns:
        Updated topic dict or None if not found
    """
    existing = fetchone(
        "SELECT id FROM topics WHERE id=? AND user_id=?",
        (topic_id, user_id)
    )
    if not existing:
        return None

    updates = []
    params = []

    if name is not None:
        updates.append("topic_name=?")
        params.append(name.strip())
    if weight_points is not None:
        updates.append("weight_points=?")
        params.append(weight_points)
    if notes is not None:
        updates.append("notes=?")
        params.append(notes)

    if updates:
        params.extend([topic_id, user_id])
        execute(
            f"UPDATE topics SET {', '.join(updates)} WHERE id=? AND user_id=?",
            tuple(params)
        )

    row = fetchone(
        "SELECT id, course_id, topic_name, weight_points, notes FROM topics WHERE id=? AND user_id=?",
        (topic_id, user_id)
    )
    if row:
        return {
            "id": row[0],
            "course_id": row[1],
            "name": row[2],
            "weight_points": row[3] or 0,
            "notes": row[4]
        }
    return None


def delete_topic(user_id: int, topic_id: int) -> bool:
    """
    Delete a topic and all related study sessions/exercises.

    Returns:
        True if deleted, False if not found
    """
    existing = fetchone(
        "SELECT id FROM topics WHERE id=? AND user_id=?",
        (topic_id, user_id)
    )
    if not existing:
        return False

    # Delete related data
    execute("DELETE FROM study_sessions WHERE topic_id=?", (topic_id,))
    execute("DELETE FROM exercises WHERE topic_id=?", (topic_id,))
    execute("DELETE FROM topics WHERE id=? AND user_id=?", (topic_id, user_id))

    return True


# ============================================================================
# STUDY ACTIVITY LOGGING
# ============================================================================

def add_study_session(
    topic_id: int,
    session_date: str,
    duration_mins: int,
    quality: int = 3,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Log a study session for a topic.

    Args:
        topic_id: The topic ID
        session_date: Date as ISO string (YYYY-MM-DD)
        duration_mins: Duration in minutes
        quality: Quality rating 1-5 (default 3)
        notes: Optional notes

    Returns:
        Dict with session details
    """
    session_id = execute_returning(
        "INSERT INTO study_sessions(topic_id, session_date, duration_mins, quality, notes) VALUES(?,?,?,?,?)",
        (topic_id, session_date, duration_mins, quality, notes)
    )

    return {
        "id": session_id,
        "topic_id": topic_id,
        "date": session_date,
        "duration_mins": duration_mins,
        "quality": quality,
        "notes": notes
    }


def add_exercise(
    topic_id: int,
    exercise_date: str,
    total_questions: int,
    correct_answers: int,
    source: Optional[str] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Log an exercise attempt for a topic.

    Args:
        topic_id: The topic ID
        exercise_date: Date as ISO string (YYYY-MM-DD)
        total_questions: Number of questions attempted
        correct_answers: Number of correct answers
        source: Source of exercises (e.g., "Past Paper 2023")
        notes: Optional notes

    Returns:
        Dict with exercise details including score_pct
    """
    exercise_id = execute_returning(
        "INSERT INTO exercises(topic_id, exercise_date, total_questions, correct_answers, source, notes) VALUES(?,?,?,?,?,?)",
        (topic_id, exercise_date, total_questions, correct_answers, source, notes)
    )

    score_pct = (correct_answers / total_questions * 100) if total_questions > 0 else 0

    return {
        "id": exercise_id,
        "topic_id": topic_id,
        "date": exercise_date,
        "total_questions": total_questions,
        "correct_answers": correct_answers,
        "score_pct": round(score_pct, 1),
        "source": source,
        "notes": notes
    }


def add_timed_attempt(
    user_id: int,
    course_id: int,
    attempt_date: str,
    source: str,
    minutes: int,
    score_pct: float,
    topics: Optional[str] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Log a timed practice attempt (past paper, mock exam).

    Args:
        user_id: The user's ID
        course_id: The course ID
        attempt_date: Date as ISO string (YYYY-MM-DD)
        source: Source (e.g., "2023 Past Paper")
        minutes: Time spent in minutes
        score_pct: Score as percentage (0-100)
        topics: Comma-separated topic names covered
        notes: Optional notes

    Returns:
        Dict with attempt details
    """
    attempt_id = execute_returning(
        "INSERT INTO timed_attempts(user_id, course_id, attempt_date, source, minutes, score_pct, topics, notes) VALUES(?,?,?,?,?,?,?,?)",
        (user_id, course_id, attempt_date, source, minutes, score_pct, topics, notes)
    )

    return {
        "id": attempt_id,
        "course_id": course_id,
        "date": attempt_date,
        "source": source,
        "minutes": minutes,
        "score_pct": round(score_pct, 1),
        "topics": topics,
        "notes": notes
    }


# ============================================================================
# READINESS & ANALYTICS
# ============================================================================

def compute_course_readiness(
    user_id: int,
    course_id: int,
    as_of_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compute readiness metrics for a course.

    Args:
        user_id: The user's ID
        course_id: The course ID
        as_of_date: Date to compute readiness for (default: today)

    Returns:
        Dict with:
        - predicted_marks: float
        - total_marks: int
        - readiness_pct: float (0-100)
        - coverage_pct: float (0-100) - % of topics touched
        - mastery_pct: float (0-100) - raw mastery average
        - retention_pct: float (0-100) - mastery with decay
        - days_left: int or None
        - next_assessment: str or None
        - status: 'on_track' | 'borderline' | 'at_risk'
        - topics: list of topic readiness data
    """
    import pandas as pd
    from services.metrics import compute_mastery, compute_readiness

    today = date.fromisoformat(as_of_date) if as_of_date else date.today()

    # Get course info
    course = get_course(user_id, course_id)
    if not course:
        return {"error": "Course not found"}

    total_marks = course["total_marks"]
    target_marks = course["target_marks"]

    # Get topics
    topics_rows = fetchall(
        "SELECT id, topic_name, weight_points FROM topics WHERE user_id=? AND course_id=?",
        (user_id, course_id)
    )

    if not topics_rows:
        return {
            "predicted_marks": 0,
            "total_marks": total_marks,
            "target_marks": target_marks,
            "readiness_pct": 0,
            "coverage_pct": 0,
            "mastery_pct": 0,
            "retention_pct": 0,
            "days_left": None,
            "next_assessment": None,
            "status": "at_risk",
            "topics": []
        }

    # Compute mastery for each topic
    mastery_data = []
    for row in topics_rows:
        topic_id = row[0]
        m, last_act, ex_cnt, st_cnt, lec_cnt, timed_sig, timed_cnt = compute_mastery(topic_id, today, False)
        mastery_data.append({
            "id": topic_id,
            "topic_name": row[1],
            "weight_points": row[2] or 0,
            "mastery": m,
            "last_activity": last_act,
            "exercises": ex_cnt,
            "study_sessions": st_cnt
        })

    topics_df = pd.DataFrame(mastery_data)
    topics_scored, expected_sum, weight_sum, coverage_pct, mastery_pct, retention_pct = compute_readiness(topics_df, today)

    # Get next due date
    from db import get_next_due_date
    next_due, next_name, _ = get_next_due_date(user_id, course_id, today)
    days_left = (next_due - today).days if next_due else None

    # Predicted marks
    predicted_marks = total_marks * retention_pct

    # Status
    if predicted_marks < target_marks - 10:
        status = "at_risk"
    elif predicted_marks < target_marks:
        status = "borderline"
    else:
        status = "on_track"

    # Topic details
    topics_out = []
    for _, row in topics_scored.iterrows():
        topics_out.append({
            "id": int(row["id"]),
            "name": row["topic_name"],
            "weight_points": float(row["weight_points"]),
            "mastery": round(float(row["mastery"]), 2),
            "readiness": round(float(row["readiness"]), 3),
            "expected_points": round(float(row["expected_points"]), 2),
            "last_activity": str(row["last_activity"]) if row["last_activity"] else None
        })

    return {
        "predicted_marks": round(predicted_marks, 1),
        "total_marks": total_marks,
        "target_marks": target_marks,
        "readiness_pct": round(retention_pct * 100, 1),
        "coverage_pct": round(coverage_pct * 100, 1),
        "mastery_pct": round(mastery_pct * 100, 1),
        "retention_pct": round(retention_pct * 100, 1),
        "days_left": days_left,
        "next_assessment": next_name,
        "status": status,
        "topics": topics_out
    }


def generate_week_plan(
    user_id: int,
    course_id: Optional[int] = None,
    hours_per_week: int = 10,
    session_length_mins: int = 60
) -> Dict[str, Any]:
    """
    Generate a weekly study plan based on gaps and priorities.

    Args:
        user_id: The user's ID
        course_id: Specific course ID, or None for all courses
        hours_per_week: Available study hours per week
        session_length_mins: Preferred session length in minutes

    Returns:
        Dict with:
        - total_sessions: int
        - total_hours: float
        - days: list of day plans with sessions
        - focus_topics: list of priority topics
    """
    from services.dashboard import generate_recommended_tasks

    # Get recommended tasks (sorted by priority)
    tasks = generate_recommended_tasks(user_id, course_id=course_id, max_tasks=20)

    # Calculate available sessions
    total_mins = hours_per_week * 60
    num_sessions = total_mins // session_length_mins

    # Distribute sessions across 7 days (Mon-Sun)
    sessions_per_day = max(1, num_sessions // 7)
    remainder = num_sessions % 7

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    plan_days = []
    task_index = 0

    # Filter to actionable tasks (exclude setup_missing, assessment_due)
    actionable_tasks = [t for t in tasks if t["task_type"] in ("review_topic", "do_exercises", "timed_attempt")]

    for i, day in enumerate(days):
        day_sessions = sessions_per_day + (1 if i < remainder else 0)
        day_plan = {
            "day": day,
            "sessions": []
        }

        for _ in range(day_sessions):
            if task_index < len(actionable_tasks):
                task = actionable_tasks[task_index]
                day_plan["sessions"].append({
                    "duration_mins": session_length_mins,
                    "task_type": task["task_type"],
                    "course": task["course_name"],
                    "topic": task.get("title", "General review"),
                    "detail": task.get("detail", "")
                })
                task_index += 1
            else:
                # Cycle back to start if we have more sessions than tasks
                if actionable_tasks:
                    task = actionable_tasks[task_index % len(actionable_tasks)]
                    day_plan["sessions"].append({
                        "duration_mins": session_length_mins,
                        "task_type": task["task_type"],
                        "course": task["course_name"],
                        "topic": task.get("title", "General review"),
                        "detail": task.get("detail", "")
                    })
                    task_index += 1

        if day_plan["sessions"]:
            plan_days.append(day_plan)

    # Extract focus topics (top 5 unique topics from tasks)
    focus_topics = []
    seen = set()
    for task in actionable_tasks[:10]:
        topic_name = task.get("title", "")
        if topic_name and topic_name not in seen:
            focus_topics.append({
                "topic": topic_name,
                "course": task["course_name"],
                "reason": task.get("detail", "")
            })
            seen.add(topic_name)
        if len(focus_topics) >= 5:
            break

    return {
        "total_sessions": num_sessions,
        "total_hours": round(num_sessions * session_length_mins / 60, 1),
        "session_length_mins": session_length_mins,
        "days": plan_days,
        "focus_topics": focus_topics
    }


# ============================================================================
# ONBOARDING & DEMO DATA
# ============================================================================

# Demo data marker - stored in notes field for easy identification
DEMO_MARKER = "[DEMO]"


def is_empty_account(user_id: int) -> Dict[str, Any]:
    """
    Check if a user account is empty (no courses, topics, or assessments).
    Used to detect first-time users for onboarding.

    Args:
        user_id: The user's ID

    Returns:
        Dict with:
        - is_empty: bool - True if account has no data
        - has_courses: bool
        - has_topics: bool
        - has_assessments: bool
        - course_count: int
        - topic_count: int
        - assessment_count: int
    """
    course_row = fetchone(
        "SELECT COUNT(*) FROM courses WHERE user_id=?",
        (user_id,)
    )
    topic_row = fetchone(
        "SELECT COUNT(*) FROM topics WHERE user_id=?",
        (user_id,)
    )
    assessment_row = fetchone(
        "SELECT COUNT(*) FROM assessments WHERE user_id=?",
        (user_id,)
    )

    course_count = course_row[0] if course_row else 0
    topic_count = topic_row[0] if topic_row else 0
    assessment_count = assessment_row[0] if assessment_row else 0

    return {
        "is_empty": course_count == 0,
        "has_courses": course_count > 0,
        "has_topics": topic_count > 0,
        "has_assessments": assessment_count > 0,
        "course_count": course_count,
        "topic_count": topic_count,
        "assessment_count": assessment_count
    }


def has_demo_data(user_id: int) -> bool:
    """
    Check if user has demo data loaded.

    Args:
        user_id: The user's ID

    Returns:
        True if demo data exists
    """
    # Check for demo course (notes contains DEMO_MARKER)
    # Note: courses don't have notes, so we check assessments
    row = fetchone(
        f"SELECT COUNT(*) FROM assessments WHERE user_id=? AND notes LIKE '%{DEMO_MARKER}%'",
        (user_id,)
    )
    return (row[0] if row else 0) > 0


def load_demo_data(user_id: int) -> Dict[str, Any]:
    """
    Load demo data for a new user to explore the app.
    Creates a sample course with topics and an assessment.

    Demo data is tagged with DEMO_MARKER in notes fields for easy deletion.

    Args:
        user_id: The user's ID

    Returns:
        Dict with created item counts and IDs
    """
    from datetime import date, timedelta

    today = date.today()

    # Check if demo data already exists
    if has_demo_data(user_id):
        return {"error": "Demo data already loaded", "created": False}

    created = {
        "courses": 0,
        "assessments": 0,
        "topics": 0,
        "course_id": None,
        "created": True
    }

    # 1. Create demo course
    course_result = create_course(
        user_id=user_id,
        name="Demo: Introduction to Economics",
        total_marks=100,
        target_marks=75
    )
    course_id = course_result["course_id"]
    created["course_id"] = course_id
    created["courses"] = 1

    # 2. Create demo assessment (exam in 30 days)
    exam_date = (today + timedelta(days=30)).isoformat()
    create_assessment(
        user_id=user_id,
        course_id=course_id,
        name="Final Exam",
        assessment_type="Exam",
        marks=100,
        due_date=exam_date,
        is_timed=True,
        notes=f"{DEMO_MARKER} Sample final exam"
    )
    created["assessments"] = 1

    # 3. Create demo topics (5 topics with varying weights)
    demo_topics = [
        ("Supply and Demand", 25, "Core microeconomics concept"),
        ("Market Equilibrium", 20, "Price determination in markets"),
        ("Elasticity", 15, "Price sensitivity analysis"),
        ("Consumer Theory", 20, "Utility and preferences"),
        ("Production Costs", 20, "Cost structures and optimization"),
    ]

    topic_ids = []
    for name, weight, note in demo_topics:
        topic_result = create_topic(
            user_id=user_id,
            course_id=course_id,
            name=name,
            weight_points=weight,
            notes=f"{DEMO_MARKER} {note}"
        )
        topic_ids.append(topic_result["id"])
    created["topics"] = len(demo_topics)

    # 4. Add sample study activity for the first two topics (to show mastery)
    if topic_ids:
        # Study session for first topic (recent)
        add_study_session(
            topic_id=topic_ids[0],
            session_date=(today - timedelta(days=2)).isoformat(),
            duration_mins=45,
            quality=4,
            notes=f"{DEMO_MARKER} Sample study session"
        )
        # Exercise for first topic
        add_exercise(
            topic_id=topic_ids[0],
            exercise_date=(today - timedelta(days=1)).isoformat(),
            total_questions=10,
            correct_answers=8,
            source="Practice Problems",
            notes=f"{DEMO_MARKER} Sample exercise"
        )
        # Study session for second topic (older, shows decay)
        add_study_session(
            topic_id=topic_ids[1],
            session_date=(today - timedelta(days=7)).isoformat(),
            duration_mins=30,
            quality=3,
            notes=f"{DEMO_MARKER} Sample study session"
        )

    log_event(user_id, "demo_data_loaded", f'{{"course_id": {course_id}}}')

    return created


def delete_demo_data(user_id: int) -> Dict[str, Any]:
    """
    Delete all demo data for a user.
    Removes items tagged with DEMO_MARKER.

    Args:
        user_id: The user's ID

    Returns:
        Dict with deleted item counts
    """
    deleted = {
        "courses": 0,
        "assessments": 0,
        "topics": 0,
        "study_sessions": 0,
        "exercises": 0,
        "deleted": True
    }

    # Find demo topics (by notes marker)
    topic_rows = fetchall(
        f"SELECT id FROM topics WHERE user_id=? AND notes LIKE '%{DEMO_MARKER}%'",
        (user_id,)
    )
    topic_ids = [r[0] for r in (topic_rows or [])]

    if topic_ids:
        # Delete study sessions for demo topics
        with get_conn() as conn:
            cur = conn.cursor()
            placeholder = "%s" if is_postgres() else "?"
            placeholders = ",".join([placeholder] * len(topic_ids))

            # Delete study sessions
            cur.execute(f"DELETE FROM study_sessions WHERE topic_id IN ({placeholders})", topic_ids)
            deleted["study_sessions"] = cur.rowcount if hasattr(cur, 'rowcount') else len(topic_ids)

            # Delete exercises
            cur.execute(f"DELETE FROM exercises WHERE topic_id IN ({placeholders})", topic_ids)
            deleted["exercises"] = cur.rowcount if hasattr(cur, 'rowcount') else len(topic_ids)

            conn.commit()

        # Delete topics
        for topic_id in topic_ids:
            execute("DELETE FROM topics WHERE id=? AND user_id=?", (topic_id, user_id))
        deleted["topics"] = len(topic_ids)

    # Delete demo assessments
    execute(
        f"DELETE FROM assessments WHERE user_id=? AND notes LIKE '%{DEMO_MARKER}%'",
        (user_id,)
    )
    # Count deleted (approximation since we can't get rowcount reliably)
    deleted["assessments"] = 1 if topic_ids else 0

    # Delete demo course (by name pattern)
    execute(
        "DELETE FROM courses WHERE user_id=? AND course_name LIKE 'Demo:%'",
        (user_id,)
    )
    deleted["courses"] = 1 if topic_ids else 0

    log_event(user_id, "demo_data_deleted", None)

    return deleted


def get_onboarding_status(user_id: int) -> Dict[str, Any]:
    """
    Get onboarding checklist status for a user.
    Used to show "Start here" guidance for new users.

    Args:
        user_id: The user's ID

    Returns:
        Dict with:
        - is_new_user: bool - True if account is empty
        - has_demo: bool - True if demo data is loaded
        - checklist: list of {step, label, completed, action}
    """
    account = is_empty_account(user_id)
    has_demo = has_demo_data(user_id)

    # Build checklist
    checklist = [
        {
            "step": 1,
            "label": "Create your first course",
            "completed": account["has_courses"],
            "action": "add_course",
            "icon": "📚"
        },
        {
            "step": 2,
            "label": "Add topics to study",
            "completed": account["has_topics"],
            "action": "add_topics",
            "icon": "📝"
        },
        {
            "step": 3,
            "label": "Set an assessment date",
            "completed": account["has_assessments"],
            "action": "add_assessment",
            "icon": "📅"
        },
        {
            "step": 4,
            "label": "Log your first study session",
            "completed": _has_study_activity(user_id),
            "action": "log_study",
            "icon": "✏️"
        }
    ]

    completed_count = sum(1 for c in checklist if c["completed"])

    return {
        "is_new_user": account["is_empty"],
        "has_demo": has_demo,
        "checklist": checklist,
        "completed_count": completed_count,
        "total_steps": len(checklist),
        "all_complete": completed_count == len(checklist)
    }


def _has_study_activity(user_id: int) -> bool:
    """Check if user has logged any study sessions or exercises."""
    # Check study sessions via topics
    row = fetchone(
        """SELECT COUNT(*) FROM study_sessions ss
           JOIN topics t ON ss.topic_id = t.id
           WHERE t.user_id = ?""",
        (user_id,)
    )
    if row and row[0] > 0:
        return True

    # Check exercises via topics
    row = fetchone(
        """SELECT COUNT(*) FROM exercises e
           JOIN topics t ON e.topic_id = t.id
           WHERE t.user_id = ?""",
        (user_id,)
    )
    return (row[0] if row else 0) > 0


# ============================================================================
# RE-EXPORT EXISTING FUNCTIONS (for convenience)
# ============================================================================

# These are already implemented in other services modules
from services.dashboard import (
    generate_recommended_tasks,
    get_at_risk_courses,
    compute_course_snapshot,
    get_all_courses,
    get_all_upcoming_assessments
)

from services.recommendations import generate_recommendations
