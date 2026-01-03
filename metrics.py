"""
Metric computation functions for topic mastery and readiness.
These are pure computation functions with NO Streamlit UI dependencies.
"""

from datetime import date
import pandas as pd
from db import fetchone, fetchall


def compute_mastery(topic_id: int, today: date, is_retake: bool = False) -> tuple:
    """
    Compute mastery (0-5) based on:
    - Exercises: 50% weight (60% if retake)
    - Study sessions: 35% weight (40% if retake)
    - Lectures: 15% weight (0% if retake - no lectures for retakes)
    - Timed attempts: boost exercise_score by up to 20% based on timed performance
    """
    exercises = fetchall("""
        SELECT exercise_date, total_questions, correct_answers
        FROM exercises WHERE topic_id=? ORDER BY exercise_date DESC
    """, (topic_id,))

    exercise_score = 0.0
    exercise_count = len(exercises)
    if exercises:
        total_q = sum(e[1] for e in exercises)
        total_correct = sum(e[2] for e in exercises)
        if total_q > 0:
            success_rate = total_correct / total_q
            recent_exercises = [e for e in exercises if (today - pd.to_datetime(e[0]).date()).days <= 14]
            recency_bonus = min(len(recent_exercises) * 0.2, 1.0)
            exercise_score = success_rate * (0.7 + 0.3 * recency_bonus)

    # Boost exercise_score based on timed attempts that include this topic
    topic_row = fetchone("SELECT course_id, topic_name FROM topics WHERE id=?", (topic_id,))
    timed_boost = 0.0
    timed_signal = 0.0  # Average score from timed attempts for this topic
    timed_count = 0

    if topic_row:
        course_id_topic, topic_name = topic_row
        timed_attempts = fetchall("""
            SELECT attempt_date, score_pct, topics
            FROM timed_attempts WHERE course_id=? ORDER BY attempt_date DESC
        """, (course_id_topic,))

        topic_timed_scores = []
        for ta in timed_attempts:
            topics_in_attempt = ta[2] or ""
            if topic_name.lower() in topics_in_attempt.lower():
                score_pct = float(ta[1])
                days_ago = (today - pd.to_datetime(ta[0]).date()).days
                # Apply decay: recent attempts matter more
                decay = 1.0 if days_ago <= 7 else (0.9 if days_ago <= 14 else (0.7 if days_ago <= 30 else 0.5))
                topic_timed_scores.append(score_pct * decay)
                timed_count += 1

        if topic_timed_scores:
            avg_timed_score = sum(topic_timed_scores) / len(topic_timed_scores)
            timed_signal = avg_timed_score  # Store for later blending
            # Boost up to +20% of exercise_score based on timed performance
            timed_boost = min(avg_timed_score * 0.2, 0.2)
            exercise_score = min(exercise_score + timed_boost, 1.0)

    sessions = fetchall("""
        SELECT session_date, duration_mins, quality
        FROM study_sessions WHERE topic_id=? ORDER BY session_date DESC
    """, (topic_id,))

    study_score = 0.0
    study_count = len(sessions)
    if sessions:
        weighted_sessions = 0.0
        for s in sessions:
            days_ago = (today - pd.to_datetime(s[0]).date()).days
            quality = s[2] / 5.0
            duration_factor = min(s[1] / 60.0, 1.5)
            decay = 1.0 if days_ago <= 7 else (0.8 if days_ago <= 14 else (0.6 if days_ago <= 30 else 0.4))
            weighted_sessions += quality * duration_factor * decay
        study_score = min(weighted_sessions / 3.0, 1.0)

    lecture_score = 0.0
    lecture_count = 0

    # Only count lectures if not a retake
    if not is_retake:
        if topic_row:
            lectures = fetchall("""
                SELECT lecture_date, attended, topics_planned
                FROM scheduled_lectures WHERE course_id=? AND attended=1
            """, (course_id_topic,))

            for lec in lectures:
                topics_covered = lec[2] or ""
                if topic_name.lower() in topics_covered.lower():
                    lecture_count += 1
            lecture_score = min(lecture_count * 0.4, 1.0)

    # Adjust weights based on retake status
    if is_retake:
        mastery = (exercise_score * 3.0) + (study_score * 2.0)
    else:
        mastery = (exercise_score * 2.5) + (study_score * 1.75) + (lecture_score * 0.75)

    mastery = min(mastery, 5.0)

    all_dates = []
    for e in exercises:
        all_dates.append(pd.to_datetime(e[0]).date())
    for s in sessions:
        all_dates.append(pd.to_datetime(s[0]).date())
    last_activity = max(all_dates) if all_dates else None

    return mastery, last_activity, exercise_count, study_count, lecture_count, timed_signal, timed_count


def decay_factor(days_since: int) -> float:
    """Calculate decay factor based on days since last activity."""
    if days_since <= 7:
        return 1.0
    if days_since <= 14:
        return 0.85
    if days_since <= 30:
        return 0.70
    return 0.55


def compute_readiness(topics_with_mastery: pd.DataFrame, today: date):
    """
    Compute readiness scores for topics based on mastery and recency.
    Returns: (df_with_readiness, total_expected, total_weight, coverage_pct, mastery_pct, retention_pct)
    """
    df = topics_with_mastery.copy()

    readiness_vals = []
    for _, r in df.iterrows():
        m = float(r["mastery"]) if pd.notna(r["mastery"]) else 0
        lr = r["last_activity"]
        if pd.isna(lr) or lr is None:
            dec = 0.6 if m > 0 else 0.0
        else:
            if isinstance(lr, str):
                lr_date = pd.to_datetime(lr).date()
            else:
                lr_date = lr
            days_since = (today - lr_date).days
            dec = decay_factor(days_since)
        readiness_vals.append((m / 5.0) * dec)

    df["readiness"] = readiness_vals
    df["expected_points"] = df["weight_points"] * df["readiness"]

    total_weight = float(df["weight_points"].sum()) if not df.empty else 0.0
    total_expected = float(df["expected_points"].sum()) if not df.empty else 0.0

    coverage_pct = (df.loc[df["mastery"] >= 1, "weight_points"].sum() / total_weight) if total_weight > 0 else 0.0
    mastery_pct = (float((df["weight_points"] * (df["mastery"] / 5.0)).sum()) / total_weight) if total_weight > 0 else 0.0
    retention_pct = (float((df["weight_points"] * df["readiness"]).sum()) / total_weight) if total_weight > 0 else 0.0

    return df, total_expected, total_weight, coverage_pct, mastery_pct, retention_pct
