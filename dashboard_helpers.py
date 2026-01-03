"""
Dashboard helper functions for global and course-specific views.
Provides cross-course queries and task recommendation engine.
"""

from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
from db import read_sql, fetchone, fetchall


# ============ CROSS-COURSE QUERIES ============

def get_all_courses(user_id: int) -> pd.DataFrame:
    """Get all courses for a user."""
    return read_sql(
        "SELECT id, course_name, total_marks, target_marks FROM courses WHERE user_id=? ORDER BY id",
        (user_id,)
    )


def get_all_upcoming_assessments(user_id: int, days_ahead: int = 30) -> pd.DataFrame:
    """
    Get all upcoming assessments across all courses within the next N days.
    Returns: DataFrame with course_id, course_name, assessment details.
    """
    today = date.today()
    cutoff_date = today + timedelta(days=days_ahead)

    query = """
        SELECT
            a.id, a.course_id, c.course_name,
            a.assessment_name, a.assessment_type, a.marks, a.actual_marks,
            a.due_date, a.is_timed, a.progress_pct
        FROM assessments a
        JOIN courses c ON a.course_id = c.id
        WHERE a.user_id = ?
          AND a.due_date IS NOT NULL
          AND a.due_date >= ?
          AND a.due_date <= ?
          AND a.actual_marks IS NULL
        ORDER BY a.due_date ASC, a.course_id
    """
    return read_sql(query, (user_id, str(today), str(cutoff_date)))


def get_course_assessment_count(user_id: int, course_id: int) -> int:
    """Get count of assessments for a course."""
    row = fetchone(
        "SELECT COUNT(*) FROM assessments WHERE user_id=? AND course_id=?",
        (user_id, course_id)
    )
    return row[0] if row else 0


def get_course_topic_count(user_id: int, course_id: int) -> int:
    """Get count of topics for a course."""
    row = fetchone(
        "SELECT COUNT(*) FROM topics WHERE user_id=? AND course_id=?",
        (user_id, course_id)
    )
    return row[0] if row else 0


def get_last_timed_attempt_date(user_id: int, course_id: int) -> Optional[date]:
    """Get the date of the last timed attempt for a course."""
    row = fetchone(
        "SELECT MAX(attempt_date) FROM timed_attempts WHERE user_id=? AND course_id=?",
        (user_id, course_id)
    )
    if row and row[0]:
        return pd.to_datetime(row[0]).date()
    return None


# ============ COURSE SNAPSHOT ============

def compute_course_snapshot(
    user_id: int,
    course_id: int,
    topics_with_mastery: pd.DataFrame = None,
    retention_pct: float = None
) -> Dict:
    """
    Compute a snapshot of course metrics.
    Returns: {
        'course_id': int,
        'course_name': str,
        'predicted_marks': float,
        'total_marks': int,
        'target_marks': int,
        'readiness_pct': float,
        'days_left': int,
        'next_due_date': date or None,
        'next_assessment_name': str or None,
        'status': str ('on_track', 'borderline', 'at_risk'),
        'has_topics': bool,
        'has_assessments': bool
    }
    """
    from db import get_course_total_marks, get_next_due_date

    # Get course details
    course_row = fetchone(
        "SELECT course_name, total_marks, target_marks FROM courses WHERE id=? AND user_id=?",
        (course_id, user_id)
    )
    if not course_row:
        return None

    course_name = course_row[0]
    total_marks = course_row[1] or 120
    target_marks = course_row[2] or 90

    # Get assessment info
    today = date.today()
    next_due, next_assessment_name, next_is_timed = get_next_due_date(user_id, course_id, today)
    days_left = (next_due - today).days if next_due else None

    # Check if course has content
    has_topics = get_course_topic_count(user_id, course_id) > 0
    has_assessments = get_course_assessment_count(user_id, course_id) > 0

    # Calculate readiness and predicted marks
    if retention_pct is None and has_topics:
        # Compute it if not provided
        from app import compute_readiness
        if topics_with_mastery is not None:
            _, _, _, _, _, retention_pct = compute_readiness(topics_with_mastery, today)
        else:
            retention_pct = 0.0
    elif retention_pct is None:
        retention_pct = 0.0

    predicted_marks = total_marks * retention_pct

    # Determine status
    if predicted_marks < target_marks - 10:
        status = 'at_risk'
    elif predicted_marks < target_marks:
        status = 'borderline'
    else:
        status = 'on_track'

    return {
        'course_id': course_id,
        'course_name': course_name,
        'predicted_marks': predicted_marks,
        'total_marks': total_marks,
        'target_marks': target_marks,
        'readiness_pct': retention_pct * 100,
        'days_left': days_left,
        'next_due_date': next_due,
        'next_assessment_name': next_assessment_name,
        'status': status,
        'has_topics': has_topics,
        'has_assessments': has_assessments
    }


# ============ TASK RECOMMENDATION ENGINE ============

def generate_recommended_tasks(
    user_id: int,
    course_id: Optional[int] = None,
    max_tasks: int = 10
) -> List[Dict]:
    """
    Generate recommended study tasks for a user.

    If course_id is None: generates tasks across all courses (Global view)
    If course_id is specified: generates tasks for that course only (Course view)

    Returns: List of task dicts with fields:
        - task_type: str ('assessment_due', 'review_topic', 'do_exercises', 'timed_attempt', 'setup_missing')
        - course_id: int
        - course_name: str
        - title: str (short)
        - detail: str (1 line)
        - due_date: date or None
        - priority_score: float
        - est_minutes: int or None
        - topic_id: int or None (for topic-specific tasks)
    """
    tasks = []
    today = date.today()

    # Determine which courses to process
    if course_id:
        courses_df = read_sql(
            "SELECT id, course_name FROM courses WHERE user_id=? AND id=?",
            (user_id, course_id)
        )
    else:
        courses_df = get_all_courses(user_id)

    if courses_df.empty:
        return []

    for _, course in courses_df.iterrows():
        cid = int(course['id'])
        cname = course['course_name']

        # Check if course has basic setup
        has_topics = get_course_topic_count(user_id, cid) > 0
        has_assessments = get_course_assessment_count(user_id, cid) > 0

        # Rule: Missing setup tasks (highest priority)
        if not has_assessments:
            tasks.append({
                'task_type': 'setup_missing',
                'course_id': cid,
                'course_name': cname,
                'title': f'Add assessments for {cname}',
                'detail': 'No assessments with due dates found. Add them to track progress.',
                'due_date': None,
                'priority_score': 1000,  # Very high priority
                'est_minutes': 10,
                'topic_id': None
            })

        if not has_topics:
            tasks.append({
                'task_type': 'setup_missing',
                'course_id': cid,
                'course_name': cname,
                'title': f'Add topics for {cname}',
                'detail': 'No topics found. Add or import topics to get recommendations.',
                'due_date': None,
                'priority_score': 1000,
                'est_minutes': 15,
                'topic_id': None
            })
            continue  # Skip other tasks if no topics

        # Get next assessment due date
        from db import get_next_due_date
        next_due, next_assessment_name, _ = get_next_due_date(user_id, cid, today)
        days_left = (next_due - today).days if next_due else 999

        # Rule 1: Assessment due soon (add to task list)
        if next_due and days_left <= 30:
            urgency_score = 100 + (30 - days_left) * 10  # More urgent = higher score
            tasks.append({
                'task_type': 'assessment_due',
                'course_id': cid,
                'course_name': cname,
                'title': f'{next_assessment_name}',
                'detail': f'Due in {days_left} days',
                'due_date': next_due,
                'priority_score': urgency_score,
                'est_minutes': None,
                'topic_id': None
            })

        # Rule 2: Timed attempt recommendation (if due soon and no recent attempts)
        if days_left <= 14:
            last_timed = get_last_timed_attempt_date(user_id, cid)
            days_since_timed = (today - last_timed).days if last_timed else 999

            if days_since_timed >= 7:
                tasks.append({
                    'task_type': 'timed_attempt',
                    'course_id': cid,
                    'course_name': cname,
                    'title': f'Practice exam for {cname}',
                    'detail': f'Exam in {days_left} days — do a timed practice attempt',
                    'due_date': next_due,
                    'priority_score': 90 + (14 - days_left) * 5,
                    'est_minutes': 90,
                    'topic_id': None
                })

        # Rule 3: Topic-specific recommendations (gap-based)
        topics_df = read_sql(
            "SELECT id, topic_name, weight_points FROM topics WHERE user_id=? AND course_id=? ORDER BY id",
            (user_id, cid)
        )

        if not topics_df.empty:
            # Import compute_mastery and compute_readiness
            from app import compute_mastery, compute_readiness

            # Calculate mastery and readiness for each topic
            mastery_data = []
            for _, row in topics_df.iterrows():
                topic_id = int(row['id'])
                m, last_act, ex_cnt, st_cnt, lec_cnt, timed_sig, timed_cnt = compute_mastery(topic_id, today, False)
                mastery_data.append({
                    'id': topic_id,
                    'topic_name': row['topic_name'],
                    'weight_points': row['weight_points'],
                    'mastery': m,
                    'last_activity': last_act,
                    'exercises': ex_cnt,
                    'study_sessions': st_cnt
                })

            topics_with_mastery = pd.DataFrame(mastery_data)
            topics_scored, _, weight_sum, _, _, _ = compute_readiness(topics_with_mastery, today)

            # Calculate gap scores
            if weight_sum > 0:
                topics_scored['gap_score'] = topics_scored['weight_points'] * (1.0 - topics_scored['readiness'])
            else:
                # Equal weights fallback
                topics_scored['gap_score'] = (1.0 / len(topics_scored)) * (1.0 - topics_scored['readiness'])

            # Sort by gap score and recommend top 2
            top_gaps = topics_scored.nlargest(2, 'gap_score')

            for _, gap_topic in top_gaps.iterrows():
                topic_id = int(gap_topic['id'])
                topic_name = gap_topic['topic_name']
                mastery = gap_topic['mastery']
                ex_count = gap_topic['exercises']
                gap_score = gap_topic['gap_score']

                # Priority based on gap size and exam proximity
                base_priority = gap_score * 50
                if days_left <= 14:
                    base_priority *= 1.5

                # Task A: Review if mastery is low
                if mastery < 3:
                    tasks.append({
                        'task_type': 'review_topic',
                        'course_id': cid,
                        'course_name': cname,
                        'title': f'Review: {topic_name}',
                        'detail': f'Low mastery ({mastery:.1f}/5) — review notes and materials',
                        'due_date': next_due,
                        'priority_score': base_priority + 10,
                        'est_minutes': 45,
                        'topic_id': topic_id
                    })

                # Task B: Do exercises if count is low
                if ex_count < 3:
                    tasks.append({
                        'task_type': 'do_exercises',
                        'course_id': cid,
                        'course_name': cname,
                        'title': f'Practice: {topic_name}',
                        'detail': f'Only {ex_count} exercise sessions — do 5-10 problems',
                        'due_date': next_due,
                        'priority_score': base_priority,
                        'est_minutes': 60,
                        'topic_id': topic_id
                    })

    # Sort tasks by priority
    # Primary: due_date (soonest first, None at end)
    # Secondary: priority_score (highest first)
    tasks_sorted = sorted(
        tasks,
        key=lambda t: (
            t['due_date'] if t['due_date'] else date(2099, 12, 31),  # Push None to end
            -t['priority_score']  # Higher score = higher priority
        )
    )

    return tasks_sorted[:max_tasks]


def get_at_risk_courses(user_id: int, readiness_threshold: float = 0.6, days_threshold: int = 21) -> List[Dict]:
    """
    Identify courses that are at risk (low readiness + due soon).

    Returns: List of course snapshots that meet at-risk criteria
    """
    at_risk = []
    courses = get_all_courses(user_id)
    today = date.today()

    for _, course in courses.iterrows():
        cid = int(course['id'])

        # Check if course has topics
        if get_course_topic_count(user_id, cid) == 0:
            continue

        # Get next due date
        from db import get_next_due_date
        next_due, _, _ = get_next_due_date(user_id, cid, today)

        if not next_due:
            continue

        days_left = (next_due - today).days

        if days_left > days_threshold:
            continue

        # Compute readiness (simplified)
        topics_df = read_sql(
            "SELECT id, topic_name, weight_points FROM topics WHERE user_id=? AND course_id=?",
            (user_id, cid)
        )

        if topics_df.empty:
            continue

        from app import compute_mastery, compute_readiness

        mastery_data = []
        for _, row in topics_df.iterrows():
            topic_id = int(row['id'])
            m, last_act, ex_cnt, st_cnt, lec_cnt, timed_sig, timed_cnt = compute_mastery(topic_id, today, False)
            mastery_data.append({
                'id': topic_id,
                'topic_name': row['topic_name'],
                'weight_points': row['weight_points'],
                'mastery': m,
                'last_activity': last_act,
                'exercises': ex_cnt,
                'study_sessions': st_cnt
            })

        topics_with_mastery = pd.DataFrame(mastery_data)
        _, _, _, _, _, retention_pct = compute_readiness(topics_with_mastery, today)

        if retention_pct < readiness_threshold:
            snapshot = compute_course_snapshot(user_id, cid, topics_with_mastery, retention_pct)
            if snapshot:
                at_risk.append(snapshot)

    return at_risk
