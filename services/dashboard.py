"""
Dashboard helper functions for global and course-specific views.
Provides cross-course queries and task recommendation engine.

NO Streamlit dependencies - pure Python business logic.
"""

from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import sys
import os

# Add parent directory to path for db import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import read_sql, fetchone, fetchall

# ============ DEBUG FLAG ============
# Set to True to print diagnostic info for prediction consistency debugging.
# This helps verify that At-Risk, All Courses Summary, and Course Dashboard
# all compute the same predicted values for the same course.
DEBUG_PREDICTION = False


# ============ PREDICTION MATURITY ============

def compute_prediction_maturity(
    days_left: int,
    lectures_occurred: int = 0,
    total_lectures_planned: int = 0,
    study_sessions: int = 0,
    exercises: int = 0,
    timed_attempts: int = 0
) -> Dict:
    """
    Compute prediction maturity/confidence based on available evidence.

    Args:
        days_left: Days until exam/assessment
        lectures_occurred: Number of lectures that have occurred/attended
        total_lectures_planned: Total lectures planned (0 if unknown)
        study_sessions: Count of study sessions logged
        exercises: Count of exercise sets completed
        timed_attempts: Count of timed practice attempts

    Returns:
        {
            'maturity_score': float in [0,1],
            'maturity_tier': 'EARLY' | 'MID' | 'LATE',
            'reason': str (short explanation for tooltip)
        }
    """
    # Component 1: Time factor (0-0.4)
    # More days left = lower maturity (predictions are less reliable far from exam)
    if days_left is None or days_left > 60:
        time_factor = 0.0
    elif days_left > 30:
        time_factor = 0.1 + (60 - days_left) / 30 * 0.1  # 0.1 to 0.2
    elif days_left > 14:
        time_factor = 0.2 + (30 - days_left) / 16 * 0.1  # 0.2 to 0.3
    elif days_left > 7:
        time_factor = 0.3 + (14 - days_left) / 7 * 0.05  # 0.3 to 0.35
    else:
        time_factor = 0.35 + max(0, 7 - days_left) / 7 * 0.05  # 0.35 to 0.4

    # Component 2: Lecture progress factor (0-0.3)
    # More lectures completed = higher maturity
    if total_lectures_planned > 0:
        lecture_progress = lectures_occurred / total_lectures_planned
        lecture_factor = lecture_progress * 0.3
    else:
        # No lectures planned - give partial credit if we have other evidence
        lecture_factor = 0.1 if (study_sessions + exercises + timed_attempts) > 0 else 0.0

    # Component 3: Evidence volume factor (0-0.3)
    # More study evidence = higher maturity
    evidence_count = study_sessions + exercises + timed_attempts
    if evidence_count == 0:
        evidence_factor = 0.0
    elif evidence_count < 3:
        evidence_factor = 0.05
    elif evidence_count < 10:
        evidence_factor = 0.1 + (evidence_count - 3) / 7 * 0.1  # 0.1 to 0.2
    elif evidence_count < 20:
        evidence_factor = 0.2 + (evidence_count - 10) / 10 * 0.05  # 0.2 to 0.25
    else:
        evidence_factor = 0.25 + min((evidence_count - 20) / 30, 1.0) * 0.05  # 0.25 to 0.3

    # Combine factors
    maturity_score = min(1.0, time_factor + lecture_factor + evidence_factor)

    # Determine tier and reason
    if maturity_score < 0.35:
        maturity_tier = "EARLY"
        if days_left is not None and days_left > 30:
            reason = f"{days_left} days left, limited data"
        elif evidence_count < 3:
            reason = "Insufficient study data"
        else:
            reason = "Early in study cycle"
    elif maturity_score < 0.65:
        maturity_tier = "MID"
        if lecture_factor < 0.15 and total_lectures_planned > 0:
            reason = "More lectures needed"
        elif evidence_count < 10:
            reason = "Building evidence"
        else:
            reason = "Moderate confidence"
    else:
        maturity_tier = "LATE"
        if days_left is not None and days_left <= 7:
            reason = "Exam approaching"
        elif evidence_count >= 20:
            reason = "Strong evidence base"
        else:
            reason = "High confidence"

    return {
        'maturity_score': round(maturity_score, 2),
        'maturity_tier': maturity_tier,
        'reason': reason
    }


def compute_maturity_aware_status(
    predicted_marks: float,
    target_marks: float,
    total_marks: float,
    maturity_tier: str
) -> str:
    """
    Compute status label using maturity-aware thresholds.

    Margins tighten as exam approaches:
    - EARLY: 15% margin, never show 'at_risk'
    - MID: 8% margin, 'at_risk' only for significant gaps
    - LATE: 4% margin, strongest labels

    Returns: status string
    """
    # Calculate margins as percentage of total marks
    if maturity_tier == "EARLY":
        margin = total_marks * 0.15
        # Never show 'at_risk' in early stage
        if predicted_marks >= target_marks:
            return 'on_track'
        elif predicted_marks >= target_marks - margin:
            return 'on_track'  # Within early margin, still OK
        else:
            return 'early_signal'  # Below target but too early to call at_risk

    elif maturity_tier == "MID":
        margin = total_marks * 0.08
        if predicted_marks >= target_marks:
            return 'on_track'
        elif predicted_marks >= target_marks - margin:
            return 'borderline'
        else:
            return 'at_risk'

    else:  # LATE
        margin = total_marks * 0.04
        if predicted_marks >= target_marks:
            return 'on_track'
        elif predicted_marks >= target_marks - margin:
            return 'borderline'
        else:
            return 'at_risk'


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
    retention_pct: float = None,
    is_retake: bool = False
) -> Dict:
    """
    Compute a snapshot of course metrics.
    
    This is the CANONICAL function for computing course predictions.
    ALL views (At-Risk, All Courses Summary, Course Dashboard) MUST use this.
    
    The prediction includes:
    - Base readiness from topic mastery
    - Practice blend (timed attempt scores weighted by exam proximity)
    - Actual marks from completed assessments
    - Proper weight scaling
    
    Args:
        user_id: The user's ID
        course_id: The course ID
        topics_with_mastery: Pre-computed mastery data (optional, will compute if None)
        retention_pct: Pre-computed retention (optional, will compute if None)
        is_retake: If True, excludes lectures from mastery calculation
    
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
        'has_assessments': bool,
        'topic_count': int,
        'coverage_pct': float,
        'mastery_pct': float,
        'practice_blend': float,
        'has_actual_marks': bool,
        'actual_marks_earned': float,
        'actual_marks_possible': float
    }
    """
    from db import get_next_due_date
    from services.metrics import compute_mastery, compute_readiness

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
    days_left = (next_due - today).days if next_due else 30  # Default 30 days if no due date

    # Check if course has content
    topic_count = get_course_topic_count(user_id, course_id)
    has_topics = topic_count > 0
    has_assessments = get_course_assessment_count(user_id, course_id) > 0

    # Initialize metrics
    coverage_pct = 0.0
    mastery_pct = 0.0
    weight_sum = 0.0
    practice_blend = 0.0
    topics_scored = None

    # ============ STEP 1: Compute base mastery and readiness ============
    if has_topics:
        # Compute mastery data if not provided
        if topics_with_mastery is None:
            topics_df = read_sql(
                "SELECT id, topic_name, weight_points FROM topics WHERE user_id=? AND course_id=?",
                (user_id, course_id)
            )
            if not topics_df.empty:
                mastery_data = []
                for _, row in topics_df.iterrows():
                    topic_id = int(row['id'])
                    m, last_act, ex_cnt, st_cnt, lec_cnt, timed_sig, timed_cnt = compute_mastery(topic_id, today, is_retake)
                    mastery_data.append({
                        'id': topic_id,
                        'topic_name': row['topic_name'],
                        'weight_points': row['weight_points'] or 0,
                        'mastery': m,
                        'last_activity': last_act,
                        'exercises': ex_cnt,
                        'study_sessions': st_cnt,
                        'timed_signal': timed_sig,
                        'timed_count': timed_cnt
                    })
                topics_with_mastery = pd.DataFrame(mastery_data)
        
        # Compute readiness from mastery data
        if topics_with_mastery is not None and not topics_with_mastery.empty:
            topics_scored, expected_sum, weight_sum, coverage_pct, mastery_pct, retention_pct = compute_readiness(topics_with_mastery, today)
        else:
            retention_pct = 0.0
            expected_sum = 0.0
    else:
        retention_pct = 0.0 if retention_pct is None else retention_pct
        expected_sum = 0.0

    # ============ STEP 2: Apply practice blend (timed attempt weighting) ============
    if topics_scored is not None and not topics_scored.empty and 'timed_signal' in topics_scored.columns:
        # Time-based component (0.1 to 0.6 based on days left)
        if days_left >= 60:
            time_blend = 0.1
        elif days_left >= 30:
            time_blend = 0.1 + (60 - days_left) / 30 * 0.15
        elif days_left >= 14:
            time_blend = 0.25 + (30 - days_left) / 16 * 0.15
        elif days_left >= 7:
            time_blend = 0.4 + (14 - days_left) / 7 * 0.1
        elif days_left >= 0:
            time_blend = 0.5 + (7 - days_left) / 7 * 0.1
        else:
            time_blend = 0.6

        # Lecture progress component (adds up to 0.2)
        lecture_blend = 0.0
        if not is_retake:
            lecture_data = read_sql("""
                SELECT COUNT(*) as total, SUM(CASE WHEN attended=1 THEN 1 ELSE 0 END) as attended
                FROM scheduled_lectures WHERE user_id=? AND course_id=?
            """, (user_id, course_id))
            if not lecture_data.empty:
                total_lec = int(lecture_data.iloc[0]["total"] or 0)
                attended_lec = int(lecture_data.iloc[0]["attended"] or 0)
                if total_lec > 0:
                    lecture_blend = (attended_lec / total_lec) * 0.2

        practice_blend = min(time_blend + lecture_blend, 0.7)

        # Apply blending if there are timed signals
        has_timed_signals = topics_scored["timed_signal"].sum() > 0
        if practice_blend > 0 and has_timed_signals:
            blended_readiness = []
            for _, row in topics_scored.iterrows():
                base_readiness = row["readiness"]
                timed_sig = row.get("timed_signal", 0.0) or 0.0
                if timed_sig > 0:
                    blended = (1 - practice_blend) * base_readiness + practice_blend * timed_sig
                else:
                    blended = base_readiness
                blended_readiness.append(blended)
            topics_scored["blended_readiness"] = blended_readiness
            topics_scored["expected_points"] = topics_scored["weight_points"] * topics_scored["blended_readiness"]
            expected_sum = topics_scored["expected_points"].sum()
            retention_pct = (topics_scored["weight_points"] * topics_scored["blended_readiness"]).sum() / weight_sum if weight_sum > 0 else 0

    # ============ STEP 3: Scale by weight sum ============
    base_pred = expected_sum
    if weight_sum and abs(weight_sum - float(total_marks)) > 1e-6:
        base_pred *= float(total_marks) / float(weight_sum)
    predicted_marks = base_pred

    # ============ STEP 4: Incorporate actual marks from completed assessments ============
    actual_marks_earned = 0.0
    actual_marks_possible = 0.0
    has_actual_marks = False

    completed_assessments = read_sql("""
        SELECT marks, actual_marks FROM assessments 
        WHERE user_id=? AND course_id=? AND actual_marks IS NOT NULL
    """, (user_id, course_id))

    completed_exams = read_sql("""
        SELECT marks, actual_marks FROM exams 
        WHERE user_id=? AND course_id=? AND actual_marks IS NOT NULL
    """, (user_id, course_id))

    if not completed_assessments.empty:
        actual_marks_earned += float(completed_assessments["actual_marks"].sum())
        actual_marks_possible += float(completed_assessments["marks"].sum())

    if not completed_exams.empty:
        actual_marks_earned += float(completed_exams["actual_marks"].sum())
        actual_marks_possible += float(completed_exams["marks"].sum())

    remaining_marks = total_marks - actual_marks_possible

    if actual_marks_possible > 0:
        has_actual_marks = True
        if remaining_marks > 0:
            # Blend actual results with predictions for remaining
            predicted_remaining = (predicted_marks / total_marks) * remaining_marks if total_marks > 0 else 0
            predicted_marks = actual_marks_earned + predicted_remaining
        else:
            # All assessments completed
            predicted_marks = actual_marks_earned

    # ============ STEP 5: Compute prediction maturity and status ============
    # Gather evidence counts for maturity calculation
    total_study_sessions = 0
    total_exercises = 0
    total_timed_attempts = 0

    if topics_with_mastery is not None and not topics_with_mastery.empty:
        if 'study_sessions' in topics_with_mastery.columns:
            total_study_sessions = int(topics_with_mastery['study_sessions'].sum())
        if 'exercises' in topics_with_mastery.columns:
            total_exercises = int(topics_with_mastery['exercises'].sum())
        if 'timed_count' in topics_with_mastery.columns:
            total_timed_attempts = int(topics_with_mastery['timed_count'].sum())

    # Get lecture counts (reuse lecture_data if already queried, else query now)
    lectures_occurred = 0
    total_lectures_planned = 0
    if not is_retake:
        lecture_counts = read_sql("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN lecture_date <= ? THEN 1 ELSE 0 END) as occurred
            FROM scheduled_lectures WHERE user_id=? AND course_id=?
        """, (str(date.today()), user_id, course_id))
        if not lecture_counts.empty:
            total_lectures_planned = int(lecture_counts.iloc[0]["total"] or 0)
            lectures_occurred = int(lecture_counts.iloc[0]["occurred"] or 0)

    # Compute prediction maturity
    maturity = compute_prediction_maturity(
        days_left=days_left,
        lectures_occurred=lectures_occurred,
        total_lectures_planned=total_lectures_planned,
        study_sessions=total_study_sessions,
        exercises=total_exercises,
        timed_attempts=total_timed_attempts
    )

    # Compute maturity-aware status
    status = compute_maturity_aware_status(
        predicted_marks=predicted_marks,
        target_marks=target_marks,
        total_marks=total_marks,
        maturity_tier=maturity['maturity_tier']
    )

    # Debug output if enabled
    if DEBUG_PREDICTION:
        print(f"[DEBUG_PREDICTION] compute_course_snapshot:")
        print(f"  user_id={user_id}, course_id={course_id}, course_name={course_name}")
        print(f"  topic_count={topic_count}, weight_sum={weight_sum:.1f}")
        print(f"  retention_pct={retention_pct:.4f}, practice_blend={practice_blend:.2f}")
        print(f"  actual_marks={actual_marks_earned:.1f}/{actual_marks_possible:.1f}")
        print(f"  predicted_marks={predicted_marks:.1f}/{total_marks}, status={status}")

    return {
        'course_id': course_id,
        'course_name': course_name,
        'predicted_marks': predicted_marks,
        'total_marks': total_marks,
        'target_marks': target_marks,
        'readiness_pct': retention_pct * 100 if retention_pct else 0.0,
        'days_left': days_left if next_due else None,
        'next_due_date': next_due,
        'next_assessment_name': next_assessment_name,
        'status': status,
        'has_topics': has_topics,
        'has_assessments': has_assessments,
        'topic_count': topic_count,
        'coverage_pct': coverage_pct * 100 if coverage_pct else 0.0,
        'mastery_pct': mastery_pct * 100 if mastery_pct else 0.0,
        'practice_blend': practice_blend * 100,
        'has_actual_marks': has_actual_marks,
        'actual_marks_earned': actual_marks_earned,
        'actual_marks_possible': actual_marks_possible,
        # Maturity info for confidence indicator
        'maturity_score': maturity['maturity_score'],
        'maturity_tier': maturity['maturity_tier'],
        'maturity_reason': maturity['reason']
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
            from services.metrics import compute_mastery, compute_readiness

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
    
    Uses compute_course_snapshot for consistent predictions across all views.
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

        # Use canonical snapshot function
        snapshot = compute_course_snapshot(user_id, cid)
        
        if snapshot and snapshot['readiness_pct'] < readiness_threshold * 100:
            at_risk.append(snapshot)

    return at_risk


# ============ PREREQUISITE STEP LOGIC ============

def get_next_prerequisite_step(user_id: int, course_id: int) -> Optional[Dict]:
    """
    Determine the next prerequisite step for a course to guide users.

    Returns:
        None if all prerequisites are complete, otherwise a dict with:
        - step_type: 'assessments' | 'topics'
        - button_label: e.g., "Add assessment"
        - message: Brief explanation
        - tab_index: Which tab to navigate to (1=Assessments, 3=Topics)
    """
    assessment_count = get_course_assessment_count(user_id, course_id)
    topic_count = get_course_topic_count(user_id, course_id)

    if assessment_count == 0:
        return {
            'step_type': 'assessments',
            'button_label': 'Add assessment',
            'message': 'Add an assessment with a due date to track your progress.',
            'tab_index': 1
        }

    if topic_count == 0:
        return {
            'step_type': 'topics',
            'button_label': 'Add topics',
            'message': 'Add topics to get personalized study recommendations.',
            'tab_index': 3
        }

    return None  # All prerequisites complete
